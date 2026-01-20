import eventlet
eventlet.monkey_patch()

from flask import Flask, request
from flask_socketio import SocketIO, join_room, emit, disconnect

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=10, ping_interval=5)

devices = {}

@app.route('/')
def index():
    return "Tether Server Running", 200

@socketio.on('join_dashboard')
def on_join_dashboard(data):
    room_key = data['key']
    join_room(room_key)
    if room_key not in devices: devices[room_key] = {}
    emit('update_device_list', list(devices[room_key].values()))

@socketio.on('register_tether')
def on_register_tether(data):
    room_key = data['key']
    join_room(room_key)
    if room_key not in devices: devices[room_key] = {}
    
    devices[room_key][request.sid] = {
        'sid': request.sid,
        'name': data['name'],
        'nickname': '',
        'status': 'online',
        'crash_on': False # Default state
    }
    emit('update_device_list', list(devices[room_key].values()), to=room_key)

@socketio.on('disconnect')
def handle_disconnect():
    for room_key, room_devices in devices.items():
        if request.sid in room_devices:
            room_devices[request.sid]['status'] = 'offline'
            emit('update_device_list', list(room_devices.values()), to=room_key)
            break

@socketio.on('update_nickname')
def on_update_nickname(data):
    room_key, target_sid = data['key'], data['sid']
    if room_key in devices and target_sid in devices[room_key]:
        devices[room_key][target_sid]['nickname'] = data['nickname']
        emit('update_device_list', list(devices[room_key].values()), to=room_key)

@socketio.on('delete_session')
def on_delete_session(data):
    room_key, target_sid = data['key'], data['sid']
    if room_key in devices and target_sid in devices[room_key]:
        del devices[room_key][target_sid]
        disconnect(target_sid)
        emit('update_device_list', list(devices[room_key].values()), to=room_key)

# NEW: Handle Crash Toggle
@socketio.on('toggle_crash')
def on_toggle_crash(data):
    room_key, target_sid = data['key'], data['sid']
    if room_key in devices and target_sid in devices[room_key]:
        # Toggle state
        new_state = not devices[room_key][target_sid]['crash_on']
        devices[room_key][target_sid]['crash_on'] = new_state
        
        # Notify Dashboard to update UI
        emit('update_device_list', list(devices[room_key].values()), to=room_key)
        
        # Notify the specific Tether to start/stop crash logic
        emit('crash_command', {'active': new_state}, room=target_sid)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
