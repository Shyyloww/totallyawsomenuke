from flask import Flask, request
from flask_socketio import SocketIO, join_room, emit, disconnect

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
# allow_unsafe_werkzeug is needed for some environments, cors_allowed_origins allows connections from anywhere
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Store state in memory: { "room_key": { "sid": { data } } }
# In a production app, use a database (Redis/Postgres)
devices = {}

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    # Find which room/user this SID belonged to
    for room_key, room_devices in devices.items():
        if request.sid in room_devices:
            # Mark as offline
            room_devices[request.sid]['status'] = 'offline'
            print(f"Device {request.sid} went offline in room {room_key}")
            
            # Notify the Dashboard in this room
            emit('update_device_list', list(room_devices.values()), to=room_key)
            break

@socketio.on('join_dashboard')
def on_join_dashboard(data):
    """Dashboard joins a specific room key"""
    room_key = data['key']
    join_room(room_key)
    
    # Initialize storage for this key if not exists
    if room_key not in devices:
        devices[room_key] = {}
        
    # Send current list of devices to the dashboard immediately
    emit('update_device_list', list(devices[room_key].values()))

@socketio.on('register_tether')
def on_register_tether(data):
    """Tether connects and registers itself"""
    room_key = data['key']
    device_name = data['name']
    
    join_room(room_key)
    
    if room_key not in devices:
        devices[room_key] = {}

    # Store device info
    devices[room_key][request.sid] = {
        'sid': request.sid,
        'name': device_name,
        'nickname': '',
        'status': 'online'
    }
    
    # Notify dashboard
    emit('update_device_list', list(devices[room_key].values()), to=room_key)

@socketio.on('update_nickname')
def on_update_nickname(data):
    """Dashboard updates a nickname"""
    room_key = data['key']
    target_sid = data['sid']
    new_nick = data['nickname']
    
    if room_key in devices and target_sid in devices[room_key]:
        devices[room_key][target_sid]['nickname'] = new_nick
        # Broadcast update back so UI confirms it
        emit('update_device_list', list(devices[room_key].values()), to=room_key)

@socketio.on('delete_session')
def on_delete_session(data):
    """Dashboard deletes a session"""
    room_key = data['key']
    target_sid = data['sid']
    
    if room_key in devices and target_sid in devices[room_key]:
        # Remove from memory
        del devices[room_key][target_sid]
        
        # Force disconnect that specific tether client
        disconnect(target_sid)
        
        # Update dashboard
        emit('update_device_list', list(devices[room_key].values()), to=room_key)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
