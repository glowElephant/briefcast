"""뉴스 수집 모듈 — RSS + YouTube + X + 검색 + 본문 추출."""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import trafilatura
from duckduckgo_search import DDGS
from googlenewsdecoder import new_decoderv1

logger = logging.getLogger(__name__)

KST = timezone(offset=timedelta(hours=9))


@dataclass
class Article:
    """수집된 기사."""

    title: str
    url: str
    source: str
    body: str = ""
    published: str = ""
    collector: str = ""  # rss | search | youtube | x


@dataclass
class CollectorConfig:
    """수집 설정."""

    max_articles: int = 10
    fetch_delay: float = 1.5
    languages: list[str] = field(default_factory=lambda: ["ko", "en"])
    hours_back: int = 24  # 몇 시간 전 데이터까지 수집


def _google_news_rss_url(query: str, lang: str = "ko", country: str = "KR") -> str:
    """Google News RSS URL 생성. when:24h로 최근 24시간 필터."""
    encoded = query.replace(" ", "+")
    return (
        f"https://news.google.com/rss/search"
        f"?q={encoded}+when:24h&hl={lang}&gl={country}&ceid={country}:{lang}"
    )


def _clean_text(text: str) -> str:
    """본문 정리."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]


async def _fetch_article_body(url: str, delay: float = 1.5) -> str:
    """trafilatura로 기사 본문 추출."""
    try:
        await asyncio.sleep(delay)
        downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
        if not downloaded:
            return ""
        text = await asyncio.to_thread(trafilatura.extract, downloaded)
        return _clean_text(text or "")
    except Exception as e:
        logger.warning("본문 추출 실패 (%s): %s", url, e)
        return ""


async def collect_from_rss(
    query: str, lang: str = "ko", max_articles: int = 10
) -> list[Article]:
    """Google News RSS에서 최근 24시간 기사 수집."""
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
        # Google News URL → 실제 기사 URL 변환
        raw_url = entry.get("link", "")
        try:
            result = new_decoderv1(raw_url)
            actual_url = result.get("decoded_url", raw_url) if result.get("status") else raw_url
        except Exception:
            actual_url = raw_url
        articles.append(
            Article(
                title=entry.get("title", ""),
                url=actual_url,
                source=source,
                published=entry.get("published", ""),
                collector="rss",
            )
        )

    logger.info("RSS 수집: '%s' (%s) → %d건", query, lang, len(articles))
    return articles


async def collect_from_search(
    query: str, max_results: int = 5
) -> list[Article]:
    """DuckDuckGo 뉴스 검색 (최근 24시간)."""
    try:
        results = await asyncio.to_thread(
            lambda: list(DDGS().news(query, max_results=max_results, timelimit="d"))
        )
    except Exception as e:
        logger.warning("DuckDuckGo 뉴스 검색 실패 (%s): %s", query, e)
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

    logger.info("뉴스 검색: '%s' → %d건", query, len(articles))
    return articles


async def collect_from_youtube(
    query: str, max_results: int = 5
) -> list[Article]:
    """DuckDuckGo 비디오 검색으로 YouTube 뉴스 영상 수집."""
    try:
        results = await asyncio.to_thread(
            lambda: list(DDGS().videos(
                f"{query} site:youtube.com",
                max_results=max_results,
                timelimit="d",
            ))
        )
    except Exception as e:
        logger.warning("YouTube 검색 실패 (%s): %s", query, e)
        return []

    articles = []
    for r in results:
        url = r.get("content", r.get("url", ""))
        if "youtube.com" not in url and "youtu.be" not in url:
            continue
        # YouTube 영상 설명을 본문으로 활용
        description = r.get("description", "")
        articles.append(
            Article(
                title=r.get("title", ""),
                url=url,
                source=r.get("publisher", "YouTube"),
                body=_clean_text(description),
                published=r.get("published", ""),
                collector="youtube",
            )
        )

    logger.info("YouTube 수집: '%s' → %d건", query, len(articles))
    return articles


async def collect_from_x(
    query: str, max_results: int = 5
) -> list[Article]:
    """DuckDuckGo로 X(Twitter) 인기 게시물 수집."""
    try:
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(
                f"{query} site:x.com OR site:twitter.com",
                max_results=max_results,
                timelimit="d",
            ))
        )
    except Exception as e:
        logger.warning("X 검색 실패 (%s): %s", query, e)
        return []

    articles = []
    for r in results:
        url = r.get("href", "")
        if "x.com" not in url and "twitter.com" not in url:
            continue
        articles.append(
            Article(
                title=r.get("title", ""),
                url=url,
                source="X",
                body=_clean_text(r.get("body", "")),
                published="",
                collector="x",
            )
        )

    logger.info("X 수집: '%s' → %d건", query, len(articles))
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


def _split_query_keywords(query: str, max_words: int = 3) -> list[str]:
    """긴 검색 쿼리를 짧은 키워드 조합으로 분할.

    Google News RSS는 긴 쿼리에서 결과가 없는 경우가 많아
    키워드를 max_words개씩 잘라서 여러 번 검색한다.
    """
    words = query.split()
    if len(words) <= max_words:
        return [query]
    chunks = []
    for i in range(0, len(words), max_words):
        chunk = " ".join(words[i : i + max_words])
        if chunk:
            chunks.append(chunk)
    return chunks


async def collect_topic(
    topic: str,
    config: CollectorConfig | None = None,
) -> list[Article]:
    """주제에 대해 모든 소스에서 뉴스를 수집하고 본문을 추출한다."""
    if config is None:
        config = CollectorConfig()

    all_articles: list[Article] = []

    # 1. RSS 수집 (키워드 분할 + 언어별)
    rss_tasks = []
    for keyword_chunk in _split_query_keywords(topic):
        for lang in config.languages:
            rss_tasks.append(
                collect_from_rss(keyword_chunk, lang=lang, max_articles=config.max_articles)
            )
    rss_results = await asyncio.gather(*rss_tasks)
    for batch in rss_results:
        all_articles.extend(batch)

    # 2. DuckDuckGo 계열 (순차 실행 — rate limit 방지)
    ddg_collectors = [
        ("search", collect_from_search(topic, max_results=5)),
        ("youtube", collect_from_youtube(topic, max_results=5)),
        ("x", collect_from_x(topic, max_results=5)),
    ]
    for name, coro in ddg_collectors:
        try:
            result = await coro
            all_articles.extend(result)
        except Exception as e:
            logger.warning("DDG %s 수집 실패 (%s): %s", name, topic, e)
        await asyncio.sleep(1)  # DDG rate limit 방지

    articles = _deduplicate(all_articles)
    logger.info("'%s' 수집 완료: %d건 (중복 제거 후)", topic, len(articles))

    # 본문 추출 (YouTube, X는 이미 body가 있을 수 있음)
    for article in articles:
        if not article.body:
            article.body = await _fetch_article_body(
                article.url, delay=config.fetch_delay
            )

    # 본문 있는 기사만 반환
    with_body = [a for a in articles if a.body]
    logger.info("'%s' 본문 추출: %d/%d건", topic, len(with_body), len(articles))
    return with_body
