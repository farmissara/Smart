
"""
Smart Farm Hub V1.0 - Backend Server
แก้ไขระบบตรวจจับประเภทโหนด ESP8266/ESP32
"""

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import sqlite3
from datetime import datetime
import os

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'smart-farm-secret-key-v1'

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

# --- ระบบฐานข้อมูล ---
def init_db():
    """Initialize database"""
    try:
        conn = sqlite3.connect('farm_data.db')
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
        conn.close()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")

def save_sensor_data(node_id, node_type, temp, humi, soil):
    """บันทึกข้อมูลเซ็นเซอร์"""
    try:
        conn = sqlite3.connect('farm_data.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO sensor_data (node_id, node_type, temperature, humidity, soil_moisture)
            VALUES (?, ?, ?, ?, ?)
        ''', (node_id, node_type, temp, humi, soil))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Error saving sensor data: {e}")

def save_command(node_id, node_type, command_type, command_value):
    """บันทึกคำสั่งควบคุม"""
    try:
        conn = sqlite3.connect('farm_data.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO commands (node_id, node_type, command_type, command_value)
            VALUES (?, ?, ?, ?)
        ''', (node_id, node_type, command_type, command_value))
        conn.commit()
        conn.close()
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
    socketio.emit('new_notification', notification)
    
    return notification

# --- ตรวจจับประเภทโหนด ---
def detect_node_type(node_id, data):
    """ตรวจจับว่าเป็น ESP8266 หรือ ESP32 จากข้อมูลที่ได้รับ"""
    # ถ้าโหนดนี้เคยตรวจจับประเภทแล้ว ให้ใช้ประเภทเดิม
    if node_id in node_types:
        return node_types[node_id]
    
    # ตรวจจับจากข้อมูลที่ได้รับ
    print(f"🔍 Detecting node type for {node_id}")
    print(f"   Data keys: {list(data.keys())}")
    print(f"   Data values: {data}")
    
    # ตรวจสอบจากฟิลด์ที่มี
    has_temp = 'temp' in data or 'temperature' in data
    has_humi = 'humi' in data or 'humidity' in data
    has_soil = 'soil' in data or 'valueA0' in data or 'soil_moisture' in data
    
    # ถ้ามีฟิลด์เฉพาะของ ESP8266 (จากโค้ดที่ให้มา)
    if 'valueA0' in data:
        print(f"   ✅ Detected as ESP8266 (has valueA0 field)")
        return 'esp8266'
    
    # ถ้ามีฟิลด์เฉพาะของ ESP32 (จากโค้ดที่ให้มา)
    # ESP32 ส่ง temp, humidity, valueA0 เช่นกัน
    # ต้องใช้วิธีตรวจจับอื่น
    
    # ตรวจจับจากชื่อโหนด
    node_id_lower = node_id.lower()
    if 'esp32' in node_id_lower:
        print(f"   ✅ Detected as ESP32 (name contains ESP32)")
        return 'esp32'
    elif 'esp8266' in node_id_lower or 'nodemcu' in node_id_lower:
        print(f"   ✅ Detected as ESP8266 (name contains ESP8266/NodeMCU)")
        return 'esp8266'
    
    # ถ้าตรวจพบข้อมูลเซ็นเซอร์พื้นฐาน
    if has_temp and has_humi:
        # ตรวจสอบจากข้อมูลเพิ่มเติม
        if 'device_info' in data:
            print(f"   ✅ Detected as ESP32 (has device_info)")
            return 'esp32'
        else:
            # พยายามเดาจากข้อมูลที่มี
            # ESP8266 มักส่ง valueA0, ESP32 มักส่ง soil_moisture
            if 'valueA0' in data:
                print(f"   ✅ Detected as ESP8266 (has valueA0)")
                return 'esp8266'
            elif 'soil_moisture' in data:
                print(f"   ✅ Detected as ESP32 (has soil_moisture)")
                return 'esp32'
    
    # ถ้ายังไม่รู้ ให้ถามผู้ใช้
    print(f"   ❓ Unknown node type, defaulting to ESP8266")
    return 'esp8266'  # ค่าเริ่มต้น

# --- ระบบ Automation ---
def check_automation(node_id, node_type, temp, humi, soil):
    """ตรวจสอบเงื่อนไข Automation"""
    actions = []
    
    # 1. ถ้าความชื้นดินต่ำกว่า 30% ให้เปิดปั๊มน้ำ
    if soil < 30:
        target_node = None
        target_action = None
        
        # หาโหนดที่มีปั๊มน้ำ
        for nid, ntype in node_types.items():
            if ntype == 'esp8266':
                # ESP8266 ใช้ 'pump'
                target_node = nid
                target_action = 'pump'
                break
            elif ntype == 'esp32':
                # ESP32 ใช้ 'd1' เป็นปั๊มน้ำ (ตามโค้ดตัวอย่าง)
                target_node = nid
                target_action = 'd1'
                break
        
        if target_node:
            if target_node not in node_commands:
                node_commands[target_node] = DEFAULT_COMMANDS[node_types[target_node]].copy()
            
            node_commands[target_node][target_action] = 1
            
            # บันทึก command
            save_command(target_node, node_types[target_node], target_action, 1)
            
            # แจ้งเตือน
            msg = f"ดินแห้ง ({soil}%) เปิดปั๊มน้ำอัตโนมัติ"
            add_notification(msg, node_id, "warning")
            
            actions.append({
                'rule': 'dry_soil',
                'target': target_node,
                'action': target_action,
                'value': 1
            })
    
    # 2. ถ้าความชื้นดินสูงกว่า 80% ให้ปิดปั๊มน้ำ
    elif soil > 80:
        target_node = None
        target_action = None
        
        for nid, ntype in node_types.items():
            if ntype == 'esp8266':
                target_node = nid
                target_action = 'pump'
                break
            elif ntype == 'esp32':
                target_node = nid
                target_action = 'd1'
                break
        
        if target_node:
            if target_node not in node_commands:
                node_commands[target_node] = DEFAULT_COMMANDS[node_types[target_node]].copy()
            
            node_commands[target_node][target_action] = 0
            
            # บันทึก command
            save_command(target_node, node_types[target_node], target_action, 0)
            
            # แจ้งเตือน
            msg = f"น้ำเต็ม ({soil}%) ปิดปั๊มน้ำอัตโนมัติ"
            add_notification(msg, node_id, "warning")
            
            actions.append({
                'rule': 'tank_full',
                'target': target_node,
                'action': target_action,
                'value': 0
            })
    
    # 3. ถ้าอุณหภูมิสูงกว่า 35°C ให้เปิดไฟเตือน
    if temp > 35:
        target_action = None
        
        if node_type == 'esp8266':
            target_action = 'led'
        elif node_type == 'esp32':
            target_action = 'd2'  # สมมติว่า D2 คือ LED
        
        if target_action:
            if node_id not in node_commands:
                node_commands[node_id] = DEFAULT_COMMANDS[node_type].copy()
            
            node_commands[node_id][target_action] = 1
            
            # บันทึก command
            save_command(node_id, node_type, target_action, 1)
            
            # แจ้งเตือน
            msg = f"อุณหภูมิสูง ({temp}°C) เปิดไฟเตือน"
            add_notification(msg, node_id, "warning")
            
            actions.append({
                'rule': 'high_temp',
                'target': node_id,
                'action': target_action,
                'value': 1
            })
    
    return actions

# --- API สำหรับ Dashboard ---
@app.route('/api/dashboard/stats')
def get_dashboard_stats():
    """API สำหรับดึงสถิติของ Dashboard"""
    nodes = list(node_states.values())
    
    if not nodes:
        return jsonify({
            'avg_temp': 0,
            'avg_humi': 0,
            'avg_soil': 0,
            'node_count': 0,
            'esp8266_count': 0,
            'esp32_count': 0
        })
    
    # คำนวณค่าเฉลี่ย
    total_temp = 0
    total_humi = 0
    total_soil = 0
    valid_nodes = 0
    esp8266_count = 0
    esp32_count = 0
    
    for node in nodes:
        if 'temp' in node and node['temp'] is not None:
            total_temp += node['temp']
            total_humi += node.get('humi', 0)
            total_soil += node.get('soil', 0)
            valid_nodes += 1
            
            # นับจำนวนโหนดแต่ละประเภท
            node_type = node.get('node_type', 'unknown')
            if node_type == 'esp8266':
                esp8266_count += 1
            elif node_type == 'esp32':
                esp32_count += 1
    
    if valid_nodes > 0:
        avg_temp = total_temp / valid_nodes
        avg_humi = total_humi / valid_nodes
        avg_soil = total_soil / valid_nodes
    else:
        avg_temp = avg_humi = avg_soil = 0
    
    return jsonify({
        'avg_temp': round(avg_temp, 1),
        'avg_humi': round(avg_humi, 1),
        'avg_soil': round(avg_soil, 1),
        'node_count': len(nodes),
        'esp8266_count': esp8266_count,
        'esp32_count': esp32_count
    })

# --- Routes ---
@app.route('/')
def index():
    """หน้า Dashboard หลัก"""
    return render_template('index.html')

@app.route('/api/status')
def api_status():
    """API สำหรับตรวจสอบสถานะระบบ"""
    return jsonify({
        'status': 'online',
        'timestamp': datetime.now().isoformat(),
        'nodes': list(node_states.keys()),
        'node_types': node_types,
        'node_count': len(node_states)
    })

@app.route('/api/nodes')
def get_nodes():
    """API สำหรับดึงข้อมูลโหนดทั้งหมด"""
    # เพิ่มข้อมูล node_type ลงใน response
    nodes_with_type = {}
    for node_id, data in node_states.items():
        nodes_with_type[node_id] = {
            **data,
            'node_type': node_types.get(node_id, 'unknown'),
            'commands': node_commands.get(node_id, {})
        }
    
    return jsonify({
        'nodes': nodes_with_type,
        'commands': node_commands,
        'node_types': node_types,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/node/<node_id>/set_type', methods=['POST'])
def set_node_type(node_id):
    """API สำหรับตั้งค่าประเภทโหนดด้วยตนเอง"""
    try:
        data = request.json
        new_type = data.get('node_type')
        
        if new_type not in ['esp8266', 'esp32']:
            return jsonify({'error': 'Invalid node type'}), 400
        
        # อัปเดทประเภทโหนด
        node_types[node_id] = new_type
        
        # ตรวจสอบว่าโหนดมีคำสั่งเริ่มต้นหรือไม่
        if node_id not in node_commands:
            node_commands[node_id] = DEFAULT_COMMANDS[new_type].copy()
        
        print(f"✅ Manually set node type: {node_id} -> {new_type}")
        
        # ส่งอัปเดทไปยัง frontend
        socketio.emit('node_type_updated', {
            'node_id': node_id,
            'node_type': new_type,
            'timestamp': datetime.now().isoformat()
        })
        
        return jsonify({
            'status': 'success',
            'message': f'Node type set to {new_type}',
            'node_id': node_id,
            'node_type': new_type
        })
        
    except Exception as e:
        print(f"❌ Error setting node type: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/notifications')
def get_notifications():
    """API สำหรับดึงการแจ้งเตือน"""
    return jsonify({
        'notifications': notifications,
        'unread_count': sum(1 for n in notifications if not n['read'])
    })

@app.route('/api/notifications/read/<int:notification_id>', methods=['POST'])
def mark_notification_read(notification_id):
    """ทำเครื่องหมายการแจ้งเตือนว่าอ่านแล้ว"""
    for notification in notifications:
        if notification['id'] == notification_id:
            notification['read'] = True
            break
    return jsonify({'status': 'success'})

@app.route('/api/notifications/clear', methods=['POST'])
def clear_notifications():
    """ล้างการแจ้งเตือนทั้งหมด"""
    notifications.clear()
    return jsonify({'status': 'success'})

# --- Endpoint สำหรับ Node ESP8266/ESP32 ---
@app.route('/node/report', methods=['POST'])
def node_report():
    """Endpoint สำหรับ Node ESP8266/ESP32 ส่งข้อมูลเซ็นเซอร์"""
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
        
        # ดึงข้อมูลจาก Node
        node_id = data.get('node_id', 'unknown')
        
        # ตรวจจับประเภทโหนด
        node_type = detect_node_type(node_id, data)
        node_types[node_id] = node_type
        
        print(f"📡 Node Report: {node_id} ({node_type})")
        
        # ดึงข้อมูลเซ็นเซอร์ (รองรับหลายชื่อฟิลด์)
        temp = float(data.get('temp', data.get('temperature', 0)))
        humi = float(data.get('humi', data.get('humidity', 0)))
        
        # ดึงข้อมูลความชื้นดิน (รองรับหลายชื่อฟิลด์)
        soil = 0
        if 'valueA0' in data:
            soil = int(data.get('valueA0', 0))
        elif 'soil' in data:
            soil = int(data.get('soil', 0))
        elif 'soil_moisture' in data:
            soil = int(data.get('soil_moisture', 0))
        else:
            soil = 50  # ค่าเริ่มต้น
        
        print(f"   🌡️ Temperature: {temp}°C")
        print(f"   💧 Humidity: {humi}%")
        print(f"   🌱 Soil Moisture: {soil}%")
        
        # 1. อัปเดทสถานะปัจจุบัน
        node_states[node_id] = {
            'temp': temp,
            'humi': humi,
            'soil': soil,
            'node_type': node_type,
            'last_update': datetime.now().isoformat()
        }
        
        # 2. บันทึกลงฐานข้อมูล
        save_sensor_data(node_id, node_type, temp, humi, soil)
        
        # 3. ตรวจสอบ Automation
        automation_actions = check_automation(node_id, node_type, temp, humi, soil)
        
        # 4. ส่งข้อมูลไปยัง frontend ผ่าน WebSocket
        socketio.emit('sensor_update', {
            'node_id': node_id,
            'node_type': node_type,
            'data': {
                'temp': temp,
                'humi': humi,
                'soil': soil
            },
            'timestamp': datetime.now().isoformat(),
            'automation': automation_actions
        })
        
        # 5. ส่งข้อมูลสถิติ dashboard ใหม่
        nodes = list(node_states.values())
        if nodes:
            # กรองเฉพาะโหนดที่มีข้อมูล
            valid_nodes = [n for n in nodes if 'temp' in n and n['temp'] is not None]
            if valid_nodes:
                avg_temp = sum(node.get('temp', 0) for node in valid_nodes) / len(valid_nodes)
                avg_humi = sum(node.get('humi', 0) for node in valid_nodes) / len(valid_nodes)
                avg_soil = sum(node.get('soil', 0) for node in valid_nodes) / len(valid_nodes)
                
                # นับจำนวนโหนดแต่ละประเภท
                esp8266_count = sum(1 for n in nodes if n.get('node_type') == 'esp8266')
                esp32_count = sum(1 for n in nodes if n.get('node_type') == 'esp32')
                
                socketio.emit('dashboard_stats', {
                    'avg_temp': round(avg_temp, 1),
                    'avg_humi': round(avg_humi, 1),
                    'avg_soil': round(avg_soil, 1),
                    'node_count': len(nodes),
                    'esp8266_count': esp8266_count,
                    'esp32_count': esp32_count
                })
        
        # 6. ส่งคำสั่งกลับไปที่ Node (ตามประเภท)
        command = node_commands.get(node_id, DEFAULT_COMMANDS[node_type].copy())
        
        if node_type == 'esp8266':
            response_data = {
                "status": "success",
                "message": "Data received",
                "pump": command.get('pump', 0),
                "led": command.get('led', 0),
                "servo": command.get('servo', 0)
            }
        elif node_type == 'esp32':
            response_data = {
                "status": "success",
                "message": "Data received",
                "d1": command.get('d1', 0),
                "d2": command.get('d2', 0),
                "d5": command.get('d5', 0),
                "d0": command.get('d0', 0),
                "d7": command.get('d7', 0),
                "d8": command.get('d8', 0)
            }
        else:
            response_data = {
                "status": "success",
                "message": "Data received"
            }
        
        print(f"   📤 Response to node: {response_data}")
        return jsonify(response_data), 200
        
    except Exception as e:
        print(f"❌ Error in node_report: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

# --- WebSocket Handlers ---
@socketio.on('connect')
def handle_connect():
    """เมื่อ Client เชื่อมต่อเข้ามา"""
    print(f"🔗 Client connected: {request.sid}")
    emit('connected', {
        'message': 'Connected to Smart Farm Hub Universal',
        'timestamp': datetime.now().isoformat(),
        'supports': ['esp8266', 'esp32']
    })
    
    # ส่งข้อมูลล่าสุดเมื่อ client เชื่อมต่อ
    nodes = list(node_states.values())
    if nodes:
        valid_nodes = [n for n in nodes if 'temp' in n and n['temp'] is not None]
        if valid_nodes:
            avg_temp = sum(node.get('temp', 0) for node in valid_nodes) / len(valid_nodes)
            avg_humi = sum(node.get('humi', 0) for node in valid_nodes) / len(valid_nodes)
            avg_soil = sum(node.get('soil', 0) for node in valid_nodes) / len(valid_nodes)
            
            esp8266_count = sum(1 for n in nodes if n.get('node_type') == 'esp8266')
            esp32_count = sum(1 for n in nodes if n.get('node_type') == 'esp32')
            
            emit('dashboard_stats', {
                'avg_temp': round(avg_temp, 1),
                'avg_humi': round(avg_humi, 1),
                'avg_soil': round(avg_soil, 1),
                'node_count': len(nodes),
                'esp8266_count': esp8266_count,
                'esp32_count': esp32_count
            })

@socketio.on('disconnect')
def handle_disconnect():
    """เมื่อ Client ตัดการเชื่อมต่อ"""
    print(f"🔌 Client disconnected: {request.sid}")

@socketio.on('control_device')
def handle_control(data):
    """รับคำสั่งควบคุมจาก Frontend"""
    try:
        node_id = data.get('node_id')
        action = data.get('action')
        value = data.get('value')
        
        if not node_id or not action:
            emit('error', {'message': 'Invalid parameters'})
            return
        
        # ดึงประเภทโหนด
        node_type = node_types.get(node_id, 'unknown')
        
        if node_type == 'unknown':
            emit('error', {'message': f'Unknown node type for {node_id}. Please set node type first.'})
            return
        
        # Validate value
        if 'servo' in action.lower() or action == 'd0':
            value = max(0, min(180, int(value)))  # Servo 0-180 องศา
        else:
            value = 1 if int(value) > 0 else 0  # 1 หรือ 0
        
        # Initialize command dict if not exists
        if node_id not in node_commands:
            node_commands[node_id] = DEFAULT_COMMANDS[node_type].copy()
        
        # Update command
        old_value = node_commands[node_id].get(action, 0)
        node_commands[node_id][action] = value
        
        # บันทึกคำสั่ง
        save_command(node_id, node_type, action, value)
        
        print(f"🎮 Control Command from Web: {node_id} ({node_type}).{action} = {value}")
        
        # Broadcast คำสั่งไปยัง frontend อื่นๆ
        emit('command_update', {
            'node_id': node_id,
            'node_type': node_type,
            'action': action,
            'value': value,
            'old_value': old_value,
            'source': 'web',
            'timestamp': datetime.now().isoformat()
        }, broadcast=True)
        
        # ส่งการแจ้งเตือน
        device_names = {
            'pump': 'ปั๊มน้ำ', 'led': 'ไฟ LED', 'servo': 'เซอร์โววาล์ว',
            'd1': 'ปั๊มน้ำ (D1)', 'd2': 'ไฟ LED (D2)', 'd5': 'พัดลม (D5)',
            'd0': 'เซอร์โว (D0)', 'd7': 'สเปรย์น้ำ (D7)', 'd8': 'ไฟส่องสว่าง (D8)'
        }
        
        if 'servo' in action.lower() or action == 'd0':
            message = f"ปรับ {device_names.get(action, action)} เป็น {value}°"
        else:
            status = 'เปิด' if value else 'ปิด'
            message = f"{status} {device_names.get(action, action)}"
        
        add_notification(f"🎮 {message}", node_id, "info")
        
    except Exception as e:
        print(f"❌ Error in handle_control: {e}")
        emit('error', {'message': 'Internal server error'})

# --- Application Startup ---
if __name__ == '__main__':
    # Initialize database
    init_db()
    
    print("\n" + "="*60)
    print("🚀 SMART FARM HUB UNIVERSAL - FIXED NODE DETECTION")
    print("="*60)
    print(f"📡 WebSocket Server: ws://0.0.0.0:5000")
    print(f"🌐 HTTP Server:      http://localhost:5000")
    print(f"📊 Dashboard:        http://localhost:5000")
    print(f"📡 Node API:         POST http://localhost:5000/node/report")
    print("="*60)
    print("\n📋 Node Detection Rules:")
    print("   • ถ้ามีฟิลด์ 'valueA0' → ESP8266")
    print("   • ถ้ามีฟิลด์ 'device_info' → ESP32")
    print("   • ถ้าชื่อโหนดมี 'esp32' → ESP32")
    print("   • ถ้าชื่อโหนดมี 'esp8266' หรือ 'nodemcu' → ESP8266")
    print("   • ค่าเริ่มต้น: ESP8266")
    print("="*60)
    print("\nPress Ctrl+C to stop the server\n")
    
    try:
        socketio.run(
            app,
            host='0.0.0.0',
            port=5000,
            debug=False,
            allow_unsafe_werkzeug=True
        )
    except KeyboardInterrupt:
        print("\n👋 Shutting down Smart Farm Hub...")
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
