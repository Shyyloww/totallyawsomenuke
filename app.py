# 1. MONKEY PATCH MUST BE FIRST
import eventlet
eventlet.monkey_patch()

from flask import Flask, request
from flask_socketio import SocketIO, join_room, emit, disconnect

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

# 2. Add ping_timeout/interval to keep connections alive on public networks
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=10, ping_interval=5)

# Store state in memory
devices = {}

# 3. Add a basic index route so Render knows the app is running (Fixes 404 on health checks)
@app.route('/')
def index():
    return "Tether Server is Running!", 200

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    for room_key, room_devices in devices.items():
        if request.sid in room_devices:
            room_devices[request.sid]['status'] = 'offline'
            print(f"Device {request.sid} went offline in room {room_key}")
            emit('update_device_list', list(room_devices.values()), to=room_key)
            break

@socketio.on('join_dashboard')
def on_join_dashboard(data):
    room_key = data['key']
    join_room(room_key)
    if room_key not in devices:
        devices[room_key] = {}
    emit('update_device_list', list(devices[room_key].values()))

@socketio.on('register_tether')
def on_register_tether(data):
    room_key = data['key']
    device_name = data['name']
    join_room(room_key)
    if room_key not in devices:
        devices[room_key] = {}
    devices[room_key][request.sid] = {
        'sid': request.sid,
        'name': device_name,
        'nickname': '',
        'status': 'online'
    }
    emit('update_device_list', list(devices[room_key].values()), to=room_key)

@socketio.on('update_nickname')
def on_update_nickname(data):
    room_key = data['key']
    target_sid = data['sid']
    new_nick = data['nickname']
    if room_key in devices and target_sid in devices[room_key]:
        devices[room_key][target_sid]['nickname'] = new_nick
        emit('update_device_list', list(devices[room_key].values()), to=room_key)

@socketio.on('delete_session')
def on_delete_session(data):
    room_key = data['key']
    target_sid = data['sid']
    if room_key in devices and target_sid in devices[room_key]:
        del devices[room_key][target_sid]
        disconnect(target_sid)
        emit('update_device_list', list(devices[room_key].values()), to=room_key)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
