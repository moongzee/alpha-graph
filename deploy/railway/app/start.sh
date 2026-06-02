#!/usr/bin/env bash
# App 서비스 기동: 의존 서비스 준비 대기 → 스키마/커넥터 부트스트랩 → 컨슈머 상시 가동.
#
# Railway Variables(이 서비스)에서 주입:
#   PG_DSN            postgresql://USER:PASS@postgres.railway.internal:5432/findb
#   KAFKA_BOOTSTRAP   kafka.railway.internal:9092
#   CONNECT_URL       http://connect.railway.internal:8083
#   NEO4J_URI         bolt://neo4j.railway.internal:7687
#   NEO4J_USER / NEO4J_PASSWORD
set -euo pipefail

echo "[app] === 부트스트랩 시작 ==="

# 1) Neo4j 준비 대기 + 온톨로지 스키마 적재
echo "[app] Neo4j 준비 대기..."
python - <<'PY'
import os, time
from neo4j import GraphDatabase
uri=os.environ["NEO4J_URI"]; user=os.getenv("NEO4J_USER","neo4j"); pw=os.environ["NEO4J_PASSWORD"]
for i in range(60):
    try:
        d=GraphDatabase.driver(uri, auth=(user,pw)); d.verify_connectivity(); d.close()
        print("[app] Neo4j OK"); break
    except Exception as e:
        print(f"  대기 {i}/60: {e}"); time.sleep(5)
else:
    raise SystemExit("[app] Neo4j 연결 실패")
PY
python ontology/load_schema.py || echo "[app] 스키마 적재 경고(이미 존재 가능)"

# 2) Postgres 준비 대기 + 원천 스키마 적재
echo "[app] Postgres 스키마 적재..."
for i in $(seq 1 60); do
  if psql "${PG_DSN}" -c "SELECT 1" >/dev/null 2>&1; then
    psql "${PG_DSN}" -f ingestion/db/schema.sql && echo "[app] PG 스키마 OK"
    break
  fi
  echo "  PG 대기 ${i}/60"; sleep 5
done

# 3) Debezium 커넥터 등록 (Connect 준비 대기 포함)
echo "[app] Debezium 커넥터 등록..."
CONNECT_URL="${CONNECT_URL:?CONNECT_URL 필요}"
for i in $(seq 1 60); do
  if curl -sf "${CONNECT_URL}/connectors" >/dev/null 2>&1; then break; fi
  echo "  Connect 대기 ${i}/60"; sleep 5
done
# postgres-source.json의 hostname을 Railway용으로 치환해 등록
python - <<'PY'
import os, json, urllib.request
cfg=json.load(open("cdc/debezium/postgres-source.json"))
dsn=os.environ["PG_DSN"]  # postgresql://user:pass@host:port/db
from urllib.parse import urlparse
parsed=urlparse(dsn)
if parsed.hostname:
    u=parsed.username; p=parsed.password
    h=parsed.hostname; port=str(parsed.port or 5432)
    db=parsed.path.lstrip("/")
    cfg["config"]["database.hostname"]=h
    cfg["config"]["database.port"]=port or "5432"
    cfg["config"]["database.user"]=u
    cfg["config"]["database.password"]=p
    cfg["config"]["database.dbname"]=db
data=json.dumps(cfg).encode()
url=os.environ["CONNECT_URL"]+"/connectors"
req=urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
try:
    print(urllib.request.urlopen(req).read().decode()[:200])
    print("[app] 커넥터 등록 완료")
except Exception as e:
    print(f"[app] 커넥터 등록 응답: {e} (이미 존재 시 정상)")
PY

echo "[app] === 부트스트랩 완료. 컨슈머 상시 가동 ==="
exec python pipeline/consumer/run.py
