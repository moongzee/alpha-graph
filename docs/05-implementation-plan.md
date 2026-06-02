# 05. 단계별 구현 계획

목표를 한 번에 다 만들지 않고 **수직 슬라이스**로 쪼개 "끝까지 동작하는 얇은 경로"부터 만든다.

## 마일스톤 개요

| 단계 | 목표 | 산출물 | 검증 |
|------|------|--------|------|
| M0 | 인프라 기동 | docker-compose | 4개 컨테이너 health |
| M1 | 온톨로지 스키마 | constraints/ontology.cypher | 제약·인덱스 생성 확인 |
| M2 | CDC E2E(수동) | schema.sql + Debezium | Postgres INSERT → Kafka 토픽에 이벤트 |
| M3 | 그래프 적재 | consumer + graph_loader | raw_news INSERT → Neo4j 노드 생성 |
| M4 | 수집기 | scraper + price | RSS/시세 → Postgres → (CDC) → 그래프 |
| M5 | 에이전트 기본 | agent(stub) | 질문 → 도구호출 → 근거 답변 |
| M6 | 에이전트 고도화 | 실 LLM + 신호 합성 | 추천 신호 + 근거 인용 + 면책 |
| M7 | 품질/운영 | 엔티티해소·감성 모델 교체, 관측성 | 정확도/지연 대시보드 |

---

## M0. 인프라
```bash
docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml ps   # 모두 healthy 확인
```
검증: `localhost:7474`(Neo4j), `localhost:8083/connectors`(Connect) 응답.

## M1. 온톨로지
```bash
pip install -r requirements.txt
NEO4J_PASSWORD=password python ontology/load_schema.py --examples
```
검증(Neo4j 브라우저): `SHOW CONSTRAINTS;` / `MATCH (n) RETURN labels(n), count(*)`.

## M2. CDC 파이프라인(원천→Kafka)
```bash
# 원천 스키마 + publication
psql "postgresql://fin:fin@localhost:5432/findb" -f ingestion/db/schema.sql
# Debezium 커넥터 등록
bash cdc/register-connectors.sh
```
검증: Postgres에 INSERT 후, Kafka 토픽 `fin.public.raw_news`에 메시지 도착
(`kafka-console-consumer` 또는 Connect status `RUNNING`).

## M3. 그래프 적재(Kafka→Neo4j)
```bash
NEO4J_PASSWORD=password python pipeline/consumer/run.py
```
검증: Postgres `raw_news` INSERT → 수 초 내 Neo4j에 `(:NewsArticle)` 생성,
`(:NewsArticle)-[:MENTIONS]->(:Asset)` 연결.

## M4. 수집기 가동
```bash
# 자산 마스터 먼저(엔티티 해소 사전)
psql ... -c "INSERT INTO assets(symbol,name,asset_type,market,aliases) VALUES
  ('005930','삼성전자','STOCK','KRX', ARRAY['Samsung','삼전']),
  ('BTC','Bitcoin','CRYPTO','Binance', ARRAY['비트코인','비트']);"
python ingestion/scrapers/run_news.py
python ingestion/market/run_prices.py
```
검증: 그래프에서 뉴스가 올바른 자산에 링킹되는지(`MENTIONS.confidence`).

## M5~M6. 에이전트
```bash
# 데모(키 없이)
NEO4J_URI=bolt://localhost:7687 NEO4J_PASSWORD=password \
  python agent/main.py "최근 호재가 많은 코인 알려줘"
# 실 LLM
export OPENAI_API_KEY=...   # 또는 ANTHROPIC_API_KEY
python agent/main.py "반도체 섹터에서 신호 좋은 종목은?"
```
검증: 답변에 (1)근거 인용 (2)신호 구성요소 (3)면책 고지 포함.

## M7. 품질/운영 고도화
- **엔티티 해소**: 사전 → NER+임베딩 fallback, confidence 임계 검수 큐.
- **감성**: rule-stub → FinBERT(한/영) 교체.
- **임베딩**: hash-stub → 실 임베딩 모델, 차원 맞춰 벡터 인덱스 재생성.
- **이벤트 추출**: 규칙/LLM으로 `events` 테이블 채우기.
- **관측성**: consumer lag, 적재 실패율, confidence 분포 대시보드(Prometheus/Grafana).
- **백필**: 과거 뉴스 일괄 적재 시 Debezium snapshot 또는 배치 로더.

---

## 테스트 전략
- **단위**: `enrich.py`(해소/감성/임베딩), `sanitize_cypher`(쓰기 차단) → 순수 함수라 키 없이 테스트.
- **통합**: docker-compose 띄우고 Postgres INSERT→Neo4j 노드 생성 어서션.
- **에이전트**: StubClient로 도구 호출 경로 검증(LLM 비결정성 제거).

## 리스크 & 대응
| 리스크 | 대응 |
|--------|------|
| 스크래핑 법적/차단 | 공식 RSS/API 우선, robots 준수, rate limit |
| 엔티티 오링킹 | confidence 임계 + 검수 큐 + 짧은 별칭 감점 |
| LLM 환각/자문 리스크 | 근거 강제·면책·읽기전용 Cypher·정보제공형 표현 |
| CDC 슬롯 적체 | replication slot 모니터링, 컨슈머 상시 가동 |
