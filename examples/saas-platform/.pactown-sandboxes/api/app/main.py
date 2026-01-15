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