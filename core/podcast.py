"""NotebookLM 팟캐스트 생성 모듈."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from notebooklm.types import AudioFormat, AudioLength

logger = logging.getLogger(__name__)

AUDIO_FORMAT_MAP = {
    "DEEP_DIVE": AudioFormat.DEEP_DIVE,
    "BRIEF": AudioFormat.BRIEF,
    "CRITIQUE": AudioFormat.CRITIQUE,
    "DEBATE": AudioFormat.DEBATE,
}

AUDIO_LENGTH_MAP = {
    "SHORT": AudioLength.SHORT,
    "DEFAULT": AudioLength.DEFAULT,
    "LONG": AudioLength.LONG,
}

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
                body = article["body"]
                title = article["title"]
                await client.sources.add_text(
                    nb.id, title, f"# {title}\n\n{body}",
                    wait=True, wait_timeout=120,
                )
                logger.info("소스 추가 (%d/%d): %s", i + 1, len(articles_text), title[:50])

            # 3. 오디오 생성
            fmt = AUDIO_FORMAT_MAP.get(audio_format, AudioFormat.DEEP_DIVE)
            length = AUDIO_LENGTH_MAP.get(audio_length, AudioLength.DEFAULT)
            logger.info("오디오 생성 시작 (포맷=%s, 길이=%s)...", fmt.name, length.name)
            status = await client.artifacts.generate_audio(
                nb.id,
                language="ko",
                audio_format=fmt,
                audio_length=length,
            )

            # 4. 완료 대기 (내장 poll 사용)
            status = await client.artifacts.wait_for_completion(
                nb.id, status.task_id, timeout=600,
            )
            logger.info("오디오 생성 결과: %s", status.status)

            if status.status != "completed":
                logger.error("오디오 생성 실패: status=%s, error=%s", status.status, status.error)
                return None

            # 5. MP3 다운로드 (파일 경로에 직접 저장)
            saved_path = await client.artifacts.download_audio(
                nb.id, str(output_path),
            )
            file_size = output_path.stat().st_size
            logger.info("MP3 저장: %s (%.1fMB)", saved_path, file_size / 1024 / 1024)

            # 6. 노트북 정리
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
