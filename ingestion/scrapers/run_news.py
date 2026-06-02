"""뉴스 스크래퍼 스타터.

RSS 피드를 우선 사용(robots/ToS 준수가 쉬움). 수집한 기사를 Postgres raw_news에
멱등 UPSERT한다. 이후는 CDC가 자동으로 그래프까지 전파한다.

사용:
    python ingestion/scrapers/run_news.py

환경변수:
    PG_DSN  (기본 postgresql://fin:fin@localhost:5432/findb)
    NEWS_FEEDS  (쉼표구분 RSS URL. 없으면 샘플 데모 데이터 삽입)

주의(준법): 실제 사이트 스크래핑 시 robots.txt / 이용약관 / 요청간격(rate limit)을
반드시 준수하고, 가능하면 공식 RSS/API를 사용할 것.
"""
from __future__ import annotations
import os
import sys
import time
import datetime as dt


SAMPLE_NEWS = [
    {
        "url": "https://example.com/news/sample-1",
        "title": "삼성전자, 차세대 HBM 양산 본격화…공급 확대 기대",
        "body": "삼성전자가 차세대 HBM 메모리 양산을 시작하며 호재로 작용. 수혜 전망.",
        "source": "SampleWire", "lang": "ko",
        "published_at": dt.datetime.utcnow().isoformat(),
    },
    {
        "url": "https://example.com/news/sample-2",
        "title": "비트코인 현물 ETF 자금 유입 가속…기관 매수세 유입",
        "body": "기관 자금이 비트코인 현물 ETF로 유입되며 상승 모멘텀. 급등.",
        "source": "SampleCrypto", "lang": "ko",
        "published_at": dt.datetime.utcnow().isoformat(),
    },
]

UPSERT = """
INSERT INTO raw_news (url, title, body, source, lang, published_at)
VALUES (%(url)s, %(title)s, %(body)s, %(source)s, %(lang)s, %(published_at)s)
ON CONFLICT (url) DO UPDATE
SET title=EXCLUDED.title, body=EXCLUDED.body, source=EXCLUDED.source,
    lang=EXCLUDED.lang, published_at=EXCLUDED.published_at
"""


def fetch_rss(url: str) -> list[dict]:
    """RSS 파싱. feedparser 있으면 사용, 없으면 빈 리스트."""
    try:
        import feedparser
    except ImportError:
        print("[!] feedparser 미설치 → RSS 건너뜀 (pip install feedparser)")
        return []
    feed = feedparser.parse(url)
    items = []
    for e in feed.entries:
        items.append({
            "url": e.get("link"),
            "title": e.get("title", ""),
            "body": e.get("summary", ""),
            "source": feed.feed.get("title", url),
            "lang": "ko",
            "published_at": _parse_dt(e),
        })
    return [i for i in items if i["url"]]


def _parse_dt(entry) -> str:
    if getattr(entry, "published_parsed", None):
        return dt.datetime(*entry.published_parsed[:6]).isoformat()
    return dt.datetime.utcnow().isoformat()


def upsert(rows: list[dict], dsn: str) -> int:
    if not rows:
        return 0
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.executemany(UPSERT, rows)
        conn.commit()
    return len(rows)


def main() -> None:
    dsn = os.getenv("PG_DSN", "postgresql://fin:fin@localhost:5432/findb")
    feeds = [u for u in os.getenv("NEWS_FEEDS", "").split(",") if u.strip()]

    rows: list[dict] = []
    for url in feeds:
        print(f"[*] RSS 수집: {url}")
        rows.extend(fetch_rss(url.strip()))
        time.sleep(1)  # rate limit 매너

    if not rows:
        print("[*] 피드 없음 → 샘플 데모 데이터 삽입")
        rows = SAMPLE_NEWS

    try:
        n = upsert(rows, dsn)
        print(f"[done] raw_news UPSERT {n}건 → CDC가 그래프로 전파합니다.")
    except Exception as e:  # noqa: BLE001
        print(f"[!] DB 적재 실패({e}). Postgres 기동/스키마 적용 여부 확인.")
        sys.exit(1)


if __name__ == "__main__":
    main()
