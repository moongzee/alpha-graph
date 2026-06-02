# 03. CDC 실시간 파이프라인 설계

## 1. CDC(Change Data Capture)란

원천 DB의 **변경(INSERT/UPDATE/DELETE)**을 **트랜잭션 로그(WAL)** 수준에서 포착해 다운스트림으로 전달하는 기법.

| 방식 | 동작 | 단점 |
|------|------|------|
| 폴링(쿼리 기반) | `WHERE updated_at > last` 반복 조회 | 부하↑, 지연↑, DELETE 감지 불가 |
| 트리거 기반 | DB 트리거로 변경 테이블 기록 | 쓰기 성능 저하, 침습적 |
| **로그 기반(CDC)** | WAL/binlog 파싱 | **저부하, 순서보장, DELETE 포함** ✅ |

→ 본 설계는 **로그 기반 CDC = Debezium**을 사용한다.

## 2. 이 도메인에서 CDC가 필요한 이유

스크래퍼/시세 수집기는 데이터를 **Postgres(staging)**에 넣는다. 이를 그래프로 옮기는 방법 후보:

1. 스크래퍼가 직접 Neo4j에도 쓰기 → 수집기와 적재 로직이 강결합, 장애 전파, 재처리 불가.
2. 배치로 주기적 폴링 → 지연, 중복, DELETE 누락.
3. **CDC** → 수집/적재 분리, 실시간, 재처리 가능, 다중 컨슈머 확장. ✅

## 3. 파이프라인 토폴로지

```
Postgres(WAL)
   │  pgoutput plugin / publication
   ▼
Debezium Source Connector (Kafka Connect)
   │  변경 이벤트(JSON, before/after/op)
   ▼
Kafka Topics:  fin.public.raw_news
               fin.public.price_bars
               fin.public.events
               fin.public.assets
   ▼
Pipeline Consumer (consumer group: graph-loader)
   ├─ raw_news   → 엔티티해소 + 감성 + 임베딩 → Cypher MERGE
   ├─ assets     → Asset/Company/Sector upsert
   ├─ events     → Event + AFFECTS
   └─ price_bars → PriceSummary 갱신(원시는 Postgres 유지)
   ▼
Neo4j
```

## 4. Debezium 이벤트 구조 (핵심)

각 변경은 아래 형태로 온다(`after`가 새 행, `op`는 c=create, u=update, d=delete).

```json
{
  "op": "c",
  "ts_ms": 1717000000000,
  "before": null,
  "after": {
    "id": 1024,
    "url": "https://.../news/abc",
    "title": "삼성전자 HBM 양산",
    "body": "...",
    "source": "ExampleWire",
    "published_at": "2026-05-28T09:00:00Z",
    "lang": "ko"
  },
  "source": { "table": "raw_news", "lsn": 987654321 }
}
```

컨슈머는 `op`에 따라 분기:
- `c`/`r`(스냅샷)/`u` → 그래프에 **MERGE(upsert)**.
- `d` → 그래프 노드/관계 **soft-delete 또는 detach delete**(뉴스 철회 등).

## 5. 변환 단계 (Consumer 내부) — 파이프라인의 핵심

```
[Debezium event]
  └─► 1. 역직렬화 + 스키마 검증
  └─► 2. 라우팅 (table → handler)
  └─► 3-A. (raw_news) 엔티티 해소
            - 사전 매칭(assets.alias) → 후보
            - NER → 임베딩 최근접 → confidence
  └─► 3-B. (raw_news) 감성분석 (FinBERT 류)
  └─► 3-C. (raw_news) 임베딩 생성 (의미검색용)
  └─► 3-D. (raw_news) 이벤트 추출 (선택: LLM/규칙)
  └─► 4. 멱등 Cypher MERGE 적재
  └─► 5. offset commit (at-least-once)
```

### 멱등성(Idempotency)이 핵심
at-least-once 전달이므로 **같은 이벤트가 두 번 와도 결과가 같아야** 한다.
→ 모든 적재는 `MERGE`(있으면 갱신, 없으면 생성) + 자연키(url, symbol) 사용.
→ 중복 처리해도 그래프 상태 불변 ⇒ 안전.

```cypher
MERGE (n:NewsArticle {url: $url})
SET n.title=$title, n.body=$body, n.published_at=datetime($published_at),
    n.source=$source, n.lang=$lang
WITH n
UNWIND $mentions AS m
  MATCH (a:Asset {symbol:m.symbol, market:m.market})
  MERGE (n)-[r:MENTIONS]->(a)
  SET r.confidence = m.confidence
```

## 6. 일관성·신뢰성 보장

| 위험 | 대응 |
|------|------|
| 컨슈머 다운 중 메시지 유실 | Kafka 보존 + offset 커밋으로 재시작 시 이어처리 |
| 중복 전달 | 멱등 MERGE |
| 순서 뒤바뀜 | 토픽 파티션 키 = 자연키(같은 뉴스는 같은 파티션 → 순서보장) |
| 부분 실패(감성은 됐는데 적재 실패) | 단위 트랜잭션 + DLQ(dead-letter-topic)로 격리 후 재처리 |
| 스키마 변경 | Schema Registry(선택) 또는 컨슈머의 관대한 파싱 |

## 7. 백프레셔·스케일링

- **수평 확장**: 컨슈머를 같은 group으로 N개 실행 → 파티션 분산.
- **무거운 작업 분리**: 임베딩/LLM 이벤트추출은 별도 컨슈머 그룹으로 떼어내 독립 스케일.
- **파티션 수** ≥ 최대 컨슈머 수.

## 8. 운영 관측성

- Kafka Connect 상태: `GET /connectors/<name>/status`
- consumer lag 모니터링(밀리지 않는지)
- 적재 실패율, DLQ 적재량, 엔티티해소 confidence 분포 대시보드

## 파일
- `infra/docker-compose.yml` — Postgres/Kafka/Connect/Neo4j 기동
- `ingestion/db/schema.sql` — 원천 테이블 + publication(CDC 소스)
- `cdc/debezium/postgres-source.json` — Debezium 커넥터 설정
- `cdc/register-connectors.sh` — 커넥터 등록 스크립트
- `pipeline/consumer/run.py` — Kafka→Neo4j 컨슈머
- `pipeline/transform/*` — 엔티티해소/감성/적재 변환 모듈
