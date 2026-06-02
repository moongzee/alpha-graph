-- ============================================================
-- 원천 DB(staging) 스키마 + CDC publication
-- 적용: psql "postgresql://fin:fin@localhost:5432/findb" -f ingestion/db/schema.sql
-- ============================================================

-- ---------- 자산 마스터 ----------
CREATE TABLE IF NOT EXISTS assets (
    id          BIGSERIAL PRIMARY KEY,
    symbol      TEXT NOT NULL,
    name        TEXT NOT NULL,
    asset_type  TEXT NOT NULL CHECK (asset_type IN ('STOCK','CRYPTO')),
    market      TEXT NOT NULL,
    currency    TEXT,
    sector      TEXT,
    aliases     TEXT[] DEFAULT '{}',   -- 엔티티 해소용 별칭 사전
    updated_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (symbol, market)
);

-- ---------- 뉴스 원천 ----------
CREATE TABLE IF NOT EXISTS raw_news (
    id            BIGSERIAL PRIMARY KEY,
    url           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    body          TEXT,
    source        TEXT,
    lang          TEXT DEFAULT 'ko',
    published_at  TIMESTAMPTZ,
    scraped_at    TIMESTAMPTZ DEFAULT now()
);

-- ---------- 시세(원시 시계열) ----------
CREATE TABLE IF NOT EXISTS price_bars (
    id        BIGSERIAL PRIMARY KEY,
    symbol    TEXT NOT NULL,
    market    TEXT NOT NULL,
    interval  TEXT NOT NULL,           -- 1m,5m,1h,1d ...
    ts        TIMESTAMPTZ NOT NULL,
    open      NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC,
    volume    NUMERIC,
    UNIQUE (symbol, market, interval, ts)
);
CREATE INDEX IF NOT EXISTS idx_price_symbol_ts ON price_bars (symbol, market, ts DESC);

-- ---------- 추출 이벤트 ----------
CREATE TABLE IF NOT EXISTS events (
    id           BIGSERIAL PRIMARY KEY,
    event_id     TEXT NOT NULL UNIQUE,
    type         TEXT NOT NULL,        -- EARNINGS, REGULATION, LISTING, HACK ...
    description  TEXT,
    occurred_at  TIMESTAMPTZ,
    news_url     TEXT,                 -- 출처 뉴스
    symbol       TEXT,                 -- 영향 자산
    market       TEXT,
    direction    TEXT,                 -- '+' / '-'
    magnitude    NUMERIC,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- CDC: Debezium이 읽을 publication 생성
-- (pgoutput 플러그인 + 이 publication을 커넥터가 구독)
-- ============================================================
DROP PUBLICATION IF EXISTS fin_pub;
CREATE PUBLICATION fin_pub FOR TABLE assets, raw_news, price_bars, events;

-- UPDATE/DELETE 시 before 이미지를 풍부하게 받으려면 REPLICA IDENTITY FULL
ALTER TABLE assets     REPLICA IDENTITY FULL;
ALTER TABLE raw_news   REPLICA IDENTITY FULL;
ALTER TABLE price_bars REPLICA IDENTITY FULL;
ALTER TABLE events     REPLICA IDENTITY FULL;
