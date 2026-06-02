"""에이전트 도구 모음.

각 도구는 `name`, `description`, `schema`(JSON-schema), `run(**kwargs)`를 갖는다.
LLM function-calling 스펙으로 직렬화 가능.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass
from typing import Any, Callable


# ---------------------------------------------------------------
# 읽기 전용 Cypher 가드 (Text2Cypher 안전장치)
# ---------------------------------------------------------------
_FORBIDDEN = re.compile(
    r"\b(CREATE|DELETE|DETACH|MERGE|SET|REMOVE|DROP|CALL\s+db\.|LOAD\s+CSV|FOREACH)\b",
    re.IGNORECASE,
)


def sanitize_cypher(cypher: str, default_limit: int = 50) -> str:
    if _FORBIDDEN.search(cypher):
        raise ValueError("읽기 전용 쿼리만 허용됩니다(쓰기/위험 키워드 감지).")
    if not re.search(r"\bLIMIT\b", cypher, re.IGNORECASE):
        cypher = cypher.rstrip().rstrip(";") + f"\nLIMIT {default_limit}"
    return cypher


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    run: Callable[..., Any]

    def to_openai_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }


# ---------------------------------------------------------------
# 도구 구현 (Neo4j / Postgres 핸들 주입)
# ---------------------------------------------------------------
class ToolRegistry:
    def __init__(self, neo4j_driver=None, pg_dsn: str | None = None, embedder=None):
        self.driver = neo4j_driver
        self.pg_dsn = pg_dsn or os.getenv("PG_DSN")
        self.embedder = embedder
        self._tools: dict[str, Tool] = {}
        self._register_all()

    # ---- public ----
    def specs(self) -> list[dict]:
        return [t.to_openai_spec() for t in self._tools.values()]

    def call(self, name: str, args: dict) -> Any:
        if name not in self._tools:
            return {"error": f"unknown tool: {name}"}
        try:
            return self._tools[name].run(**(args or {}))
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    # ---- registration ----
    def _register_all(self):
        self._tools["graph_query"] = Tool(
            name="graph_query",
            description="읽기 전용 Cypher로 지식 그래프를 조회한다.",
            schema={
                "type": "object",
                "properties": {"cypher": {"type": "string", "description": "읽기 전용 Cypher"}},
                "required": ["cypher"],
            },
            run=self._graph_query,
        )
        self._tools["vector_search"] = Tool(
            name="vector_search",
            description="질의문과 의미적으로 유사한 뉴스 top-k를 찾는다.",
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            run=self._vector_search,
        )
        self._tools["get_price"] = Tool(
            name="get_price",
            description="자산의 최근 시세와 변화율을 조회한다.",
            schema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "market": {"type": "string"},
                    "interval": {"type": "string", "default": "1d"},
                },
                "required": ["symbol", "market"],
            },
            run=self._get_price,
        )
        self._tools["compute_signal"] = Tool(
            name="compute_signal",
            description="감성·뉴스량·모멘텀·이벤트 신호를 합성해 설명가능한 점수를 만든다.",
            schema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "market": {"type": "string"},
                },
                "required": ["symbol", "market"],
            },
            run=self._compute_signal,
        )
        self._tools["list_assets"] = Tool(
            name="list_assets",
            description="조건에 맞는 자산 목록을 반환한다.",
            schema={
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string", "enum": ["STOCK", "CRYPTO"]},
                    "sector": {"type": "string"},
                },
            },
            run=self._list_assets,
        )

    # ---- impls ----
    def _graph_query(self, cypher: str) -> list[dict]:
        safe = sanitize_cypher(cypher)
        if self.driver is None:
            return [{"_note": "neo4j 미연결(스캐폴드)", "cypher": safe}]
        with self.driver.session() as s:
            return [r.data() for r in s.run(safe)]

    def _vector_search(self, query: str, k: int = 5) -> list[dict]:
        if self.driver is None or self.embedder is None:
            return [{"_note": "벡터검색 미연결(스캐폴드)", "query": query, "k": k}]
        vec = self.embedder.embed(query)
        cypher = """
        CALL db.index.vector.queryNodes('news_embedding', $k, $vec)
        YIELD node, score
        RETURN node.title AS title, node.url AS url,
               node.published_at AS published_at, score
        ORDER BY score DESC
        """
        with self.driver.session() as s:
            return [r.data() for r in s.run(cypher, {"k": k, "vec": vec})]

    def _get_price(self, symbol: str, market: str, interval: str = "1d") -> dict:
        if not self.pg_dsn:
            return {"_note": "postgres 미연결(스캐폴드)", "symbol": symbol}
        try:
            import psycopg
            with psycopg.connect(self.pg_dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ts, close FROM price_bars
                    WHERE symbol=%s AND market=%s AND interval=%s
                    ORDER BY ts DESC LIMIT 8
                    """,
                    (symbol, market, interval),
                )
                rows = cur.fetchall()
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        if not rows:
            return {"symbol": symbol, "note": "데이터 없음"}
        last = float(rows[0][1])
        prev = float(rows[-1][1])
        pct = round((last - prev) / prev * 100, 2) if prev else None
        return {
            "symbol": symbol, "market": market, "interval": interval,
            "last_close": last, "pct_change_window": pct,
            "as_of": str(rows[0][0]),
        }

    def _compute_signal(self, symbol: str, market: str) -> dict:
        """그래프 감성/뉴스량/이벤트 + 시세 모멘텀을 투명하게 합성."""
        senti = vol = event = 0.0
        if self.driver is not None:
            cypher = """
            MATCH (a:Asset {symbol:$symbol, market:$market})
            OPTIONAL MATCH (n:NewsArticle)-[:MENTIONS]->(a)
              WHERE n.published_at >= datetime() - duration('P7D')
            OPTIONAL MATCH (n)-[:HAS_SENTIMENT]->(s:Sentiment)
            OPTIONAL MATCH (ev:Event)-[af:AFFECTS]->(a)
              WHERE ev.occurred_at >= datetime() - duration('P7D')
            RETURN count(DISTINCT n) AS news_count,
                   avg(s.score) AS avg_sentiment,
                   sum(CASE af.direction WHEN '+' THEN af.magnitude
                            WHEN '-' THEN -af.magnitude ELSE 0 END) AS event_impact
            """
            with self.driver.session() as s:
                rec = s.run(cypher, {"symbol": symbol, "market": market}).single()
            if rec:
                senti = rec["avg_sentiment"] or 0.0
                vol = float(rec["news_count"] or 0)
                event = rec["event_impact"] or 0.0
        price = self._get_price(symbol, market)
        momentum = price.get("pct_change_window") or 0.0 if isinstance(price, dict) else 0.0

        # 투명한 가중합 (가중치는 설정 외부화 권장)
        w = {"sentiment": 1.0, "volume": 0.2, "momentum": 0.05, "event": 1.0}
        score = round(
            w["sentiment"] * senti
            + w["volume"] * min(vol, 10) / 10
            + w["momentum"] * momentum
            + w["event"] * event,
            3,
        )
        return {
            "symbol": symbol, "market": market, "signal_score": score,
            "components": {
                "avg_sentiment_7d": round(senti, 3),
                "news_volume_7d": vol,
                "price_momentum": momentum,
                "event_impact_7d": round(event, 3),
            },
            "note": "참고용 신호이며 매매 권유가 아님",
        }

    def _list_assets(self, asset_type: str | None = None, sector: str | None = None):
        if self.driver is None:
            return [{"_note": "neo4j 미연결(스캐폴드)"}]
        cypher = "MATCH (a:Asset) "
        where = []
        params: dict = {}
        if asset_type:
            where.append("a.asset_type=$at"); params["at"] = asset_type
        if sector:
            cypher += "MATCH (a)-[:ISSUED_BY]->(:Company)-[:IN_SECTOR]->(s:Sector {name:$sec}) "
            params["sec"] = sector
        if where:
            cypher += "WHERE " + " AND ".join(where) + " "
        cypher += "RETURN a.symbol AS symbol, a.market AS market, a.name AS name, a.asset_type AS type LIMIT 50"
        with self.driver.session() as s:
            return [r.data() for r in s.run(cypher, params)]
