# 02. 온톨로지 데이터 설계

## 1. 온톨로지란, 그리고 여기서의 의미

온톨로지는 도메인의 **개념(클래스)**, **관계**, **속성**, **제약**을 명시한 형식적 모델이다. 단순 테이블 스키마와 다른 점:

- **관계가 1급 시민**: "뉴스가 종목을 언급한다", "종목이 섹터에 속한다"가 데이터로 명시됨.
- **추론 가능**: "A기업이 B섹터, B섹터에 악재 → A에 잠재 영향" 같은 전이적 추론.
- **의미 부여**: LLM이 "이 노드는 코인이고, 이 엣지는 호재 뉴스"라는 의미를 안다.

> 본 설계는 운영 효율을 위해 **Property Graph(Neo4j)**를 1차 저장소로 쓰고, 엄밀한 형식 의미론이 필요할 때 **RDF/OWL/SHACL**로 내보낼 수 있는 하이브리드 전략을 택한다.

## 2. 핵심 클래스 (노드 라벨)

| 클래스 | 설명 | 핵심 속성 |
|--------|------|-----------|
| `Asset` | 거래 대상 자산(주식/코인 통합 추상) | `symbol, name, asset_type(STOCK/CRYPTO), market, currency` |
| `Company` | 발행 기업(주식에 한함) | `name, ticker, country, market_cap` |
| `Sector` | 산업/섹터 분류 | `name, code` |
| `Exchange` | 거래소/시장 | `name, mic, country` |
| `NewsArticle` | 뉴스 기사 | `url(unique), title, body, published_at, source, lang, embedding` |
| `Event` | 추출된 이벤트(실적/규제/상장/해킹 등) | `type, occurred_at, description` |
| `Sentiment` | 감성 분석 결과 | `label(POS/NEG/NEU), score, model` |
| `PriceBar` | OHLCV 시계열 한 단위 | `ts, open, high, low, close, volume, interval` |
| `Topic` | 뉴스 토픽/키워드 | `name` |

> **설계 결정**: `PriceBar` 같은 고빈도 시계열은 그래프에 **전부 넣지 않는다.** 그래프에는 "관계/요약"만, 원시 시계열은 Postgres(또는 시계열 DB)에 두고 에이전트가 `get_price` 도구로 직접 조회. 그래프 비대화를 방지.

## 3. 핵심 관계 (엣지 타입)

```
(:Asset)-[:ISSUED_BY]->(:Company)
(:Company)-[:IN_SECTOR]->(:Sector)
(:Asset)-[:LISTED_ON]->(:Exchange)
(:Asset)-[:COMPETES_WITH]->(:Asset)
(:NewsArticle)-[:MENTIONS {confidence}]->(:Asset)
(:NewsArticle)-[:MENTIONS {confidence}]->(:Company)
(:NewsArticle)-[:ABOUT_TOPIC]->(:Topic)
(:NewsArticle)-[:HAS_SENTIMENT]->(:Sentiment)
(:NewsArticle)-[:DESCRIBES]->(:Event)
(:Event)-[:AFFECTS {direction, magnitude}]->(:Asset)
(:Asset)-[:HAS_PRICE_SUMMARY {interval}]->(:PriceSummary)
```

### 관계 설계 원칙
- `MENTIONS`에 `confidence`를 둬서 **엔티티 링킹 신뢰도**를 보존(에이전트가 임계값으로 필터 가능).
- `AFFECTS`에 `direction(+/-)`, `magnitude`를 둬서 **영향 방향성**을 표현 → 추천 신호의 핵심 입력.
- 경쟁/섹터 관계로 **2차 영향 전파**("경쟁사 악재 → 반사 수혜") 추론 가능.

## 4. 온톨로지 다이어그램 (개념)

```
        ┌─────────┐  IN_SECTOR   ┌────────┐
        │ Company ├─────────────►│ Sector │
        └────▲────┘              └────────┘
   ISSUED_BY │
        ┌────┴────┐  LISTED_ON   ┌──────────┐
        │  Asset  ├─────────────►│ Exchange │
        └────▲────┘              └──────────┘
   MENTIONS  │  AFFECTS
        ┌────┴───────┐  HAS_SENTIMENT  ┌───────────┐
        │ NewsArticle├────────────────►│ Sentiment │
        └────┬───────┘                 └───────────┘
   DESCRIBES │
        ┌────▼────┐
        │  Event  │
        └─────────┘
```

## 5. 제약·인덱스 (데이터 무결성)

Neo4j 제약으로 온톨로지 규칙을 강제한다(상세 Cypher: `ontology/schema/constraints.cypher`).

- **유일성**: `Asset.symbol+market`, `NewsArticle.url`, `Company.ticker`.
- **존재성(엔터프라이즈)**: `NewsArticle.published_at` 필수.
- **벡터 인덱스**: `NewsArticle.embedding` (의미 검색용).
- **풀텍스트 인덱스**: `NewsArticle.title, body` (키워드 검색).

## 6. 엔티티 해소(Entity Resolution) 전략

뉴스 본문의 "삼성전자", "Samsung Electronics", "005930"을 **하나의 `Asset`/`Company`로 링킹**해야 그래프가 의미를 가진다.

1. **사전 기반(우선)**: `assets`/`companies` 테이블의 별칭(alias) 사전으로 1차 매칭.
2. **NER + 임베딩 유사도**: 사전에 없으면 NER로 후보 추출 후 임베딩 최근접으로 링킹, `confidence` 기록.
3. **휴먼인더루프(선택)**: confidence < 임계값이면 검수 큐로.

> 이 단계가 파이프라인 품질의 80%를 좌우한다. 상세는 `docs/03` §변환 단계 참조.

## 7. 저장소 선택 근거: Property Graph vs RDF

| 기준 | Neo4j(Property Graph) | RDF/SPARQL |
|------|------------------------|------------|
| 개발 속도 | 빠름(Cypher 직관적) | 느림(엄격) |
| 형식 추론 | 제한적 | 강력(OWL reasoner) |
| 운영 생태계 | 풍부 | 상대적으로 좁음 |
| 벡터/풀텍스트 | 내장 | 별도 |

→ **실시간 + 추천 + LLM 통합**이 목적이므로 Neo4j 채택. 규제·표준 상호운용이 필요해지면 SHACL/OWL로 내보내는 어댑터를 추가(`ontology/schema/shapes.ttl` 자리 예약).

## 8. 진화 전략 (스키마 버저닝)

- 노드에 `_schema_version` 속성을 두고, 마이그레이션은 `ontology/migrations/`에 Cypher로 누적.
- 라벨/속성 **추가는 자유**, **제거/이름변경은 마이그레이션 필수**(LLM 프롬프트의 스키마 설명과 동기화).
- 에이전트는 시작 시 `CALL db.schema.visualization()`으로 **실제 스키마를 읽어** 프롬프트에 주입(스키마 드리프트 방지).

## 파일
- `ontology/schema/constraints.cypher` — 제약·인덱스 정의
- `ontology/schema/ontology.cypher` — 시드 클래스/관계 메타
- `ontology/examples/sample_graph.cypher` — 예시 데이터
- `ontology/load_schema.py` — 스키마 적재 스크립트
