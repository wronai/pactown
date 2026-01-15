import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from db import (
    init_db, get_records, get_record, create_record,
    update_record, delete_record, get_collections, get_stats
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(
    title="Database Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "service": "database"}

@app.get("/collections")
async def list_collections():
    return {"collections": await get_collections()}

@app.get("/stats")
async def database_stats():
    return await get_stats()

@app.get("/records/{collection}")
async def list_records(collection: str):
    records = await get_records(collection)
    return records

@app.post("/records/{collection}", status_code=201)
async def create_new_record(collection: str, data: dict):
    return await create_record(collection, data)

@app.get("/records/{collection}/{record_id}")
async def get_record_by_id(collection: str, record_id: int):
    record = await get_record(collection, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record

@app.put("/records/{collection}/{record_id}")
async def update_record_by_id(collection: str, record_id: int, data: dict):
    record = await update_record(collection, record_id, data)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record

@app.delete("/records/{collection}/{record_id}")
async def delete_record_by_id(collection: str, record_id: int):
    if await delete_record(collection, record_id):
        return {"message": "Record deleted"}
    raise HTTPException(status_code=404, detail="Record not found")