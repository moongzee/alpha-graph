"""CDC 파이프라인 컨슈머: Kafka(Debezium) → 변환 → Neo4j.

사용:
    python pipeline/consumer/run.py

환경변수:
    KAFKA_BOOTSTRAP   (기본 localhost:9092)
    NEO4J_URI/USER/PASSWORD
    PG_DSN            (자산 별칭 사전 로딩용, 선택)

동작:
    1) Postgres에서 assets 별칭 사전 로딩(엔티티 해소용, 실패해도 진행)
    2) Debezium 토픽(fin.public.*) 구독
    3) 각 메시지 → GraphLoader로 멱등 적재
    4) at-least-once: 처리 성공 후 커밋
"""
from __future__ import annotations
import json
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from pipeline.transform.enrich import EntityResolver, SentimentAnalyzer, Embedder
from pipeline.transform.graph_loader import GraphLoader

TOPICS = [
    "fin.public.assets",
    "fin.public.raw_news",
    "fin.public.events",
    "fin.public.price_bars",
]
TABLE_FROM_TOPIC = {t: t.split(".")[-1] for t in TOPICS}


def load_alias_index() -> EntityResolver:
    dsn = os.getenv("PG_DSN", "postgresql://fin:fin@localhost:5432/findb")
    try:
        import psycopg
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT symbol, name, market, aliases FROM assets")
            assets = [
                {"symbol": r[0], "name": r[1], "market": r[2], "aliases": r[3]}
                for r in cur.fetchall()
            ]
        print(f"[*] 자산 별칭 사전 로딩: {len(assets)}건")
        return EntityResolver.from_assets(assets)
    except Exception as e:  # noqa: BLE001
        print(f"[!] 별칭 사전 로딩 실패({e}); 빈 사전으로 진행")
        return EntityResolver({})


def main() -> None:
    try:
        from confluent_kafka import Consumer
    except ImportError:
        sys.exit("confluent-kafka 필요:  pip install confluent-kafka")
    try:
        from neo4j import GraphDatabase
    except ImportError:
        sys.exit("neo4j 드라이버 필요:  pip install neo4j")

    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_pw = os.getenv("NEO4J_PASSWORD", "password")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pw))
    resolver = load_alias_index()
    loader = GraphLoader(driver, resolver, SentimentAnalyzer(), Embedder())

    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": "graph-loader",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,   # 수동 커밋(at-least-once)
    })
    consumer.subscribe(TOPICS)
    print(f"[*] 구독: {TOPICS}")
    print(f"[*] Neo4j: {neo4j_uri}  Kafka: {bootstrap}")

    running = True

    def _stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    processed = 0
    try:
        while running:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                print(f"[!] kafka error: {msg.error()}")
                continue
            try:
                payload = json.loads(msg.value()) if msg.value() else None
                if payload is None:  # tombstone
                    consumer.commit(msg)
                    continue

                # ExtractNewRecordState(unwrap) 적용 시: payload가 곧 row + __op 등
                op = payload.get("__op") or payload.get("op") or "c"
                table = (payload.get("__table")
                         or TABLE_FROM_TOPIC.get(msg.topic(), ""))
                # unwrap 모드에서는 payload 자체가 after 행
                after = None if op == "d" else {
                    k: v for k, v in payload.items() if not k.startswith("__")
                }
                before = payload if op == "d" else None

                loader.handle(table, op, after, before)
                consumer.commit(msg)        # 성공 후 커밋
                processed += 1
                if processed % 50 == 0:
                    print(f"[*] 처리 {processed}건")
            except Exception as e:  # noqa: BLE001
                # 운영: DLQ 토픽으로 전송 후 커밋. 스캐폴드: 로그만.
                print(f"[!] 처리 실패(topic={msg.topic()}): {e}")
                consumer.commit(msg)
    finally:
        consumer.close()
        driver.close()
        print(f"[done] 총 {processed}건 처리, 종료")


if __name__ == "__main__":
    main()
