from typing import List, Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.auth_service import auth_service
from common.databases.models.user import User
import logging
import json

router = APIRouter()
logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Map user_id to List[WebSocket] (user might have multiple tabs)
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"User {user_id} connected via WebSocket")

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"User {user_id} disconnected")

    async def send_personal_message(self, message: str, user_id: int):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_text(message)
                except Exception as e:
                    logger.error(f"Error sending message to {user_id}: {e}")

    async def broadcast(self, message: str):
        for user_cons in self.active_connections.values():
            for connection in user_cons:
                await connection.send_text(message)

manager = ConnectionManager()

# --- Redis Pub/Sub Logic ---
import redis.asyncio as aioredis
from config import settings

async def start_redis_listener(manager: ConnectionManager):
    """
    Listens to Redis channel 'job_messages' and forwards to local WebSocket users.
    """
    logger.info("Starting Redis Subscriber for WebSockets...")
    redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe("job_messages")
    
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    user_id = data.get("user_id")
                    msg_content = data.get("message") # Expecting stringified JSON or dict
                    
                    if user_id:
                        # Forward to specific user
                        # msg_content should be string to send over WS
                        if isinstance(msg_content, (dict, list)):
                            msg_content = json.dumps(msg_content)
                        await manager.send_personal_message(msg_content, int(user_id))
                    else:
                        # Broadcast?
                        pass
                except Exception as e:
                    logger.error(f"Redis message processing error: {e}")
    except Exception as e:
        logger.error(f"Redis Listener crashed: {e}")
    finally:
        await redis.close()


@router.websocket("/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """
    WebSocket endpoint.
    Path param 'token' used for auth since headers are tricky in JS WebSocket API (standard).
    """
    try:
        # Get user from token using auth_service
        user = await auth_service.get_user_from_token_str(token)
        if not user:
             await websocket.close(code=4003)
             return
             
        await manager.connect(websocket, user.id)
        
        try:
            while True:
                # Keep alive / Listen for client messages
                data = await websocket.receive_text()
                # Here we could handle client acknowledgements or other ops
        except WebSocketDisconnect:
            manager.disconnect(websocket, user.id)
            
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        try:
            await websocket.close()
        except:
            pass
