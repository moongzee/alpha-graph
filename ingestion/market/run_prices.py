"""시세 수집 스타터.

거래소/증권 API에서 OHLCV를 받아 Postgres price_bars에 멱등 UPSERT한다.
CDC가 이를 PriceSummary로 그래프에 전파한다.

사용:
    python ingestion/market/run_prices.py

환경변수:
    PG_DSN
    PRICE_SYMBOLS  예: "BTC:Binance:CRYPTO,005930:KRX:STOCK"

데이터 소스:
    - 코인: ccxt (거래소 통합)  ─ pip install ccxt
    - 주식: yfinance 등          ─ pip install yfinance
  미설치/미설정 시 샘플 데이터를 생성해 흐름을 시연한다.
"""
from __future__ import annotations
import os
import sys
import random
import datetime as dt


UPSERT = """
INSERT INTO price_bars (symbol, market, interval, ts, open, high, low, close, volume)
VALUES (%(symbol)s, %(market)s, %(interval)s, %(ts)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
ON CONFLICT (symbol, market, interval, ts) DO UPDATE
SET close=EXCLUDED.close, high=EXCLUDED.high, low=EXCLUDED.low,
    open=EXCLUDED.open, volume=EXCLUDED.volume
"""


def parse_symbols() -> list[tuple[str, str, str]]:
    raw = os.getenv("PRICE_SYMBOLS", "BTC:Binance:CRYPTO,005930:KRX:STOCK")
    out = []
    for tok in raw.split(","):
        parts = tok.split(":")
        if len(parts) >= 2:
            sym, market = parts[0], parts[1]
            atype = parts[2] if len(parts) > 2 else "CRYPTO"
            out.append((sym.strip(), market.strip(), atype.strip()))
    return out


def fetch_crypto_ccxt(symbol: str, market: str) -> list[dict]:
    try:
        import ccxt
    except ImportError:
        return []
    try:
        ex = getattr(ccxt, market.lower())()
        ohlcv = ex.fetch_ohlcv(f"{symbol}/USDT", timeframe="1d", limit=8)
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for ts, o, h, l, c, v in ohlcv:
        rows.append({
            "symbol": symbol, "market": market, "interval": "1d",
            "ts": dt.datetime.utcfromtimestamp(ts / 1000).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": v,
        })
    return rows


def fake_series(symbol: str, market: str) -> list[dict]:
    """데모용 가짜 시계열(연결 안 될 때)."""
    base = random.uniform(100, 1000)
    rows = []
    now = dt.datetime.utcnow()
    for i in range(8):
        base *= random.uniform(0.98, 1.03)
        rows.append({
            "symbol": symbol, "market": market, "interval": "1d",
            "ts": (now - dt.timedelta(days=7 - i)).isoformat(),
            "open": round(base * 0.99, 2), "high": round(base * 1.02, 2),
            "low": round(base * 0.97, 2), "close": round(base, 2),
            "volume": round(random.uniform(1e5, 1e6), 0),
        })
    return rows


def upsert(rows: list[dict], dsn: str) -> int:
    if not rows:
        return 0
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.executemany(UPSERT, rows)
        conn.commit()
    return len(rows)


def main() -> None:
    dsn = os.getenv("PG_DSN", "postgresql://fin:***@localhost:5432/findb")
    total = 0
    for sym, market, atype in parse_symbols():
        rows = []
        if atype == "CRYPTO":
            rows = fetch_crypto_ccxt(sym, market)
        if not rows:
            print(f"[*] {sym}:{market} 실데이터 없음 → 데모 시계열 생성")
            rows = fake_series(sym, market)
        try:
            total += upsert(rows, dsn)
            print(f"[*] {sym}:{market} price_bars {len(rows)}건 적재")
        except Exception as e:  # noqa: BLE001
            print(f"[!] 적재 실패({e})"); sys.exit(1)
    print(f"[done] 총 {total}건 → CDC가 PriceSummary로 전파합니다.")


if __name__ == "__main__":
    main()
