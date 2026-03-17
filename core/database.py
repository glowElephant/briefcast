"""SQLite 데이터베이스 모듈."""

import json
import aiosqlite
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

KST = timezone(offset=__import__("datetime").timedelta(hours=9))

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "briefcast.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    schedule_hour INTEGER NOT NULL DEFAULT 7,
    schedule_minute INTEGER NOT NULL DEFAULT 0,
    topics TEXT NOT NULL DEFAULT '[]',
    custom_topics TEXT NOT NULL DEFAULT '[]',
    audio_format TEXT NOT NULL DEFAULT 'DEEP_DIVE',
    audio_length TEXT NOT NULL DEFAULT 'DEFAULT',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    articles_count INTEGER DEFAULT 0,
    mp3_path TEXT,
    drive_id TEXT,
    drive_link TEXT,
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);
"""


async def init_db():
    """데이터베이스 초기화."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()
    logger.info("DB 초기화 완료: %s", DB_PATH)


async def get_db() -> aiosqlite.Connection:
    """DB 연결을 반환한다."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


# === Channels ===

async def get_channels(enabled_only: bool = False) -> list[dict]:
    """채널 목록 조회. topics, custom_topics는 JSON parse해서 리스트로 반환."""
    db = await get_db()
    try:
        query = "SELECT * FROM channels"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at DESC"
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["topics"] = json.loads(d["topics"]) if isinstance(d["topics"], str) else d["topics"]
            d["custom_topics"] = json.loads(d["custom_topics"]) if isinstance(d["custom_topics"], str) else d["custom_topics"]
            result.append(d)
        return result
    finally:
        await db.close()


async def add_channel(
    name: str,
    schedule_hour: int = 7,
    schedule_minute: int = 0,
    topics: list[str] | None = None,
    custom_topics: list[str] | None = None,
    audio_format: str = "DEEP_DIVE",
    audio_length: str = "DEFAULT",
) -> int:
    """채널 추가."""
    now = datetime.now(KST).isoformat()
    topics_json = json.dumps(topics or [], ensure_ascii=False)
    custom_topics_json = json.dumps(custom_topics or [], ensure_ascii=False)
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO channels
               (name, schedule_hour, schedule_minute, topics, custom_topics,
                audio_format, audio_length, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, schedule_hour, schedule_minute, topics_json, custom_topics_json,
             audio_format, audio_length, now, now),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def update_channel(channel_id: int, **kwargs) -> None:
    """채널 수정."""
    allowed = {"name", "schedule_hour", "schedule_minute", "topics", "custom_topics",
               "audio_format", "audio_length", "enabled"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    # topics, custom_topics는 리스트면 JSON 직렬화
    for json_field in ("topics", "custom_topics"):
        if json_field in fields and isinstance(fields[json_field], list):
            fields[json_field] = json.dumps(fields[json_field], ensure_ascii=False)
    fields["updated_at"] = datetime.now(KST).isoformat()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [channel_id]
    db = await get_db()
    try:
        await db.execute(f"UPDATE channels SET {sets} WHERE id = ?", values)
        await db.commit()
    finally:
        await db.close()


async def delete_channel(channel_id: int) -> None:
    """채널 삭제."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        await db.commit()
    finally:
        await db.close()


# === Episodes ===

async def create_episode(channel_id: int, date: str) -> int:
    """에피소드 생성."""
    now = datetime.now(KST).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO episodes (channel_id, date, status, created_at, started_at) VALUES (?, ?, 'running', ?, ?)",
            (channel_id, date, now, now),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def update_episode(episode_id: int, **kwargs) -> None:
    """에피소드 업데이트."""
    allowed = {"status", "articles_count", "mp3_path", "drive_id", "drive_link", "error", "completed_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [episode_id]
    db = await get_db()
    try:
        await db.execute(f"UPDATE episodes SET {sets} WHERE id = ?", values)
        await db.commit()
    finally:
        await db.close()


async def get_episodes(limit: int = 50) -> list[dict]:
    """최근 에피소드 목록."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT e.*, c.name as channel_name
               FROM episodes e JOIN channels c ON e.channel_id = c.id
               ORDER BY e.created_at DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
