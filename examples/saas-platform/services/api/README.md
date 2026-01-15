# API Service

REST API backend for the SaaS platform. Provides user management, data endpoints, and health monitoring.

## Endpoints

- `GET /health` – Health check
- `GET /api/users` – List users
- `POST /api/users` – Create user
- `GET /api/users/{id}` – Get user
- `DELETE /api/users/{id}` – Delete user
- `GET /api/stats` – Platform statistics

## Environment Variables

- `DATABASE_URL` – Database connection URL
- `MARKPACT_PORT` – Service port (default: 8001)

---

```python markpact:deps
fastapi
uvicorn
httpx
pydantic
```

```python markpact:file path=app/models.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    name: str
    email: str

class User(BaseModel):
    id: int
    name: str
    email: str
    created_at: datetime

class Stats(BaseModel):
    total_users: int
    active_services: int
    uptime_seconds: float
```

```python markpact:file path=app/database.py
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
```

```python markpact:file path=app/main.py
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models import UserCreate, User, Stats
from app.database import get_users, create_user, get_user, delete_user, get_stats

app = FastAPI(
    title="SaaS Platform API",
    version="1.0.0",
    description="Backend API for the SaaS platform"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "service": "api"}

@app.get("/api/users")
async def list_users():
    users = await get_users()
    return {"users": users, "count": len(users)}

@app.post("/api/users", status_code=201)
async def create_new_user(user: UserCreate):
    new_user = await create_user(user.name, user.email)
    return new_user

@app.get("/api/users/{user_id}")
async def get_user_by_id(user_id: int):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.delete("/api/users/{user_id}")
async def delete_user_by_id(user_id: int):
    if await delete_user(user_id):
        return {"message": "User deleted"}
    raise HTTPException(status_code=404, detail="User not found")

@app.get("/api/stats", response_model=Stats)
def get_statistics():
    return get_stats()
```

```bash markpact:run
uvicorn app.main:app --host 0.0.0.0 --port ${MARKPACT_PORT:-8001} --reload
```

```http markpact:test
GET /health EXPECT 200
GET /api/users EXPECT 200
GET /api/stats EXPECT 200
POST /api/users BODY {"name":"Test","email":"test@example.com"} EXPECT 201
```
