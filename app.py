"""
Smart Farm Hub V1.0 - Backend Server
แก้ไขระบบตรวจจับประเภทโหนด ESP8266/ESP32
"""

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import sqlite3
from datetime import datetime
import os

# Configuration
DATABASE_PATH = os.environ.get('SMART_DB_PATH', 'farm_data.db')
# Read SECRET_KEY from environment for security; fallback kept for backwards compatibility
SECRET_KEY = os.environ.get('SMART_FARM_SECRET_KEY', 'smart-farm-secret-key-v1')

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Global variables สำหรับเก็บสถานะ
node_states = {}      # เก็บข้อมูลเซ็นเซอร์ล่าสุดของแต่ละ node
node_commands = {}    # เก็บคำสั่งควบคุมสำหรับแต่ละ node
node_types = {}       # เก็บประเภทของแต่ละโหนด (esp8266 หรือ esp32)
node_pin_info = {}    # เก็บข้อมูล pin ของแต่ละโหนด
notifications = []    # เก็บการแจ้งเตือน
notification_id_counter = 1  # Counter สำหรับ ID ของ notification

# ค่าเริ่มต้นสำหรับคำสั่ง
DEFAULT_COMMANDS = {
    'esp8266': {"pump": 0, "led": 0, "servo": 0},
    'esp32': {"d1": 0, "d2": 0, "d5": 0, "d0": 0, "d7": 0, "d8": 0}
}

# Helper to get sqlite connection
def get_db_connection():
    # check_same_thread=False to allow usage across threads (SocketIO)
    conn = sqlite3.connect(DATABASE_PATH, timeout=5, check_same_thread=False)
    return conn

# --- ระบบฐานข้อมูล ---
def init_db():
    """Initialize database"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()

            # ตารางข้อมูลเซ็นเซอร์
            c.execute('''
                CREATE TABLE IF NOT EXISTS sensor_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    node_id TEXT NOT NULL,
                    node_type TEXT,
                    temperature REAL,
                    humidity REAL,
                    soil_moisture INTEGER
                )
            ''')

            # ตารางคำสั่งควบคุม
            c.execute('''
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    node_id TEXT NOT NULL,
                    node_type TEXT,
                    command_type TEXT,
                    command_value INTEGER
                )
            ''')

            conn.commit()
        print("✅ Database initialized successfully (path: {} )".format(DATABASE_PATH))
    except Exception as e:
        print(f"❌ Database initialization error: {e}")


def save_sensor_data(node_id, node_type, temp, humi, soil):
    """บันทึกข้อมูลเซ็นเซอร์"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO sensor_data (node_id, node_type, temperature, humidity, soil_moisture)
                VALUES (?, ?, ?, ?, ?)
            ''', (node_id, node_type, temp, humi, soil))
            conn.commit()
    except Exception as e:
        print(f"❌ Error saving sensor data: {e}")


def save_command(node_id, node_type, command_type, command_value):
    """บันทึกคำสั่งควบคุม"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO commands (node_id, node_type, command_type, command_value)
                VALUES (?, ?, ?, ?)
            ''', (node_id, node_type, command_type, command_value))
            conn.commit()
    except Exception as e:
        print(f"❌ Error saving command: {e}")

# --- ระบบแจ้งเตือน ---
def add_notification(message, node_id=None, level="info"):
    """เพิ่มการแจ้งเตือน"""
    global notification_id_counter

    notification = {
        'id': notification_id_counter,
        'timestamp': datetime.now().isoformat(),
        'node_id': node_id,
        'message': message,
        'level': level,  # info, warning, error
        'read': False
    }

    notification_id_counter += 1
    notifications.insert(0, notification)

    # จำกัดจำนวน notifications
    if len(notifications) > 50:
        notifications.pop()

    # ส่งไปยัง frontend
    try:
        socketio.emit('new_notification', notification)
    except Exception:
        # ไม่ให้ server ล่มเพราะการส่ง notification
        pass

    return notification

# --- ตรวจจับประเภทโหนด ---
# (unchanged) - keep existing detect_node_type implementation
