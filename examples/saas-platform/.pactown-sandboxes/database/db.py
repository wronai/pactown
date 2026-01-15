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