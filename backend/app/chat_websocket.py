"""
WebSocket manager for real-time chat functionality
"""
import socketio
from typing import Dict, Set, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Create Socket.IO server with ASGI support
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    logger=True,
    engineio_logger=True
)

# Track active connections: {user_id: set(sid)}
active_connections: Dict[int, Set[str]] = {}

# Track user presence: {user_id: {'status': 'online'|'away', 'last_seen': datetime}}
user_presence: Dict[int, Dict] = {}

# Track typing indicators: {channel_id: {user_id: sid}}
typing_indicators: Dict[int, Dict[int, str]] = {}


class ChatWebSocketManager:
    """Manages WebSocket connections for chat functionality"""
    
    @staticmethod
    async def broadcast_to_channel(channel_id, event: str, data: dict):
        """Broadcast message to all users in a channel (supports int or string channel_id)"""
        room_name = f'channel_{str(channel_id)}'
        await sio.emit(event, data, room=room_name)
        logger.info(f"Broadcasted {event} to {room_name}")
    
    @staticmethod
    async def broadcast_to_user(user_id, event: str, data: dict):
        """Send message to specific user (all their connections)"""
        try:
            uid_int = int(user_id)
        except (ValueError, TypeError):
            uid_int = None

        # Emit to named user room (string and int variations)
        await sio.emit(event, data, room=f'user_{user_id}')
        if uid_int is not None and str(uid_int) != str(user_id):
            await sio.emit(event, data, room=f'user_{uid_int}')

        # Also emit directly to individual connection SIDs if found in active_connections
        sids_to_send = set()
        if user_id in active_connections:
            sids_to_send.update(active_connections[user_id])
        if uid_int is not None and uid_int in active_connections:
            sids_to_send.update(active_connections[uid_int])
        
        for sid in sids_to_send:
            try:
                await sio.emit(event, data, room=sid)
            except Exception as e:
                logger.warning(f"Failed to emit {event} to sid {sid}: {e}")
        logger.info(f"Sent {event} to user {user_id} (sids: {len(sids_to_send)})")
    
    @staticmethod
    async def broadcast_all(event: str, data: dict):
        """Broadcast message to all connected users"""
        await sio.emit(event, data)
        logger.info(f"Broadcasted {event} to all connected clients")

    @staticmethod
    async def broadcast_to_dm(user1_id, user2_id, event: str, data: dict):
        """Broadcast message to both users in a DM conversation"""
        await ChatWebSocketManager.broadcast_to_user(user1_id, event, data)
        await ChatWebSocketManager.broadcast_to_user(user2_id, event, data)
    
    @staticmethod
    def get_online_users() -> list:
        """Get list of currently online user IDs"""
        return list(active_connections.keys())
    
    @staticmethod
    def is_user_online(user_id) -> bool:
        """Check if user is currently online"""
        try:
            uid_int = int(user_id)
        except (ValueError, TypeError):
            uid_int = None
        if user_id in active_connections and len(active_connections[user_id]) > 0:
            return True
        if uid_int is not None and uid_int in active_connections and len(active_connections[uid_int]) > 0:
            return True
        return False


@sio.event
async def connect(sid, environ, auth=None):
    """Handle client connection"""
    logger.info(f"Client connected: {sid}, auth: {auth}")
    
    # Extract user info from auth token if present
    user_id = auth.get('user_id') if isinstance(auth, dict) else None
    
    if user_id is not None:
        try:
            uid_int = int(user_id)
        except Exception:
            uid_int = user_id
        
        for key in (uid_int, str(user_id)):
            if key not in active_connections:
                active_connections[key] = set()
            active_connections[key].add(sid)
        
        await sio.enter_room(sid, f'user_{user_id}')
        if uid_int != user_id:
            await sio.enter_room(sid, f'user_{uid_int}')
        
        user_presence[uid_int] = {
            'status': 'online',
            'last_seen': datetime.utcnow()
        }
        
        async with sio.session(sid) as session:
            session['user_id'] = uid_int
        
        await sio.emit('user_status', {
            'user_id': uid_int,
            'status': 'online',
            'timestamp': datetime.utcnow().isoformat()
        }, skip_sid=sid)
        logger.info(f"User {uid_int} connected with sid {sid}")
    
    return True


@sio.event
async def authenticate(sid, data):
    """Authenticate socket session after connecting"""
    user_id = data.get('user_id') if isinstance(data, dict) else data
    if user_id is not None:
        try:
            uid_int = int(user_id)
        except Exception:
            uid_int = user_id
        
        for key in (uid_int, str(user_id)):
            if key not in active_connections:
                active_connections[key] = set()
            active_connections[key].add(sid)
            
        await sio.enter_room(sid, f'user_{user_id}')
        if uid_int != user_id:
            await sio.enter_room(sid, f'user_{uid_int}')
            
        user_presence[uid_int] = {
            'status': 'online',
            'last_seen': datetime.utcnow()
        }
        async with sio.session(sid) as session:
            session['user_id'] = uid_int
        logger.info(f"User {uid_int} authenticated on sid {sid}")
        await sio.emit('authenticated', {'user_id': uid_int}, room=sid)



@sio.event
async def disconnect(sid):
    """Handle client disconnection"""
    async with sio.session(sid) as session:
        user_id = session.get('user_id')
    
    if user_id is not None:
        try:
            uid_int = int(user_id)
        except Exception:
            uid_int = user_id

        for key in (uid_int, str(user_id)):
            if key in active_connections:
                active_connections[key].discard(sid)
                if not active_connections[key]:
                    del active_connections[key]
        
        # If no more connections for this user
        is_still_online = (
            (uid_int in active_connections and len(active_connections[uid_int]) > 0) or
            (str(user_id) in active_connections and len(active_connections[str(user_id)]) > 0)
        )
        if not is_still_online:
            # Update presence
            user_presence[uid_int] = {
                'status': 'offline',
                'last_seen': datetime.utcnow()
            }
            
            # Notify others that user is offline
            await sio.emit('user_status', {
                'user_id': uid_int,
                'status': 'offline',
                'timestamp': datetime.utcnow().isoformat()
            })
    
    logger.info(f"Client disconnected: {sid}")


@sio.event
async def join_channel(sid, data):
    """Join a channel room"""
    channel_id = data.get('channel_id') if isinstance(data, dict) else data
    if channel_id:
        room_name = f'channel_{str(channel_id)}'
        await sio.enter_room(sid, room_name)
        
        async with sio.session(sid) as session:
            user_id = session.get('user_id')
        
        logger.info(f"User {user_id} joined {room_name}")
        
        # Notify channel members
        await sio.emit('user_joined_channel', {
            'user_id': user_id,
            'channel_id': str(channel_id),
            'timestamp': datetime.utcnow().isoformat()
        }, room=room_name, skip_sid=sid)


@sio.event
async def leave_channel(sid, data):
    """Leave a channel room"""
    channel_id = data.get('channel_id') if isinstance(data, dict) else data
    if channel_id:
        async with sio.session(sid) as session:
            user_id = session.get('user_id')
        
        room_name = f'channel_{str(channel_id)}'
        await sio.leave_room(sid, room_name)
        logger.info(f"User {user_id} left {room_name}")
        
        # Notify channel members
        await sio.emit('user_left_channel', {
            'user_id': user_id,
            'channel_id': str(channel_id),
            'timestamp': datetime.utcnow().isoformat()
        }, room=room_name)


@sio.event
async def typing_start(sid, data):
    """User started typing"""
    channel_id = data.get('channel_id')
    cid_str = str(channel_id) if channel_id else None
    
    async with sio.session(sid) as session:
        user_id = session.get('user_id')
    
    if cid_str and user_id:
        if cid_str not in typing_indicators:
            typing_indicators[cid_str] = {}
        typing_indicators[cid_str][user_id] = sid
        
        # Broadcast to channel
        await sio.emit('user_typing', {
            'user_id': user_id,
            'channel_id': cid_str,
            'is_typing': True
        }, room=f'channel_{cid_str}', skip_sid=sid)


@sio.event
async def typing_stop(sid, data):
    """User stopped typing"""
    channel_id = data.get('channel_id')
    cid_str = str(channel_id) if channel_id else None
    
    async with sio.session(sid) as session:
        user_id = session.get('user_id')
    
    if cid_str and user_id:
        if cid_str in typing_indicators and user_id in typing_indicators[cid_str]:
            del typing_indicators[cid_str][user_id]
        
        # Broadcast to channel
        await sio.emit('user_typing', {
            'user_id': user_id,
            'channel_id': cid_str,
            'is_typing': False
        }, room=f'channel_{cid_str}', skip_sid=sid)


@sio.event
async def message_read(sid, data):
    """Mark message as read"""
    message_id = data.get('message_id')
    channel_id = data.get('channel_id')
    
    async with sio.session(sid) as session:
        user_id = session.get('user_id')
    
    if message_id and channel_id and user_id:
        # Broadcast read receipt
        await sio.emit('message_read_receipt', {
            'message_id': message_id,
            'channel_id': channel_id,
            'user_id': user_id,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'channel_{channel_id}', skip_sid=sid)


@sio.event
async def update_status(sid, data):
    """Update user status (online, away, do not disturb)"""
    status = data.get('status')  # online, away, dnd
    
    async with sio.session(sid) as session:
        user_id = session.get('user_id')
    
    if user_id and status:
        user_presence[user_id] = {
            'status': status,
            'last_seen': datetime.utcnow()
        }
        
        # Broadcast status change
        await sio.emit('user_status', {
            'user_id': user_id,
            'status': status,
            'timestamp': datetime.utcnow().isoformat()
        }, skip_sid=sid)


# Export the manager instance
ws_manager = ChatWebSocketManager()
