"""NotebookLM 팟캐스트 생성 모듈."""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

KST = timezone(offset=__import__("datetime").timedelta(hours=9))


async def generate_podcast(
    topic: str,
    articles_text: list[dict[str, str]],
    output_dir: Path,
    audio_format: str = "DEEP_DIVE",
    audio_length: str = "DEFAULT",
) -> Path | None:
    """NotebookLM으로 팟캐스트 오디오를 생성한다.

    Args:
        topic: 주제명
        articles_text: [{"title": ..., "body": ...}, ...]
        output_dir: MP3 저장 경로
        audio_format: DEEP_DIVE | BRIEF | CRITIQUE | DEBATE
        audio_length: SHORT | DEFAULT | LONG

    Returns:
        생성된 MP3 파일 경로, 실패 시 None
    """
    try:
        from notebooklm import NotebookLMClient
    except ImportError:
        logger.error("notebooklm-py가 설치되지 않았습니다: pip install 'notebooklm-py[browser]'")
        return None

    now = datetime.now(KST)
    notebook_name = f"[Briefcast] {topic} - {now.strftime('%Y-%m-%d')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_topic = "".join(c if c.isalnum() or c in "-_ " else "" for c in topic)
    filename = f"{now.strftime('%Y%m%d')}_{safe_topic}.mp3"
    output_path = output_dir / filename

    try:
        async with await NotebookLMClient.from_storage() as client:
            # 1. 노트북 생성
            nb = await client.notebooks.create(notebook_name)
            logger.info("노트북 생성: %s (id=%s)", notebook_name, nb.id)

            # 2. 기사를 소스로 추가
            for i, article in enumerate(articles_text):
                text = f"# {article['title']}\n\n{article['body']}"
                src = await client.sources.add_text(
                    nb.id, text, title=article["title"]
                )
                await client.sources.wait_until_ready(
                    nb.id, src.id, timeout_seconds=120
                )
                logger.info("소스 추가 (%d/%d): %s", i + 1, len(articles_text), article["title"][:50])
                await asyncio.sleep(1)

            # 3. 오디오 생성
            logger.info("오디오 생성 시작 (포맷=%s, 길이=%s)...", audio_format, audio_length)
            status = await client.artifacts.generate_audio(
                nb.id,
                audio_format=audio_format,
                audio_length=audio_length,
            )

            # 4. 생성 완료 대기
            timeout = 600  # 10분
            elapsed = 0
            poll_interval = 10
            while status.status == "GENERATING" and elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                status = await client.artifacts.poll(nb.id, status.artifact_id)
                logger.debug("오디오 생성 중... (%ds)", elapsed)

            if status.status != "COMPLETED":
                logger.error("오디오 생성 실패: status=%s", status.status)
                return None

            # 5. MP3 다운로드
            audio_bytes = await client.artifacts.download_audio(
                nb.id, status.artifact_id
            )
            output_path.write_bytes(audio_bytes)
            logger.info("MP3 저장: %s (%.1fMB)", output_path, len(audio_bytes) / 1024 / 1024)

            # 6. 노트북 정리 (선택)
            try:
                await client.notebooks.delete(nb.id)
                logger.info("노트북 삭제 완료: %s", nb.id)
            except Exception:
                logger.warning("노트북 삭제 실패 (수동 정리 필요): %s", nb.id)

            return output_path

    except FileNotFoundError:
        logger.error(
            "NotebookLM 인증 정보 없음. 'notebooklm login' 실행 필요"
        )
        return None
    except Exception as e:
        logger.error("팟캐스트 생성 실패 (%s): %s", topic, e)
        return None
