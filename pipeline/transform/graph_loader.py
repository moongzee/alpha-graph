"""그래프 적재 모듈: Debezium 이벤트 → 멱등 Cypher MERGE.

각 핸들러는 테이블별 변경 이벤트를 받아 Neo4j에 upsert한다.
모든 쿼리는 MERGE 기반이라 at-least-once 중복 전달에도 안전(멱등).
"""
from __future__ import annotations
from typing import Any


class GraphLoader:
    def __init__(self, driver, resolver, sentiment, embedder):
        self.driver = driver
        self.resolver = resolver
        self.sentiment = sentiment
        self.embedder = embedder

    # ---- 라우터 ----
    def handle(self, table: str, op: str, after: dict[str, Any] | None,
               before: dict[str, Any] | None) -> None:
        if op == "d":  # delete
            self._handle_delete(table, before or after or {})
            return
        if after is None:
            return
        if table == "assets":
            self._upsert_asset(after)
        elif table == "raw_news":
            self._upsert_news(after)
        elif table == "events":
            self._upsert_event(after)
        elif table == "price_bars":
            self._update_price_summary(after)

    # ---- assets ----
    def _upsert_asset(self, row: dict) -> None:
        cypher = """
        MERGE (a:Asset {symbol:$symbol, market:$market})
        SET a.name=$name, a.asset_type=$asset_type, a.currency=$currency
        WITH a
        FOREACH (_ IN CASE WHEN $sector IS NULL THEN [] ELSE [1] END |
          MERGE (s:Sector {name:$sector})
          MERGE (a)-[:IN_SECTOR_VIA_COMPANY]->(s)
        )
        """
        self._run(cypher, {
            "symbol": row["symbol"], "market": row["market"],
            "name": row.get("name"), "asset_type": row.get("asset_type"),
            "currency": row.get("currency"), "sector": row.get("sector"),
        })

    # ---- raw_news (핵심) ----
    def _upsert_news(self, row: dict) -> None:
        text = f"{row.get('title','')} {row.get('body','')}"
        mentions = self.resolver.resolve(text)
        senti = self.sentiment.analyze(text)
        embedding = self.embedder.embed(text)

        cypher = """
        MERGE (n:NewsArticle {url:$url})
        SET n.title=$title, n.body=$body, n.source=$source, n.lang=$lang,
            n.published_at = CASE WHEN $published_at IS NULL THEN n.published_at
                                  ELSE datetime($published_at) END,
            n.embedding=$embedding
        MERGE (sent:Sentiment {label:$slabel})
        SET sent.score=$sscore, sent.model=$smodel
        MERGE (n)-[:HAS_SENTIMENT]->(sent)
        WITH n
        UNWIND $mentions AS m
          MATCH (a:Asset {symbol:m.symbol, market:m.market})
          MERGE (n)-[r:MENTIONS]->(a)
          SET r.confidence = m.confidence
        """
        self._run(cypher, {
            "url": row["url"], "title": row.get("title"), "body": row.get("body"),
            "source": row.get("source"), "lang": row.get("lang"),
            "published_at": row.get("published_at"),
            "embedding": embedding,
            "slabel": senti.label, "sscore": senti.score, "smodel": senti.model,
            "mentions": [vars(m) for m in mentions],
        })

    # ---- events ----
    def _upsert_event(self, row: dict) -> None:
        cypher = """
        MERGE (ev:Event {event_id:$event_id})
        SET ev.type=$type, ev.description=$description,
            ev.occurred_at = CASE WHEN $occurred_at IS NULL THEN ev.occurred_at
                                  ELSE datetime($occurred_at) END
        WITH ev
        FOREACH (_ IN CASE WHEN $symbol IS NULL THEN [] ELSE [1] END |
          MERGE (a:Asset {symbol:$symbol, market:$market})
          MERGE (ev)-[af:AFFECTS]->(a)
          SET af.direction=$direction, af.magnitude=$magnitude
        )
        WITH ev
        FOREACH (_ IN CASE WHEN $news_url IS NULL THEN [] ELSE [1] END |
          MERGE (n:NewsArticle {url:$news_url})
          MERGE (n)-[:DESCRIBES]->(ev)
        )
        """
        self._run(cypher, {
            "event_id": row["event_id"], "type": row.get("type"),
            "description": row.get("description"), "occurred_at": row.get("occurred_at"),
            "symbol": row.get("symbol"), "market": row.get("market"),
            "direction": row.get("direction"), "magnitude": row.get("magnitude"),
            "news_url": row.get("news_url"),
        })

    # ---- price_bars → 그래프엔 요약만 ----
    def _update_price_summary(self, row: dict) -> None:
        cypher = """
        MATCH (a:Asset {symbol:$symbol, market:$market})
        MERGE (ps:PriceSummary {asset_symbol:$symbol, interval:$interval})
        SET ps.last_close=$close, ps.last_ts=datetime($ts), ps.updated_at=datetime()
        MERGE (a)-[:HAS_PRICE_SUMMARY {interval:$interval}]->(ps)
        """
        self._run(cypher, {
            "symbol": row["symbol"], "market": row["market"],
            "interval": row.get("interval"), "close": row.get("close"),
            "ts": row.get("ts"),
        })

    # ---- delete ----
    def _handle_delete(self, table: str, row: dict) -> None:
        if table == "raw_news" and row.get("url"):
            self._run("MATCH (n:NewsArticle {url:$url}) DETACH DELETE n",
                      {"url": row["url"]})

    # ---- helper ----
    def _run(self, cypher: str, params: dict) -> None:
        with self.driver.session() as s:
            s.run(cypher, params)
