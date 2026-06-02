#!/usr/bin/env bash
# Debezium 커넥터 등록 스크립트
# 사용: bash cdc/register-connectors.sh
set -euo pipefail

CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[*] Kafka Connect 준비 대기..."
until curl -sf "${CONNECT_URL}/connectors" >/dev/null; do
  echo "    connect 대기 중..."; sleep 3
done

echo "[*] Postgres 소스 커넥터 등록"
curl -sf -X POST "${CONNECT_URL}/connectors" \
  -H "Content-Type: application/json" \
  -d @"${HERE}/debezium/postgres-source.json" \
  | python3 -m json.tool || {
    echo "[!] 이미 존재하면 PUT으로 갱신 시도"
    NAME=$(python3 -c "import json,sys;print(json.load(open('${HERE}/debezium/postgres-source.json'))['name'])")
    CFG=$(python3 -c "import json;print(json.dumps(json.load(open('${HERE}/debezium/postgres-source.json'))['config']))")
    curl -sf -X PUT "${CONNECT_URL}/connectors/${NAME}/config" \
      -H "Content-Type: application/json" -d "${CFG}" | python3 -m json.tool
  }

echo
echo "[*] 커넥터 상태:"
curl -sf "${CONNECT_URL}/connectors/fin-postgres-source/status" | python3 -m json.tool

echo
echo "[done] 등록 완료. 생성될 토픽 예시:"
echo "  fin.public.raw_news / fin.public.price_bars / fin.public.events / fin.public.assets"
