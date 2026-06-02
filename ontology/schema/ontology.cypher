// ============================================================
// 금융 온톨로지 - 클래스/관계 메타 정의 (문서화 목적의 시드)
// 실제 인스턴스는 파이프라인이 MERGE로 생성한다.
// 이 파일은 "온톨로지가 무엇을 표현하는가"를 그래프 안에 메타로 남긴다.
// ============================================================

// ---------- 메타: 클래스 카탈로그 ----------
MERGE (m:OntologyMeta {key: 'catalog'})
SET m.version = '1.0.0',
    m.updated_at = datetime(),
    m.classes = [
      'Asset','Company','Sector','Exchange',
      'NewsArticle','Event','Sentiment','PriceSummary','Topic'
    ],
    m.relationships = [
      'ISSUED_BY','IN_SECTOR','LISTED_ON','COMPETES_WITH',
      'MENTIONS','ABOUT_TOPIC','HAS_SENTIMENT','DESCRIBES',
      'AFFECTS','HAS_PRICE_SUMMARY'
    ];

// ---------- 메타: 관계 시그니처(에이전트 Text2Cypher 힌트) ----------
MERGE (r1:RelMeta {name:'MENTIONS'})
  SET r1.from='NewsArticle', r1.to='Asset|Company', r1.props='confidence:float';
MERGE (r2:RelMeta {name:'AFFECTS'})
  SET r2.from='Event', r2.to='Asset', r2.props='direction:string(+/-), magnitude:float';
MERGE (r3:RelMeta {name:'HAS_SENTIMENT'})
  SET r3.from='NewsArticle', r3.to='Sentiment', r3.props='-';
MERGE (r4:RelMeta {name:'IN_SECTOR'})
  SET r4.from='Company', r4.to='Sector', r4.props='-';

// ---------- 시드: 표준 섹터(예시) ----------
UNWIND [
  {name:'Semiconductors', code:'SEMI'},
  {name:'Banking', code:'BANK'},
  {name:'Internet', code:'INET'},
  {name:'Automotive', code:'AUTO'},
  {name:'CryptoInfra', code:'CRYP'}
] AS s
MERGE (:Sector {name: s.name}) ;

// ---------- 시드: 주요 거래소(예시) ----------
UNWIND [
  {name:'KRX', mic:'XKRX', country:'KR'},
  {name:'NASDAQ', mic:'XNAS', country:'US'},
  {name:'Binance', mic:'BINA', country:'GLOBAL'},
  {name:'Upbit', mic:'UPBT', country:'KR'}
] AS e
MERGE (:Exchange {mic: e.mic}) SET e += e ;
