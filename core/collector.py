"""뉴스 수집 모듈 — RSS + 검색 + 본문 추출."""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
import trafilatura
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

KST = timezone(offset=__import__("datetime").timedelta(hours=9))


@dataclass
class Article:
    """수집된 기사."""

    title: str
    url: str
    source: str
    body: str = ""
    published: str = ""
    collector: str = ""  # rss | search


@dataclass
class CollectorConfig:
    """수집 설정."""

    max_articles: int = 10
    fetch_delay: float = 1.5
    languages: list[str] = field(default_factory=lambda: ["ko", "en"])


def _google_news_rss_url(query: str, lang: str = "ko", country: str = "KR") -> str:
    """Google News RSS URL 생성."""
    encoded = query.replace(" ", "+")
    return (
        f"https://news.google.com/rss/search"
        f"?q={encoded}&hl={lang}&gl={country}&ceid={country}:{lang}"
    )


def _clean_text(text: str) -> str:
    """본문 정리."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]  # NotebookLM 소스 크기 제한 고려


async def _fetch_article_body(url: str, delay: float = 1.5) -> str:
    """trafilatura로 기사 본문 추출."""
    try:
        await asyncio.sleep(delay)
        downloaded = await asyncio.to_thread(
            trafilatura.fetch_url, url
        )
        if not downloaded:
            return ""
        text = await asyncio.to_thread(
            trafilatura.extract, downloaded
        )
        return _clean_text(text or "")
    except Exception as e:
        logger.warning("본문 추출 실패 (%s): %s", url, e)
        return ""


async def collect_from_rss(
    query: str, lang: str = "ko", max_articles: int = 10
) -> list[Article]:
    """Google News RSS에서 기사 수집."""
    country = "KR" if lang == "ko" else "US"
    url = _google_news_rss_url(query, lang, country)

    try:
        feed = await asyncio.to_thread(feedparser.parse, url)
    except Exception as e:
        logger.error("RSS 파싱 실패 (%s): %s", query, e)
        return []

    articles = []
    for entry in feed.entries[:max_articles]:
        source = ""
        if hasattr(entry, "source") and hasattr(entry.source, "title"):
            source = entry.source.title
        articles.append(
            Article(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                source=source,
                published=entry.get("published", ""),
                collector="rss",
            )
        )

    logger.info("RSS 수집: '%s' → %d건", query, len(articles))
    return articles


async def collect_from_search(
    query: str, max_results: int = 5
) -> list[Article]:
    """DuckDuckGo 뉴스 검색으로 보조 수집."""
    try:
        results = await asyncio.to_thread(
            lambda: list(DDGS().news(query, max_results=max_results))
        )
    except Exception as e:
        logger.warning("DuckDuckGo 검색 실패 (%s): %s", query, e)
        return []

    articles = []
    for r in results:
        articles.append(
            Article(
                title=r.get("title", ""),
                url=r.get("url", ""),
                source=r.get("source", ""),
                published=r.get("date", ""),
                collector="search",
            )
        )

    logger.info("검색 수집: '%s' → %d건", query, len(articles))
    return articles


def _deduplicate(articles: list[Article]) -> list[Article]:
    """URL 기반 중복 제거."""
    seen: set[str] = set()
    unique: list[Article] = []
    for a in articles:
        if a.url not in seen:
            seen.add(a.url)
            unique.append(a)
    return unique


async def collect_topic(
    topic: str,
    config: CollectorConfig | None = None,
) -> list[Article]:
    """주제에 대해 뉴스를 수집하고 본문을 추출한다."""
    if config is None:
        config = CollectorConfig()

    # RSS + 검색 병렬 수집
    rss_tasks = [
        collect_from_rss(topic, lang=lang, max_articles=config.max_articles)
        for lang in config.languages
    ]
    search_task = collect_from_search(topic, max_results=5)

    results = await asyncio.gather(*rss_tasks, search_task)
    all_articles: list[Article] = []
    for batch in results:
        all_articles.extend(batch)

    articles = _deduplicate(all_articles)
    logger.info("'%s' 수집 완료: %d건 (중복 제거 후)", topic, len(articles))

    # 본문 추출 (순차, rate limit 존중)
    for article in articles:
        article.body = await _fetch_article_body(
            article.url, delay=config.fetch_delay
        )

    # 본문 있는 기사만 반환
    with_body = [a for a in articles if a.body]
    logger.info("'%s' 본문 추출: %d/%d건", topic, len(with_body), len(articles))
    return with_body
