"""스케줄러 + 파이프라인 실행 모듈."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.collector import CollectorConfig, collect_channel_topics
from core.podcast import generate_podcast
from core.drive import upload_file, ensure_folder
from core.database import (
    get_channels,
    create_episode,
    update_episode,
)

logger = logging.getLogger(__name__)

KST = timezone(offset=__import__("datetime").timedelta(hours=9))
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

_scheduler: AsyncIOScheduler | None = None

MAX_PODCAST_ARTICLES = 10


async def run_channel(channel: dict) -> None:
    """단일 채널 파이프라인 실행."""
    now = datetime.now(KST)
    date_str = now.strftime("%Y-%m-%d")

    channel_name = channel["name"]
    logger.info("=== 채널 '%s' 시작 (%s) ===", channel_name, date_str)

    episode_id = await create_episode(channel["id"], date_str)

    try:
        # 1. 뉴스 수집
        topics = json.loads(channel["topics"]) if isinstance(channel["topics"], str) else channel["topics"]
        custom_topics = json.loads(channel["custom_topics"]) if isinstance(channel["custom_topics"], str) else channel["custom_topics"]

        config = CollectorConfig(
            max_articles=int(os.getenv("MAX_ARTICLES_PER_TOPIC", "10")),
            fetch_delay=float(os.getenv("ARTICLE_FETCH_DELAY", "1.5")),
        )
        all_articles = await collect_channel_topics(topics, custom_topics, config)

        if not all_articles:
            logger.warning("채널 '%s': 수집된 기사 없음", channel_name)
            await update_episode(
                episode_id,
                status="failed",
                error="수집된 기사 없음",
                completed_at=datetime.now(KST).isoformat(),
            )
            return

        # 본문 길이순 상위 N건 제한
        if len(all_articles) > MAX_PODCAST_ARTICLES:
            all_articles.sort(key=lambda a: len(a.body), reverse=True)
            all_articles = all_articles[:MAX_PODCAST_ARTICLES]
            logger.info("기사 수 제한: → %d건", MAX_PODCAST_ARTICLES)

        await update_episode(episode_id, articles_count=len(all_articles))
        logger.info("채널 '%s' 수집: %d건", channel_name, len(all_articles))

        # 2. 팟캐스트 생성
        articles_text = [
            {"title": a.title, "body": a.body} for a in all_articles
        ]
        mp3_path = await generate_podcast(
            topic=f"{channel_name} ({date_str})",
            articles_text=articles_text,
            output_dir=OUTPUT_DIR,
            audio_format=channel.get("audio_format", "DEEP_DIVE"),
            audio_length=channel.get("audio_length", "DEFAULT"),
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
        logger.info("=== 채널 '%s' 완료 ===", channel_name)

    except Exception as e:
        logger.error("채널 '%s' 실패: %s", channel_name, e)
        await update_episode(
            episode_id,
            status="failed",
            error=str(e)[:500],
            completed_at=datetime.now(KST).isoformat(),
        )


async def run_channel_by_id(channel_id: int) -> None:
    """채널 ID로 파이프라인 실행 (스케줄러에서 호출)."""
    channels = await get_channels()
    channel = next((c for c in channels if c["id"] == channel_id), None)
    if channel:
        await run_channel(channel)


async def reschedule_all() -> None:
    """모든 채널의 스케줄을 재등록."""
    global _scheduler
    if _scheduler is None:
        return

    # 기존 채널 job 삭제
    for job in _scheduler.get_jobs():
        if job.id.startswith("channel_"):
            _scheduler.remove_job(job.id)

    # 활성 채널 재등록
    channels = await get_channels(enabled_only=True)
    for ch in channels:
        _scheduler.add_job(
            run_channel_by_id,
            trigger="cron",
            hour=ch["schedule_hour"],
            minute=ch["schedule_minute"],
            args=[ch["id"]],
            id=f"channel_{ch['id']}",
            name=f"{ch['name']} ({ch['schedule_hour']:02d}:{ch['schedule_minute']:02d})",
            replace_existing=True,
        )
        logger.info("스케줄 등록: '%s' → %02d:%02d KST", ch["name"], ch["schedule_hour"], ch["schedule_minute"])


def create_scheduler() -> AsyncIOScheduler:
    """APScheduler 인스턴스 생성."""
    global _scheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    _scheduler = scheduler
    return scheduler


async def init_schedules() -> None:
    """서버 시작 시 활성 채널 스케줄 등록."""
    await reschedule_all()
