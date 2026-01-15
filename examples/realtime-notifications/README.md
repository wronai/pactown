# Real-time Notifications Service

WebSocket + SSE push notifications - alternatywa dla Cloudflare Durable Objects.

## Architektura

```
┌─────────────────────────────────────────────────────────────┐
│                    Pactown Notifications                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  Connection Manager                   │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │   │
│  │  │  WebSocket  │  │    SSE      │  │  Long Poll  │   │   │
│  │  │  Handler    │  │  Handler    │  │  Handler    │   │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘   │   │
│  │         └────────────────┼────────────────┘          │   │
│  │                          ▼                           │   │
│  │  ┌──────────────────────────────────────────────┐    │   │
│  │  │              Pub/Sub Engine                   │    │   │
│  │  │  channels: orders.*, users.{id}, broadcast   │    │   │
│  │  └──────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Funkcje

- **WebSocket connections** - Persistent bidirectional
- **Server-Sent Events** - One-way push notifications
- **Pub/Sub channels** - Topic-based subscriptions z wildcards
- **Presence tracking** - Online/offline status
- **Message buffer** - Historia wiadomości per channel

## Deploy

```bash
pactown quadlet deploy ./README.md \
    --domain yourdomain.com \
    --subdomain notify \
    --tenant notifications \
    --tls
```

## API

### WebSocket Connection

```javascript
const ws = new WebSocket('wss://notify.yourdomain.com/ws?token=xxx');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Received:', data);
};

// Subscribe to channels
ws.send(JSON.stringify({
  action: 'subscribe',
  channels: ['orders.*', 'user.123']
}));
```

### Server-Sent Events

```javascript
const source = new EventSource('https://notify.yourdomain.com/sse?token=xxx&channels=orders');

source.onmessage = (event) => {
  console.log('Notification:', JSON.parse(event.data));
};
```

### REST API - Send Notification

```bash
POST /api/notify
{
  "channel": "orders.new",
  "event": "order_created",
  "data": {"order_id": 123, "total": 99.99},
  "tenant_id": "shop-001"
}
```

## Porównanie z Cloudflare

| Aspekt | Pactown Notify | CF Durable Objects |
|--------|----------------|-------------------|
| WebSocket | Full support | Limited |
| Connections | 10k+ per node | 32k global |
| State | In-memory/Redis | Built-in |
| Latency | ~20ms (EU) | ~5ms (edge) |
| Cost | €5/mc VPS | $0.15/M requests |
| Self-hosted | ✓ | ✗ |

## Kod źródłowy

```python main.py
"""Real-time Notifications Service - Pactown Worker.

WebSocket + SSE push notifications with pub/sub channels.
Alternative to Cloudflare Durable Objects.
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional, Set
from collections import defaultdict
import fnmatch

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import jwt

# Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")
MAX_CONNECTIONS_PER_TENANT = int(os.getenv("MAX_CONNECTIONS_PER_TENANT", "1000"))
MESSAGE_BUFFER_SIZE = int(os.getenv("MESSAGE_BUFFER_SIZE", "100"))
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Pactown Real-time Notifications", version="1.0.0")


class NotificationMessage(BaseModel):
    channel: str
    event: str
    data: dict
    tenant_id: str = "default"
    timestamp: Optional[str] = None


class ConnectionInfo:
    def __init__(self, websocket: WebSocket, tenant_id: str, user_id: Optional[str] = None):
        self.websocket = websocket
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.channels: Set[str] = set()
        self.connected_at = datetime.utcnow()


class ConnectionManager:
    def __init__(self):
        self.ws_connections: dict[str, list[ConnectionInfo]] = defaultdict(list)
        self.sse_connections: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self.channel_subs: dict[str, Set[int]] = defaultdict(set)
        self.message_buffer: dict[str, list[dict]] = defaultdict(list)
        self.stats = {"total_connections": 0, "total_messages": 0, "ws_connections": 0, "sse_connections": 0}
    
    async def connect_ws(self, websocket: WebSocket, tenant_id: str, user_id: Optional[str] = None) -> ConnectionInfo:
        if len(self.ws_connections[tenant_id]) >= MAX_CONNECTIONS_PER_TENANT:
            await websocket.close(code=4029, reason="Connection limit exceeded")
            raise HTTPException(status_code=429, detail="Too many connections")
        await websocket.accept()
        conn = ConnectionInfo(websocket, tenant_id, user_id)
        self.ws_connections[tenant_id].append(conn)
        self.stats["ws_connections"] += 1
        self.stats["total_connections"] += 1
        logger.info(f"WebSocket connected: tenant={tenant_id}, user={user_id}")
        return conn
    
    def disconnect_ws(self, conn: ConnectionInfo):
        if conn in self.ws_connections[conn.tenant_id]:
            self.ws_connections[conn.tenant_id].remove(conn)
            self.stats["ws_connections"] -= 1
        conn_id = id(conn)
        for channel in list(conn.channels):
            self.channel_subs[channel].discard(conn_id)
        logger.info(f"WebSocket disconnected: tenant={conn.tenant_id}")
    
    def subscribe(self, conn: ConnectionInfo, channels: list[str]):
        conn_id = id(conn)
        for channel in channels:
            conn.channels.add(channel)
            self.channel_subs[channel].add(conn_id)
    
    def unsubscribe(self, conn: ConnectionInfo, channels: list[str]):
        conn_id = id(conn)
        for channel in channels:
            conn.channels.discard(channel)
            self.channel_subs[channel].discard(conn_id)
    
    def matches_channel(self, pattern: str, channel: str) -> bool:
        return fnmatch.fnmatch(channel, pattern)
    
    async def broadcast(self, message: NotificationMessage):
        self.stats["total_messages"] += 1
        self.message_buffer[message.channel].append(message.dict())
        if len(self.message_buffer[message.channel]) > MESSAGE_BUFFER_SIZE:
            self.message_buffer[message.channel].pop(0)
        
        msg_json = json.dumps({
            "channel": message.channel, "event": message.event,
            "data": message.data, "timestamp": message.timestamp or datetime.utcnow().isoformat(),
        })
        
        for conn in self.ws_connections.get(message.tenant_id, []):
            for pattern in conn.channels:
                if self.matches_channel(pattern, message.channel):
                    try:
                        await conn.websocket.send_text(msg_json)
                    except Exception as e:
                        logger.error(f"Failed to send WS message: {e}")
                    break
        
        for queue in self.sse_connections.get(message.tenant_id, []):
            try:
                await queue.put(msg_json)
            except:
                pass
    
    def get_presence(self, tenant_id: str) -> dict:
        users = set()
        for conn in self.ws_connections.get(tenant_id, []):
            if conn.user_id:
                users.add(conn.user_id)
        return {"online_users": list(users), "total_connections": len(self.ws_connections.get(tenant_id, []))}


manager = ConnectionManager()


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/health")
async def health():
    return {"status": "healthy", "stats": manager.stats}


@app.get("/stats")
async def get_stats():
    return {**manager.stats, "tenants": len(manager.ws_connections), "channels": len(manager.channel_subs)}


@app.get("/presence/{tenant_id}")
async def get_presence(tenant_id: str):
    return manager.get_presence(tenant_id)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    try:
        payload = verify_token(token)
        tenant_id = payload.get("tenant_id", "default")
        user_id = payload.get("user_id")
    except HTTPException:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    conn = await manager.connect_ws(websocket, tenant_id, user_id)
    
    try:
        await websocket.send_json({"type": "connected", "user_id": user_id, "tenant_id": tenant_id})
        
        async def heartbeat():
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
        
        heartbeat_task = asyncio.create_task(heartbeat())
        
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            action = msg.get("action")
            
            if action == "subscribe":
                manager.subscribe(conn, msg.get("channels", []))
                await websocket.send_json({"type": "subscribed", "channels": list(conn.channels)})
            elif action == "unsubscribe":
                manager.unsubscribe(conn, msg.get("channels", []))
                await websocket.send_json({"type": "unsubscribed", "channels": list(conn.channels)})
            elif action == "publish":
                await manager.broadcast(NotificationMessage(
                    channel=msg.get("channel", ""), event=msg.get("event", "message"),
                    data=msg.get("data", {}), tenant_id=tenant_id,
                ))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        heartbeat_task.cancel()
        manager.disconnect_ws(conn)


@app.get("/sse")
async def sse_endpoint(token: str = Query(...), channels: str = Query("*")):
    payload = verify_token(token)
    tenant_id = payload.get("tenant_id", "default")
    channel_list = channels.split(",")
    queue: asyncio.Queue = asyncio.Queue()
    
    manager.sse_connections[tenant_id].append(queue)
    manager.stats["sse_connections"] += 1
    
    async def event_generator():
        try:
            yield f"event: connected\ndata: {json.dumps({'tenant_id': tenant_id})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                    msg_data = json.loads(msg)
                    for pattern in channel_list:
                        if manager.matches_channel(pattern, msg_data.get("channel", "")):
                            yield f"event: message\ndata: {msg}\n\n"
                            break
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {json.dumps({'time': datetime.utcnow().isoformat()})}\n\n"
        finally:
            manager.sse_connections[tenant_id].remove(queue)
            manager.stats["sse_connections"] -= 1
    
    return StreamingResponse(event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.post("/api/notify")
async def send_notification(message: NotificationMessage):
    message.timestamp = datetime.utcnow().isoformat()
    await manager.broadcast(message)
    return {"status": "sent", "channel": message.channel}


@app.post("/api/broadcast")
async def broadcast_to_tenant(tenant_id: str, event: str, data: dict):
    message = NotificationMessage(channel="broadcast", event=event, data=data, tenant_id=tenant_id)
    await manager.broadcast(message)
    return {"status": "sent", "connections": len(manager.ws_connections.get(tenant_id, []))}


@app.get("/api/buffer/{channel}")
async def get_message_buffer(channel: str, limit: int = 10):
    return {"channel": channel, "messages": manager.message_buffer.get(channel, [])[-limit:]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
```

## Requirements

```txt requirements.txt
fastapi>=0.100.0
uvicorn>=0.20.0
pydantic>=2.0
pyjwt>=2.0
```

## Wygenerowane pliki (./sandbox)

Po uruchomieniu `pactown quadlet deploy` zostaną wygenerowane:

- `./sandbox/main.py` - Kod z tego README
- `./sandbox/requirements.txt` - Zależności
- `./sandbox/Dockerfile` - Obraz kontenera
- `./sandbox/notifications.container` - Quadlet unit file
