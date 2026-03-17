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


TOPIC_SEARCH_KEYWORDS: dict[str, dict[str, str]] = {
    # 사용자 맞춤
    "AI/인공지능": {"ko": "AI 인공지능", "en": "AI artificial intelligence"},
    "LLM/GPT": {"ko": "LLM GPT 대규모 언어모델", "en": "LLM GPT large language model"},
    "미국 주식": {"ko": "미국 주식 증시 월가", "en": "US stock market Wall Street"},
    "테슬라": {"ko": "테슬라 TSLA", "en": "Tesla TSLA"},
    "엔비디아": {"ko": "엔비디아 NVDA", "en": "Nvidia NVDA"},
    "구글": {"ko": "구글 알파벳 GOOGL", "en": "Google Alphabet GOOGL"},
    "환율/원달러": {"ko": "환율 원달러 USD KRW", "en": "USD KRW exchange rate"},
    "한국 경제": {"ko": "한국 경제 GDP 성장률", "en": "South Korea economy"},
    "금리": {"ko": "금리 기준금리 한국은행", "en": "interest rate Federal Reserve"},
    "프로그래밍": {"ko": "프로그래밍 개발자 코딩", "en": "programming developer coding"},
    "오픈소스": {"ko": "오픈소스 GitHub", "en": "open source GitHub"},
    "반도체": {"ko": "반도체 삼성전자 SK하이닉스", "en": "semiconductor chip TSMC"},
    # 대표 카테고리
    "부동산": {"ko": "부동산 아파트 집값", "en": "real estate housing market"},
    "암호화폐": {"ko": "암호화폐 비트코인 이더리움", "en": "cryptocurrency Bitcoin Ethereum"},
    "스타트업": {"ko": "스타트업 벤처 투자", "en": "startup venture funding"},
    "전기차": {"ko": "전기차 EV 자율주행", "en": "electric vehicle EV autonomous driving"},
    "클라우드": {"ko": "클라우드 AWS Azure", "en": "cloud computing AWS Azure"},
    "사이버보안": {"ko": "사이버보안 해킹 보안", "en": "cybersecurity hacking"},
    "게임": {"ko": "게임 e스포츠", "en": "gaming esports"},
    "우주/항공": {"ko": "우주 항공 NASA SpaceX", "en": "space NASA SpaceX"},
    "기후/환경": {"ko": "기후변화 탄소중립 환경", "en": "climate change carbon neutral"},
    "건강/의료": {"ko": "건강 의료 바이오", "en": "health medical biotech"},
    "스포츠": {"ko": "스포츠 축구 야구 NBA", "en": "sports MLB NBA soccer"},
    "K-POP/엔터": {"ko": "K-POP 아이돌 연예", "en": "K-POP idol entertainment"},
    "정치/시사": {"ko": "정치 국회 대통령", "en": "politics South Korea"},
    "국제/외교": {"ko": "국제 외교 미중관계", "en": "international diplomacy US China"},
}


async def collect_channel_topics(
    topic_slugs: list[str],
    custom_topics: list[str],
    config: CollectorConfig | None = None,
) -> list[Article]:
    """채널의 모든 주제에서 뉴스를 수집한다.

    topic_slugs: 미리 정의된 주제 slug 리스트 (예: ["AI/인공지능", "미국 주식"])
    custom_topics: 사용자 직접 입력 키워드 리스트 (예: ["베라더믹스"])
    """
    if config is None:
        config = CollectorConfig()

    all_articles: list[Article] = []

    # 1. 미리 정의된 주제별 수집
    for slug in topic_slugs:
        keywords = TOPIC_SEARCH_KEYWORDS.get(slug)
        if not keywords:
            logger.warning("알 수 없는 주제: %s", slug)
            continue

        # ko + en 각각 개별 검색
        for lang, query in keywords.items():
            for keyword_chunk in _split_query_keywords(query):
                articles = await collect_from_rss(keyword_chunk, lang=lang, max_articles=config.max_articles)
                all_articles.extend(articles)

        # DuckDuckGo (ko 키워드로)
        ko_query = keywords.get("ko", slug)
        try:
            result = await collect_from_search(ko_query, max_results=3)
            all_articles.extend(result)
        except Exception as e:
            logger.warning("DDG 뉴스 실패 (%s): %s", slug, e)
        await asyncio.sleep(1)

    # 2. 커스텀 주제 수집
    for custom in custom_topics:
        # 커스텀은 입력된 텍스트 그대로 ko + en 검색
        for lang in ["ko", "en"]:
            articles = await collect_from_rss(custom, lang=lang, max_articles=config.max_articles)
            all_articles.extend(articles)

        try:
            result = await collect_from_search(custom, max_results=3)
            all_articles.extend(result)
        except Exception as e:
            logger.warning("DDG 뉴스 실패 (%s): %s", custom, e)
        await asyncio.sleep(1)

    # 중복 제거
    articles = _deduplicate(all_articles)
    logger.info("채널 수집 완료: %d건 (중복 제거 후)", len(articles))

    # 본문 추출
    for article in articles:
        if not article.body:
            article.body = await _fetch_article_body(article.url, delay=config.fetch_delay)

    with_body = [a for a in articles if a.body]
    logger.info("본문 추출: %d/%d건", len(with_body), len(articles))
    return with_body


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
