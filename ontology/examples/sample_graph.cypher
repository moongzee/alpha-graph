// ============================================================
// 예시 데이터 (데모/테스트용) - 온톨로지 구조 시연
// ============================================================

// --- 섹터/거래소는 ontology.cypher에서 시드됨 ---

// --- 기업 + 자산(주식) ---
MERGE (samsung:Company {ticker:'005930'})
  SET samsung.name='삼성전자', samsung.country='KR', samsung.market_cap=400000000000;
MERGE (semi:Sector {name:'Semiconductors'});
MERGE (samsung)-[:IN_SECTOR]->(semi);

MERGE (krx:Exchange {mic:'XKRX'});
MERGE (a1:Asset {symbol:'005930', market:'KRX'})
  SET a1.name='삼성전자', a1.asset_type='STOCK', a1.currency='KRW';
MERGE (a1)-[:ISSUED_BY]->(samsung);
MERGE (a1)-[:LISTED_ON]->(krx);

// --- 자산(코인) ---
MERGE (bn:Exchange {mic:'BINA'});
MERGE (btc:Asset {symbol:'BTC', market:'Binance'})
  SET btc.name='Bitcoin', btc.asset_type='CRYPTO', btc.currency='USDT';
MERGE (btc)-[:LISTED_ON]->(bn);
MERGE (crypsec:Sector {name:'CryptoInfra'});

// --- 뉴스 + 감성 + 이벤트 + 언급 ---
MERGE (n1:NewsArticle {url:'https://example.com/news/1'})
  SET n1.title='삼성전자, HBM 차세대 양산 본격화',
      n1.body='삼성전자가 차세대 HBM 메모리 양산을 시작했다...',
      n1.source='ExampleWire', n1.lang='ko',
      n1.published_at=datetime('2026-05-28T09:00:00Z');
MERGE (s1:Sentiment {label:'POS'}) SET s1.score=0.82, s1.model='finbert-ko';
MERGE (n1)-[:HAS_SENTIMENT]->(s1);
MERGE (n1)-[:MENTIONS {confidence:0.97}]->(a1);
MERGE (ev1:Event {event_id:'evt-1'})
  SET ev1.type='PRODUCT_LAUNCH', ev1.occurred_at=datetime('2026-05-28T00:00:00Z'),
      ev1.description='HBM 차세대 양산 개시';
MERGE (n1)-[:DESCRIBES]->(ev1);
MERGE (ev1)-[:AFFECTS {direction:'+', magnitude:0.6}]->(a1);

MERGE (n2:NewsArticle {url:'https://example.com/news/2'})
  SET n2.title='비트코인 ETF 자금 유입 가속',
      n2.body='기관 자금이 비트코인 현물 ETF로 유입되며...',
      n2.source='CryptoDaily', n2.lang='ko',
      n2.published_at=datetime('2026-05-30T12:00:00Z');
MERGE (s2:Sentiment {label:'POS'}) SET s2.score=0.75, s2.model='finbert-en';
MERGE (n2)-[:HAS_SENTIMENT]->(s2);
MERGE (n2)-[:MENTIONS {confidence:0.95}]->(btc);

// --- 가격 요약(원시 시계열은 Postgres, 그래프엔 요약만) ---
MERGE (ps1:PriceSummary {asset_symbol:'BTC', interval:'1d'})
  SET ps1.last_close=68000, ps1.pct_change_7d=4.2, ps1.updated_at=datetime();
MERGE (btc)-[:HAS_PRICE_SUMMARY {interval:'1d'}]->(ps1);
