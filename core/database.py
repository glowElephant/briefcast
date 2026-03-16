"""SQLite 데이터베이스 모듈."""

import aiosqlite
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

KST = timezone(offset=__import__("datetime").timedelta(hours=9))

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "briefcast.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    query TEXT NOT NULL,
    languages TEXT NOT NULL DEFAULT 'ko,en',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
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
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


DEFAULT_SETTINGS = {
    "schedule_hour": "6",
    "schedule_minute": "0",
    "audio_format": "DEEP_DIVE",
    "audio_length": "DEFAULT",
}


async def init_db():
    """데이터베이스 초기화."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        # 기본 설정 삽입
        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()
    logger.info("DB 초기화 완료: %s", DB_PATH)


async def get_db() -> aiosqlite.Connection:
    """DB 연결을 반환한다."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


# === Topics ===

async def get_topics(enabled_only: bool = False) -> list[dict]:
    """주제 목록 조회."""
    db = await get_db()
    try:
        query = "SELECT * FROM topics"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at DESC"
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def add_topic(name: str, search_query: str, languages: str = "ko,en") -> int:
    """주제 추가."""
    now = datetime.now(KST).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO topics (name, query, languages, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, search_query, languages, now, now),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def update_topic(topic_id: int, **kwargs) -> None:
    """주제 수정."""
    allowed = {"name", "query", "languages", "enabled"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = datetime.now(KST).isoformat()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [topic_id]
    db = await get_db()
    try:
        await db.execute(f"UPDATE topics SET {sets} WHERE id = ?", values)
        await db.commit()
    finally:
        await db.close()


async def delete_topic(topic_id: int) -> None:
    """주제 삭제."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
        await db.commit()
    finally:
        await db.close()


# === Episodes ===

async def create_episode(topic_id: int, date: str) -> int:
    """에피소드 생성."""
    now = datetime.now(KST).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO episodes (topic_id, date, status, created_at, started_at) VALUES (?, ?, 'running', ?, ?)",
            (topic_id, date, now, now),
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


# === Settings ===

async def get_settings() -> dict[str, str]:
    """전체 설정 조회."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        await db.close()


async def update_settings(settings: dict[str, str]) -> None:
    """설정 업데이트."""
    db = await get_db()
    try:
        for key, value in settings.items():
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()
    finally:
        await db.close()


async def get_episodes(limit: int = 50) -> list[dict]:
    """최근 에피소드 목록."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT e.*, t.name as topic_name
               FROM episodes e JOIN topics t ON e.topic_id = t.id
               ORDER BY e.created_at DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
