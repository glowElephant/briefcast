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
    get_topics,
    add_topic,
    update_topic,
    delete_topic,
    get_episodes,
)
from core.scheduler import create_scheduler, run_pipeline, run_all_topics

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
    topics = await get_topics()
    episodes = await get_episodes(limit=30)
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "topics": topics, "episodes": episodes},
    )


# === API: Topics ===

@app.get("/api/topics")
async def api_get_topics():
    """주제 목록 조회."""
    topics = await get_topics()
    return JSONResponse(topics)


@app.post("/api/topics")
async def api_add_topic(request: Request):
    """주제 추가."""
    data = await request.json()
    name = data.get("name", "").strip()
    query = data.get("query", "").strip()
    languages = data.get("languages", "ko,en").strip()

    if not name or not query:
        return JSONResponse({"error": "name과 query는 필수"}, status_code=400)

    topic_id = await add_topic(name, query, languages)
    return JSONResponse({"id": topic_id, "message": "추가 완료"})


@app.put("/api/topics/{topic_id}")
async def api_update_topic(topic_id: int, request: Request):
    """주제 수정."""
    data = await request.json()
    await update_topic(topic_id, **data)
    return JSONResponse({"message": "수정 완료"})


@app.delete("/api/topics/{topic_id}")
async def api_delete_topic(topic_id: int):
    """주제 삭제."""
    await delete_topic(topic_id)
    return JSONResponse({"message": "삭제 완료"})


# === API: Episodes ===

@app.get("/api/episodes")
async def api_get_episodes():
    """에피소드 목록 조회."""
    episodes = await get_episodes(limit=50)
    return JSONResponse(episodes)


# === API: Actions ===

@app.post("/api/run/{topic_id}")
async def api_run_topic(topic_id: int):
    """특정 주제 즉시 실행."""
    topics = await get_topics()
    topic = next((t for t in topics if t["id"] == topic_id), None)
    if not topic:
        return JSONResponse({"error": "주제를 찾을 수 없음"}, status_code=404)

    import asyncio
    asyncio.create_task(run_pipeline(topic))
    return JSONResponse({"message": f"'{topic['name']}' 실행 시작"})


@app.post("/api/run-all")
async def api_run_all():
    """모든 활성 주제 즉시 실행."""
    import asyncio
    asyncio.create_task(run_all_topics())
    return JSONResponse({"message": "전체 실행 시작"})


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8585"))
    uvicorn.run("server:app", host=host, port=port, reload=True)
