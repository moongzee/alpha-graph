# 금융 인텔리전스 플랫폼: Ontology + CDC 실시간 파이프라인 + LLM 에이전트

> 도메인: **금융 (뉴스 스크래핑 + 코인/주식 종목 정보 제공·추천)**

뉴스와 시세를 실시간으로 수집해 **지식 그래프(온톨로지)**로 구조화하고, 그 위에서 **LLM 에이전트**가 근거 기반으로 종목 인사이트를 제공하는 레퍼런스 설계입니다.

```
[뉴스 스크래퍼]   ┐
[시세/시장 API]   ├─► [원천 DB(Postgres)] ──(CDC/Debezium)──► [Kafka] ──(변환)──► [Neo4j 지식그래프]
[공시/이벤트]     ┘                                                                     │
                                                                                  (질의/추론)
                                                                                        │
                                              사용자 ◄──►  [LLM 에이전트(Tool-calling)]
```

---

## 세 개의 축

### 1. 온톨로지 데이터 설계
금융 도메인의 개념과 관계를 그래프로 모델링한다.
`Asset(주식/코인) ↔ Company ↔ Sector ↔ NewsArticle ↔ Event ↔ Sentiment ↔ PriceBar`
→ "삼성전자 주가가 왜 움직였는가?"를 **뉴스·이벤트·섹터 연관관계로 설명**할 수 있게 만든다.

### 2. CDC 실시간 파이프라인
스크래퍼와 시세 수집기가 원천 DB(Postgres)에 적재하면, **Debezium**이 WAL(로그)을 캡처해 폴링 없이 변경분만 Kafka로 흘려보낸다. 컨슈머가 이를 **온톨로지 그래프로 변환·적재**한다.
→ 새 뉴스가 들어오면 **수 초 내**에 그래프와 에이전트의 지식이 갱신된다.

### 3. LLM 에이전트
온톨로지를 도구(tool)로 삼아 자연어 질문에 답한다. **Text2Cypher**(자연어→그래프 질의), **그래프 RAG**, **시세 도구**를 조합한다.
→ "최근 호재 뉴스가 많고 섹터 모멘텀이 좋은 종목은?" 같은 복합 질문에 **근거(뉴스·수치)를 인용**해 답한다.

---

## ⚠️ 중요: 투자 면책 설계

이 시스템은 **정보 제공·교육 목적**이며 **투자자문이 아닙니다.** 추천 로직과 에이전트 출력에는 다음이 강제됩니다.

- 모든 추천에 **근거(뉴스 ID, 수치, 날짜) 인용** 의무화
- 출력 말미에 **면책 고지** 자동 삽입
- "사라/팔아라" 같은 단정적 지시 대신 **"~한 신호가 관측됨"** 식 정보 제공형 표현
- 자세한 설계: [docs/04-llm-agent-design.md](docs/04-llm-agent-design.md) §안전장치

---

## 문서 맵

| 문서 | 내용 |
|------|------|
| [docs/01-architecture.md](docs/01-architecture.md) | 전체 아키텍처 · 데이터 흐름 · 기술 선택 근거 |
| [docs/02-ontology-design.md](docs/02-ontology-design.md) | 금융 온톨로지 모델링 · 클래스/관계/제약 · 저장소 선택 |
| [docs/03-cdc-pipeline-design.md](docs/03-cdc-pipeline-design.md) | CDC 원리 · Debezium 구성 · 스트림→그래프 변환 · 일관성 |
| [docs/04-llm-agent-design.md](docs/04-llm-agent-design.md) | 에이전트 아키텍처 · 도구 · Text2Cypher · 추천 로직 · 안전장치 |
| [docs/05-implementation-plan.md](docs/05-implementation-plan.md) | 단계별 구현 로드맵 · 마일스톤 · 검증 기준 |

## 코드/구성 맵

```
ingestion/      뉴스 스크래퍼, 시세 수집기, 원천 DB 스키마
ontology/       Neo4j 온톨로지 스키마(Cypher/제약), 예시 데이터
cdc/            Debezium 커넥터 설정, Kafka 토픽 구성
pipeline/       Kafka consumer + 그래프 적재 변환 로직
agent/          LLM 에이전트(코어 루프, 도구, 프롬프트)
infra/          docker-compose 인프라 정의
```

---

## 빠른 시작 (개념 흐름)

```bash
# 1) 인프라 기동 (Postgres + Kafka + Connect + Neo4j)
docker compose -f infra/docker-compose.yml up -d

# 2) 원천 DB 스키마 + 온톨로지 스키마 적재
psql -f ingestion/db/schema.sql
python ontology/load_schema.py

# 3) CDC 커넥터 등록 (Postgres -> Kafka)
bash cdc/register-connectors.sh

# 4) 파이프라인 컨슈머 기동 (Kafka -> Neo4j)
python pipeline/consumer/run.py

# 5) 수집기 기동 (뉴스 + 시세 -> Postgres)
python ingestion/scrapers/run_news.py
python ingestion/market/run_prices.py

# 6) 에이전트 실행
python agent/main.py "최근 1주일 호재 뉴스가 집중된 코인은?"
```

> 본 저장소는 **설계 + 실행 가능한 스캐폴드**입니다. 운영 배포 전 환경값/시크릿/실제 데이터 소스 연결이 필요합니다.

---

## 기술 스택 요약

| 레이어 | 선택 | 비고 |
|--------|------|------|
| 뉴스 수집 | Python(httpx + selectolax/feedparser) | RSS 우선, robots.txt 준수 |
| 시세 수집 | 거래소/증권 API (ccxt, yfinance 등) | 폴링/웹소켓 |
| 원천 DB | PostgreSQL (logical replication=on) | CDC 소스 |
| CDC | Debezium + Kafka Connect | WAL 기반 |
| 스트림 | Apache Kafka | 토픽=테이블 |
| 지식그래프 | Neo4j (property graph) | Cypher 질의 |
| 임베딩 검색 | Neo4j vector index 또는 pgvector | 뉴스 의미검색 |
| LLM | function-calling 지원 모델 | Claude/GPT/로컬 |
| 에이전트 | 경량 ReAct 루프(자체 구현) | LangGraph 선택적 |
