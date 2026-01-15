# Database Service

Simple key-value database service with REST API. Provides persistent storage for the SaaS platform.

## Endpoints

- `GET /health` – Health check
- `GET /records/{collection}` – List records in collection
- `POST /records/{collection}` – Create record
- `GET /records/{collection}/{id}` – Get record by ID
- `PUT /records/{collection}/{id}` – Update record
- `DELETE /records/{collection}/{id}` – Delete record

## Storage

Data is persisted to SQLite database in the sandbox directory.

---
```python markpact:deps
fastapi
uvicorn
aiosqlite
```

```python markpact:file path=db.py
import aiosqlite
import json
from pathlib import Path
from typing import Optional, Any

DB_PATH = Path("./data.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_collection ON records(collection)
        """)
        await db.commit()

async def get_records(collection: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM records WHERE collection = ? ORDER BY id",
            (collection,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {**json.loads(row["data"]), "id": row["id"]}
                for row in rows
            ]

async def get_record(collection: str, record_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM records WHERE collection = ? AND id = ?",
            (collection, record_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {**json.loads(row["data"]), "id": row["id"]}
            return None

async def create_record(collection: str, data: dict) -> dict:
    data_copy = {k: v for k, v in data.items() if k != "id"}
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO records (collection, data) VALUES (?, ?)",
            (collection, json.dumps(data_copy))
        )
        await db.commit()
        return {**data_copy, "id": cursor.lastrowid}

async def update_record(collection: str, record_id: int, data: dict) -> Optional[dict]:
    data_copy = {k: v for k, v in data.items() if k != "id"}
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """UPDATE records 
               SET data = ?, updated_at = CURRENT_TIMESTAMP 
               WHERE collection = ? AND id = ?""",
            (json.dumps(data_copy), collection, record_id)
        )
        await db.commit()
        if cursor.rowcount > 0:
            return {**data_copy, "id": record_id}
        return None

async def delete_record(collection: str, record_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM records WHERE collection = ? AND id = ?",
            (collection, record_id)
        )
        await db.commit()
        return cursor.rowcount > 0

async def get_collections() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT DISTINCT collection FROM records"
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM records") as cursor:
            total = (await cursor.fetchone())[0]
        collections = await get_collections()
        return {
            "total_records": total,
            "collections": len(collections),
            "collection_names": collections,
        }
```

```python markpact:file path=main.py
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
```

```bash markpact:run
uvicorn main:app --host 0.0.0.0 --port ${MARKPACT_PORT:-8003} --reload
```

```http markpact:test
GET /health EXPECT 200
GET /collections EXPECT 200
GET /stats EXPECT 200
POST /records/test BODY {"name":"item1"} EXPECT 201
GET /records/test EXPECT 200
```
