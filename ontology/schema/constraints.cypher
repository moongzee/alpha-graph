// ============================================================
// 금융 온톨로지 - 제약(Constraints) 및 인덱스(Index)
// Neo4j 5.x Cypher
// 적용: cypher-shell -f constraints.cypher  또는 ontology/load_schema.py
// ============================================================

// ---------- 유일성 제약 (Uniqueness) ----------
CREATE CONSTRAINT asset_symbol_market IF NOT EXISTS
FOR (a:Asset) REQUIRE (a.symbol, a.market) IS UNIQUE;

CREATE CONSTRAINT company_ticker IF NOT EXISTS
FOR (c:Company) REQUIRE c.ticker IS UNIQUE;

CREATE CONSTRAINT news_url IF NOT EXISTS
FOR (n:NewsArticle) REQUIRE n.url IS UNIQUE;

CREATE CONSTRAINT sector_name IF NOT EXISTS
FOR (s:Sector) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT exchange_mic IF NOT EXISTS
FOR (e:Exchange) REQUIRE e.mic IS UNIQUE;

CREATE CONSTRAINT topic_name IF NOT EXISTS
FOR (t:Topic) REQUIRE t.name IS UNIQUE;

CREATE CONSTRAINT event_id IF NOT EXISTS
FOR (ev:Event) REQUIRE ev.event_id IS UNIQUE;

// ---------- 존재성(스키마) 인덱스 ----------
CREATE INDEX news_published_at IF NOT EXISTS
FOR (n:NewsArticle) ON (n.published_at);

CREATE INDEX asset_type IF NOT EXISTS
FOR (a:Asset) ON (a.asset_type);

CREATE INDEX event_occurred_at IF NOT EXISTS
FOR (ev:Event) ON (ev.occurred_at);

// ---------- 풀텍스트 인덱스 (키워드 검색) ----------
CREATE FULLTEXT INDEX news_fulltext IF NOT EXISTS
FOR (n:NewsArticle) ON EACH [n.title, n.body];

// ---------- 벡터 인덱스 (의미 검색, 차원=임베딩 모델에 맞춤) ----------
// 예: text-embedding-3-small=1536, bge-m3=1024. 아래는 1536 가정.
CREATE VECTOR INDEX news_embedding IF NOT EXISTS
FOR (n:NewsArticle) ON (n.embedding)
OPTIONS { indexConfig: {
  `vector.dimensions`: 1536,
  `vector.similarity_function`: 'cosine'
}};
