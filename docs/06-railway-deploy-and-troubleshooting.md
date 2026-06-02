# 06. Railway 풀스택 배포 + Kafka 트러블슈팅 가이드

> 목표: Postgres + Kafka + Kafka Connect(Debezium) + Neo4j + App 을 **Railway에 개별 서비스로** 배포하고,
> Kafka 운영 중 마주치는 실전 장애를 직접 트러블슈팅한다.

---

## 0. 핵심 개념: Railway는 docker-compose가 아니다

| 로컬(compose) | Railway |
|----------------|---------|
| `docker-compose up` 한 방 | 서비스마다 **개별 배포** |
| 서비스명으로 통신(`kafka:9092`) | **`<service>.railway.internal`** (private network) |
| `depends_on` 기동순서 | **없음** → 죽으면 재시작으로 수렴 |
| `localhost` 포트 노출 | **public domain**은 명시적으로 생성한 것만 |

→ compose의 `infra/docker-compose.yml`은 **로컬 검증용으로 유지**, Railway는 `deploy/railway/*`로 따로 구성.

---

## 1. 서비스 토폴로지 (Railway 프로젝트 1개 안에 5개 서비스)

```
┌────────────────────────── Railway Project: fin-platform ──────────────────────────┐
│                                                                                     │
│  [Postgres]  ──private──┐                                                            │
│   (plugin)              │                                                            │
│                         ▼                                                            │
│  [kafka] ◄──private──► [connect] ──private──► (Kafka topics)                         │
│   railway.internal       (Debezium)                                                  │
│                         │                                                            │
│                         ▼                                                            │
│  [app]  ── consumer(Kafka→Neo4j) + agent ── private ──► [neo4j]                      │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
   public domain은 app(에이전트 API)과 neo4j(7474 UI, 디버그용)에만 부여
```

### 내부 호스트네임 (private networking)
- Postgres: Railway가 주입하는 `DATABASE_URL` / `PGHOST` 등 사용
- Kafka: `kafka.railway.internal:9092`
- Connect: `connect.railway.internal:8083`
- Neo4j: `neo4j.railway.internal:7687`

> ⚠️ Railway private network는 **IPv6**다. 컨테이너가 `0.0.0.0`(IPv4)만 리슨하면 내부 통신이 안 될 수 있다 → 아래 Kafka 설정에서 `::`(IPv6 any) 또는 모든 인터페이스 바인딩 주의.

---

## 2. 배포 순서 (의존성 기준)

```
1) Postgres (plugin)         ─ 가장 먼저, DATABASE_URL 확보
2) Neo4j                     ─ 독립적, 먼저 떠도 됨
3) Kafka                     ─ Connect/app의 전제
4) Connect (Debezium)        ─ Kafka 준비 후
5) App (consumer + agent)    ─ 전부 준비 후
```

Railway엔 `depends_on`이 없으므로 **3→4→5가 먼저 떠서 죽었다 재시작**하는 게 정상이다.
이건 버그가 아니라 "eventually consistent 기동" → §트러블슈팅 T1 참조.

---

## 3. 각 서비스 구성 파일

| 서비스 | 디렉토리 | 핵심 파일 |
|--------|----------|-----------|
| Kafka | `deploy/railway/kafka/` | Dockerfile, railway.json |
| Connect | `deploy/railway/connect/` | Dockerfile, railway.json |
| Neo4j | `deploy/railway/neo4j/` | railway.json (이미지 직접 사용) |
| App | `deploy/railway/app/` | Dockerfile (consumer+agent) |
| Postgres | — | Railway 플러그인(원클릭) |

각 디렉토리의 파일과 환경변수는 해당 폴더 + 본 문서 §5 참조.

---

## 4. CLI 배포 흐름

```bash
# 설치 (npm 또는 brew)
npm i -g @railway/cli      # 또는: bash <(curl -fsSL cli.new)

railway login              # 브라우저 인증
railway init               # 프로젝트 생성 (fin-platform)

# Postgres 플러그인 추가
railway add --plugin postgresql

# 서비스별 배포 (각 디렉토리에서)
cd deploy/railway/kafka   && railway up --service kafka
cd ../neo4j               && railway up --service neo4j
cd ../connect             && railway up --service connect
cd ../app                 && railway up --service app
```

> GitHub 연동 방식이면: 이 repo를 푸시 → Railway 대시보드에서 각 서비스의 **Root Directory**를
> `deploy/railway/kafka` 식으로 지정 → 자동 빌드.

---

## 5. 환경변수 (서비스별)

### Kafka (KRaft 단일 노드)
```
KAFKA_NODE_ID=1
KAFKA_PROCESS_ROLES=broker,controller
KAFKA_CONTROLLER_QUORUM_VOTERS=1@kafka.railway.internal:29093
KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:29093
KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka.railway.internal:9092   # ★ 핵심
KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER
KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1
KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1
KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1
CLUSTER_ID=fin-cluster-0000000000
KAFKA_HEAP_OPTS=-Xmx512m -Xms256m     # ★ 메모리 절약(OOM 방지)
```

### Connect (Debezium)
```
BOOTSTRAP_SERVERS=kafka.railway.internal:9092      # ★ private host
GROUP_ID=fin-connect
CONFIG_STORAGE_TOPIC=_connect_configs
OFFSET_STORAGE_TOPIC=_connect_offsets
STATUS_STORAGE_TOPIC=_connect_status
CONFIG_STORAGE_REPLICATION_FACTOR=1
OFFSET_STORAGE_REPLICATION_FACTOR=1
STATUS_STORAGE_REPLICATION_FACTOR=1
KEY_CONVERTER=org.apache.kafka.connect.json.JsonConverter
VALUE_CONVERTER=org.apache.kafka.connect.json.JsonConverter
CONNECT_KEY_CONVERTER_SCHEMAS_ENABLE=false
CONNECT_VALUE_CONVERTER_SCHEMAS_ENABLE=false
KAFKA_HEAP_OPTS=-Xmx512m -Xms256m
```

### Neo4j
```
NEO4J_AUTH=neo4j/<강한비밀번호>
NEO4J_server_memory_heap_max__size=512m
NEO4J_server_memory_pagecache_size=256m
NEO4J_PLUGINS=["apoc"]
```

### App (consumer + agent)
```
KAFKA_BOOTSTRAP=kafka.railway.internal:9092
NEO4J_URI=bolt://neo4j.railway.internal:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<위와 동일>
PG_DSN=${{Postgres.DATABASE_URL}}                  # Railway 변수 참조 문법
OPENAI_API_KEY=<선택>
```

> `${{Postgres.DATABASE_URL}}`는 Railway의 **서비스 간 변수 참조** 문법. 대시보드 Variables에서 연결.

---

## 6. 트러블슈팅 플레이북 (Kafka 장애 대응)

### T1. Connect/App이 계속 재시작 (CrashLoopBackOff 유사)
**증상**: 배포 직후 connect/app 로그에 `Connection refused kafka.railway.internal:9092` 반복.
**원인**: Kafka가 아직 안 떴는데 먼저 접속 시도(기동 순서 없음).
**대응**:
- 정상 동작이다. Kafka가 뜨면 재시작하며 수렴한다.
- 그래도 안 붙으면 → Kafka 로그에서 "started (kafka.server.KafkaRaftServer)" 확인.
- 영구화: app에 **재시도 로직**(지수 백오프) 내장 → `deploy/railway/app/wait_for_kafka.py`.

### T2. `advertised.listeners` 미스 → consumer가 못 붙음
**증상**: Connect는 떴는데 토픽 생성/구독에서 멈춤. 로그에 broker 주소가 엉뚱하게 보임.
**원인**: `KAFKA_ADVERTISED_LISTENERS`가 `localhost`나 컨테이너 내부 IP로 광고됨.
**대응**:
- 반드시 `PLAINTEXT://kafka.railway.internal:9092`로 설정(★).
- 검증: connect 컨테이너에서 `kafka-broker-api-versions --bootstrap-server kafka.railway.internal:9092`.

### T3. Kafka OOMKilled
**증상**: Kafka가 주기적으로 죽음. Railway Metrics에서 memory 100% 후 재시작.
**원인**: JVM heap 기본값이 너무 큼.
**대응**:
- `KAFKA_HEAP_OPTS=-Xmx512m -Xms256m`로 제한.
- 토픽 retention 축소: `KAFKA_LOG_RETENTION_HOURS=24`, 세그먼트 작게.
- 그래도 부족하면 서비스 메모리 플랜 상향.

### T4. Postgres replication slot 적체 → 디스크 폭증
**증상**: Postgres 디스크 사용량이 계속 증가. `pg_replication_slots`의 slot이 `active=false`.
**원인**: Debezium consumer가 죽어서 WAL이 소비되지 않아 슬롯에 쌓임.
**대응**:
```sql
SELECT slot_name, active, pg_size_pretty(
  pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained
FROM pg_replication_slots;
-- 죽은 슬롯 정리 (주의: 재스냅샷 필요해질 수 있음)
SELECT pg_drop_replication_slot('fin_slot');
```
- 예방: connect를 상시 가동, `heartbeat.interval.ms` 설정.

### T5. Connect 내부 토픽 RF 에러
**증상**: connect 기동 시 `replication factor: 3 larger than available brokers: 1`.
**원인**: 단일 브로커인데 내부 토픽 RF 기본 3.
**대응**: `*_STORAGE_REPLICATION_FACTOR=1` 3종 모두 설정(§5).

### T6. consumer lag 증가 (그래프 반영 지연)
**증상**: Postgres엔 들어왔는데 Neo4j 반영이 느림.
**진단**:
```bash
kafka-consumer-groups --bootstrap-server kafka.railway.internal:9092 \
  --describe --group graph-loader     # LAG 컬럼 확인
```
**대응**: 무거운 작업(임베딩/LLM)을 별도 컨슈머 그룹으로 분리, 파티션·컨슈머 수평 확장.

### T7. private network 연결 실패 (IPv6)
**증상**: `*.railway.internal` 이름은 풀리는데 connection timeout.
**원인**: 서비스가 IPv4(`0.0.0.0`)만 리슨, Railway 내부는 IPv6.
**대응**: 가능하면 모든 인터페이스 바인딩, 또는 Railway 권장 이미지 사용. App(파이썬)은 보통 자동 처리됨.

---

## 7. 배포 후 스모크 테스트

```bash
# 1) Postgres 스키마 적재 (로컬에서 public DATABASE_URL로)
psql "$DATABASE_URL_PUBLIC" -f ingestion/db/schema.sql

# 2) Connect에 커넥터 등록 (connect public domain 부여 후)
CONNECT_URL=https://<connect-domain> bash cdc/register-connectors.sh

# 3) 샘플 뉴스 INSERT → CDC → Neo4j 확인
PG_DSN="$DATABASE_URL_PUBLIC" python ingestion/scrapers/run_news.py
# Neo4j 브라우저(https://<neo4j-domain>)에서:
#   MATCH (n:NewsArticle)-[:MENTIONS]->(a:Asset) RETURN n,a

# 4) 에이전트 호출
python agent/main.py "최근 호재가 많은 코인 알려줘"
```

검증 체크리스트:
- [ ] Kafka 토픽 `fin.public.raw_news` 생성됨
- [ ] consumer group `graph-loader` LAG ~0
- [ ] Neo4j에 NewsArticle/MENTIONS 노드 생성
- [ ] 에이전트 응답에 근거 + 면책 포함

---

## 8. 비용/리소스 메모

| 서비스 | 권장 메모리 | 비고 |
|--------|-------------|------|
| Postgres | 256–512MB | 플러그인 |
| Neo4j | 768MB+ | heap 512 + pagecache 256 |
| Kafka | 768MB+ | heap 512 |
| Connect | 768MB+ | heap 512 |
| App | 256–512MB | 파이썬 |

→ 합계 ~3GB. **Hobby plan 이상 권장.** Trial 크레딧만으론 Kafka+Connect 동시 가동이 불안정.
