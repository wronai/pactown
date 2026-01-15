from datetime import datetime
import os
import httpx

# In-memory storage for demo (connects to database service if available)
_users: dict[int, dict] = {}
_next_id = 1
_start_time = datetime.utcnow()

DATABASE_URL = os.environ.get("DATABASE_URL")

async def get_users() -> list[dict]:
    if DATABASE_URL:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{DATABASE_URL}/records/users")
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                pass
    return list(_users.values())

async def create_user(name: str, email: str) -> dict:
    global _next_id
    user = {
        "id": _next_id,
        "name": name,
        "email": email,
        "created_at": datetime.utcnow().isoformat(),
    }
    
    if DATABASE_URL:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{DATABASE_URL}/records/users",
                    json=user
                )
                if resp.status_code == 201:
                    _next_id += 1
                    return resp.json()
            except Exception:
                pass
    
    _users[_next_id] = user
    _next_id += 1
    return user

async def get_user(user_id: int) -> dict | None:
    if DATABASE_URL:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{DATABASE_URL}/records/users/{user_id}")
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                pass
    return _users.get(user_id)

async def delete_user(user_id: int) -> bool:
    if DATABASE_URL:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.delete(f"{DATABASE_URL}/records/users/{user_id}")
                return resp.status_code == 200
            except Exception:
                pass
    if user_id in _users:
        del _users[user_id]
        return True
    return False

def get_stats() -> dict:
    uptime = (datetime.utcnow() - _start_time).total_seconds()
    return {
        "total_users": len(_users),
        "active_services": 1,
        "uptime_seconds": uptime,
    }