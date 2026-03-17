"""스케줄러 + 파이프라인 실행 모듈."""

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
    get_settings,
    create_episode,
    update_episode,
)

logger = logging.getLogger(__name__)

KST = timezone(offset=__import__("datetime").timedelta(hours=9))
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

# 모듈 레벨에서 scheduler 참조 유지
_scheduler: AsyncIOScheduler | None = None

# 통합 에피소드용 가상 topic_id
COMBINED_TOPIC_ID = 0


async def run_pipeline(topic: dict | None = None, settings: dict | None = None) -> None:
    """전체 파이프라인 실행. 모든 토픽의 뉴스를 합쳐 하나의 팟캐스트 생성."""
    if settings is None:
        settings = await get_settings()

    now = datetime.now(KST)
    date_str = now.strftime("%Y-%m-%d")

    # 단일 토픽 지정 시 해당 토픽만, 아니면 전체 활성 토픽
    if topic:
        topics = [topic]
    else:
        topics = await get_topics(enabled_only=True)

    if not topics:
        logger.info("활성화된 주제 없음 — 스킵")
        return

    topic_names = [t["name"] for t in topics]
    combined_name = " + ".join(topic_names)
    logger.info("=== 브리프캐스트 시작: %s (%s) ===", combined_name, date_str)

    # 에피소드는 첫 번째 토픽 ID로 기록
    episode_id = await create_episode(topics[0]["id"], date_str)

    try:
        # 1. 모든 토픽에서 뉴스 수집
        all_articles = []
        for t in topics:
            search_query = t["query"]
            languages = t.get("languages", "ko,en").split(",")
            config = CollectorConfig(
                max_articles=int(os.getenv("MAX_ARTICLES_PER_TOPIC", "10")),
                fetch_delay=float(os.getenv("ARTICLE_FETCH_DELAY", "1.5")),
                languages=languages,
            )
            articles = await collect_topic(search_query, config)
            logger.info("'%s' → %d건 수집", t["name"], len(articles))
            all_articles.extend(articles)

        if not all_articles:
            logger.warning("수집된 기사 없음")
            await update_episode(
                episode_id,
                status="failed",
                error="수집된 기사 없음",
                completed_at=datetime.now(KST).isoformat(),
            )
            return

        # URL 기반 중복 제거
        seen = set()
        unique_articles = []
        for a in all_articles:
            if a.url not in seen:
                seen.add(a.url)
                unique_articles.append(a)

        # NotebookLM 소스 제한: 최대 15건으로 제한 (본문 길이 순)
        MAX_PODCAST_ARTICLES = 10
        if len(unique_articles) > MAX_PODCAST_ARTICLES:
            unique_articles.sort(key=lambda a: len(a.body), reverse=True)
            unique_articles = unique_articles[:MAX_PODCAST_ARTICLES]
            logger.info("기사 수 제한: %d건 → %d건", len(unique_articles), MAX_PODCAST_ARTICLES)

        await update_episode(episode_id, articles_count=len(unique_articles))
        logger.info("전체 수집: %d건 (중복 제거 후)", len(unique_articles))

        # 2. 하나의 팟캐스트로 생성
        articles_text = [
            {"title": a.title, "body": a.body} for a in unique_articles
        ]
        mp3_path = await generate_podcast(
            topic=f"오늘의 브리핑 ({date_str})",
            articles_text=articles_text,
            output_dir=OUTPUT_DIR,
            audio_format=settings.get("audio_format", "DEEP_DIVE"),
            audio_length=settings.get("audio_length", "DEFAULT"),
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
        logger.info("=== 브리프캐스트 완료 ===")

    except Exception as e:
        logger.error("파이프라인 실패: %s", e)
        await update_episode(
            episode_id,
            status="failed",
            error=str(e)[:500],
            completed_at=datetime.now(KST).isoformat(),
        )


async def run_all_topics() -> None:
    """모든 활성 토픽을 합쳐서 하나의 팟캐스트 생성."""
    await run_pipeline()


async def reschedule(hour: int, minute: int) -> None:
    """스케줄 시간 변경 (대시보드에서 호출)."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.reschedule_job(
        "daily_briefcast",
        trigger="cron",
        hour=hour,
        minute=minute,
    )
    logger.info("스케줄 변경: 매일 %02d:%02d KST", hour, minute)


def create_scheduler() -> AsyncIOScheduler:
    """APScheduler 인스턴스 생성."""
    global _scheduler
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
    _scheduler = scheduler
    return scheduler
