"""Briefcast — 웹 대시보드 + 스케줄러 서버."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.database import (
    init_db,
    get_channels,
    add_channel,
    update_channel,
    delete_channel,
    get_episodes,
)
from core.scheduler import create_scheduler, run_channel, reschedule_all, init_schedules

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 이벤트."""
    await init_db()
    scheduler = create_scheduler()
    await init_schedules()
    scheduler.start()
    logger.info("Briefcast 서버 시작")
    yield
    scheduler.shutdown()
    logger.info("Briefcast 서버 종료")


app = FastAPI(title="Briefcast", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# === Pages ===

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """대시보드 페이지."""
    channels = await get_channels()
    episodes = await get_episodes(limit=30)
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "channels": channels, "episodes": episodes},
    )


# === API: Channels ===

@app.get("/api/channels")
async def api_get_channels():
    """채널 목록 조회."""
    channels = await get_channels()
    return JSONResponse(channels)


@app.post("/api/channels")
async def api_add_channel(request: Request):
    """채널 추가."""
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "name은 필수"}, status_code=400)

    channel_id = await add_channel(
        name=name,
        schedule_hour=int(data.get("schedule_hour", 7)),
        schedule_minute=int(data.get("schedule_minute", 0)),
        topics=data.get("topics", []),
        custom_topics=data.get("custom_topics", []),
        audio_format=data.get("audio_format", "DEEP_DIVE"),
        audio_length=data.get("audio_length", "DEFAULT"),
    )
    await reschedule_all()
    return JSONResponse({"id": channel_id, "message": "채널 추가 완료"})


@app.put("/api/channels/{channel_id}")
async def api_update_channel(channel_id: int, request: Request):
    """채널 수정."""
    data = await request.json()
    await update_channel(channel_id, **data)
    await reschedule_all()
    return JSONResponse({"message": "채널 수정 완료"})


@app.delete("/api/channels/{channel_id}")
async def api_delete_channel(channel_id: int):
    """채널 삭제."""
    await delete_channel(channel_id)
    await reschedule_all()
    return JSONResponse({"message": "채널 삭제 완료"})


# === API: Episodes ===

@app.get("/api/episodes")
async def api_get_episodes():
    """에피소드 목록 조회."""
    episodes = await get_episodes(limit=50)
    return JSONResponse(episodes)


# === API: Actions ===

@app.post("/api/run/{channel_id}")
async def api_run_channel(channel_id: int):
    """특정 채널 즉시 실행."""
    channels = await get_channels()
    channel = next((c for c in channels if c["id"] == channel_id), None)
    if not channel:
        return JSONResponse({"error": "채널을 찾을 수 없음"}, status_code=404)

    import asyncio
    asyncio.create_task(run_channel(channel))
    return JSONResponse({"message": f"'{channel['name']}' 실행 시작"})


@app.post("/api/run-all")
async def api_run_all():
    """모든 활성 채널 즉시 실행."""
    channels = await get_channels(enabled_only=True)
    if not channels:
        return JSONResponse({"message": "활성 채널 없음"})

    import asyncio
    for ch in channels:
        asyncio.create_task(run_channel(ch))
    return JSONResponse({"message": f"{len(channels)}개 채널 실행 시작"})


# === API: Available Topics ===

@app.get("/api/available-topics")
async def api_available_topics():
    """사용 가능한 주제 목록 반환."""
    from core.collector import TOPIC_SEARCH_KEYWORDS
    return JSONResponse(list(TOPIC_SEARCH_KEYWORDS.keys()))


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8585"))
    reload = os.getenv("BRIEFCAST_RELOAD", "false").lower() == "true"
    uvicorn.run("server:app", host=host, port=port, reload=reload)
