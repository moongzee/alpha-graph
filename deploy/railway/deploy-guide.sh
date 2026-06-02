#!/usr/bin/env bash
# Railway 풀스택 배포 가이드 스크립트 (대화형 안내).
# 실제 배포는 각 단계 주석을 따라 수동 실행 권장.
# Railway는 서비스마다 별도 배포가 필요하므로 한 방에 다 되진 않는다.
set -euo pipefail

cat <<'GUIDE'
=====================================================================
 Railway 풀스택 배포 절차 (Postgres + Kafka + Connect + Neo4j + App)
=====================================================================

[사전] Railway CLI 설치 & 로그인
  npm i -g @railway/cli      # 또는: bash <(curl -fsSL https://railway.app/install.sh)
  railway login
  railway init               # 새 프로젝트 생성 (이 폴더에서)

---------------------------------------------------------------------
STEP 1. Postgres (공식 플러그인 — 가장 쉬움)
---------------------------------------------------------------------
  Railway 대시보드 > New > Database > PostgreSQL
  → DATABASE_URL 등 자동 생성. wal_level=logical 설정 필요:
    railway connect Postgres   # psql 접속 후:
      ALTER SYSTEM SET wal_level = logical;
      -- 플러그인 PG는 재시작 권한이 제한될 수 있음.
      -- 안 되면 Postgres를 커스텀 Docker로 띄워 command에 wal_level 지정.

  ※ 플러그인 PG가 wal_level 변경 불가면:
    커스텀 이미지를 만들어
    command: postgres -c wal_level=logical -c max_replication_slots=10

---------------------------------------------------------------------
STEP 2. Neo4j
---------------------------------------------------------------------
  서비스 생성 후 이 repo 연결:
  dockerfilePath = deploy/railway/neo4j/Dockerfile
  Variables: NEO4J_AUTH=neo4j/강한비밀번호
  Volume: /data 마운트

---------------------------------------------------------------------
STEP 3. Kafka  ★ 트러블슈팅 1순위 ★
---------------------------------------------------------------------
  서비스 생성, dockerfilePath = deploy/railway/kafka/Dockerfile
  Variables(ENV_TEMPLATE.txt 참고):
    KAFKA_CLUSTER_ID, KAFKA_INTERNAL_PORT=9092 ...
  Volume: /var/lib/kafka/data
  start.sh가 RAILWAY_PRIVATE_DOMAIN으로 advertised listener를 맞춘다.
  배포 후 로그에서 advertised= 줄 확인:
    [kafka] advertised=PLAINTEXT://kafka.railway.internal:9092

---------------------------------------------------------------------
STEP 4. Connect (Debezium)
---------------------------------------------------------------------
  dockerfilePath = deploy/railway/connect/Dockerfile
  Variables: KAFKA_BOOTSTRAP=kafka.railway.internal:9092
  Kafka보다 먼저 뜨면 죽는다 → start.sh가 대기 로직 포함, 재시작으로 수렴.
  배포 후 확인(app 셸에서):
    curl http://connect.railway.internal:8083/

---------------------------------------------------------------------
STEP 5. App (파이프라인 컨슈머 + 부트스트랩)
---------------------------------------------------------------------
  dockerfilePath = deploy/railway/app/Dockerfile
  Variables: PG_DSN, KAFKA_BOOTSTRAP, CONNECT_URL, NEO4J_URI/USER/PASSWORD
  start.sh가 자동으로:
     온톨로지 스키마 적재 -> PG 스키마 적재 -> Debezium 커넥터 등록 -> 컨슈머 가동

---------------------------------------------------------------------
STEP 6. 검증
---------------------------------------------------------------------
  # app 서비스 셸(railway shell 또는 railway run)에서:
  python ingestion/scrapers/run_news.py     # 샘플 뉴스 -> PG
  python ingestion/market/run_prices.py     # 샘플 시세 -> PG
  # 수 초 후 Neo4j에 NewsArticle 생성되는지:
  python agent/main.py "최근 호재가 많은 코인 알려줘"

  자세한 트러블슈팅: docs/06-railway-deploy-and-troubleshooting.md
=====================================================================
GUIDE
