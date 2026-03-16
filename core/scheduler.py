"""스케줄러 + 파이프라인 실행 모듈."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.collector import CollectorConfig, collect_topic
from core.podcast import generate_podcast
from core.drive import upload_file, ensure_folder
from core.database import (
    get_topics,
    create_episode,
    update_episode,
)

logger = logging.getLogger(__name__)

KST = timezone(offset=__import__("datetime").timedelta(hours=9))
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


async def run_pipeline(topic: dict) -> None:
    """단일 주제에 대한 전체 파이프라인 실행."""
    now = datetime.now(KST)
    date_str = now.strftime("%Y-%m-%d")
    topic_name = topic["name"]
    search_query = topic["query"]
    languages = topic.get("languages", "ko,en").split(",")

    logger.info("=== 파이프라인 시작: %s (%s) ===", topic_name, date_str)

    episode_id = await create_episode(topic["id"], date_str)

    try:
        # 1. 뉴스 수집
        config = CollectorConfig(
            max_articles=int(os.getenv("MAX_ARTICLES_PER_TOPIC", "10")),
            fetch_delay=float(os.getenv("ARTICLE_FETCH_DELAY", "1.5")),
            languages=languages,
        )
        articles = await collect_topic(search_query, config)

        if not articles:
            logger.warning("수집된 기사 없음: %s", topic_name)
            await update_episode(
                episode_id,
                status="failed",
                error="수집된 기사 없음",
                completed_at=datetime.now(KST).isoformat(),
            )
            return

        await update_episode(episode_id, articles_count=len(articles))

        # 2. 팟캐스트 생성
        articles_text = [
            {"title": a.title, "body": a.body} for a in articles
        ]
        mp3_path = await generate_podcast(
            topic=topic_name,
            articles_text=articles_text,
            output_dir=OUTPUT_DIR,
            audio_format=os.getenv("AUDIO_FORMAT", "DEEP_DIVE"),
            audio_length=os.getenv("AUDIO_LENGTH", "DEFAULT"),
        )

        if not mp3_path:
            await update_episode(
                episode_id,
                status="failed",
                error="오디오 생성 실패",
                completed_at=datetime.now(KST).isoformat(),
            )
            return

        await update_episode(episode_id, mp3_path=str(mp3_path))

        # 3. Google Drive 업로드
        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
        if folder_id:
            # 날짜별 하위 폴더
            date_folder_id = ensure_folder(date_str, parent_id=folder_id)
            target_folder = date_folder_id or folder_id
            drive_id = upload_file(mp3_path, folder_id=target_folder)
            if drive_id:
                await update_episode(episode_id, drive_id=drive_id)
        else:
            logger.warning("GOOGLE_DRIVE_FOLDER_ID 미설정 — Drive 업로드 스킵")

        await update_episode(
            episode_id,
            status="completed",
            completed_at=datetime.now(KST).isoformat(),
        )
        logger.info("=== 파이프라인 완료: %s ===", topic_name)

    except Exception as e:
        logger.error("파이프라인 실패 (%s): %s", topic_name, e)
        await update_episode(
            episode_id,
            status="failed",
            error=str(e)[:500],
            completed_at=datetime.now(KST).isoformat(),
        )


async def run_all_topics() -> None:
    """활성화된 모든 주제에 대해 파이프라인 실행."""
    topics = await get_topics(enabled_only=True)
    if not topics:
        logger.info("활성화된 주제 없음 — 스킵")
        return

    logger.info("=== 일일 브리프캐스트 시작 (%d개 주제) ===", len(topics))
    for topic in topics:
        await run_pipeline(topic)
    logger.info("=== 일일 브리프캐스트 완료 ===")


def create_scheduler() -> AsyncIOScheduler:
    """APScheduler 인스턴스 생성."""
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    hour = int(os.getenv("SCHEDULE_HOUR", "6"))
    minute = int(os.getenv("SCHEDULE_MINUTE", "0"))

    scheduler.add_job(
        run_all_topics,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="daily_briefcast",
        name=f"Daily Briefcast ({hour:02d}:{minute:02d})",
        replace_existing=True,
    )

    logger.info("스케줄 등록: 매일 %02d:%02d KST", hour, minute)
    return scheduler
