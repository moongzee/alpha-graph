#!/usr/bin/env bash
# Railway용 Kafka Connect 기동.
#
# ★ 트러블슈팅 핵심 ★
# 1) BOOTSTRAP_SERVERS는 Kafka 서비스의 private domain을 가리켜야 한다.
# 2) Connect가 Kafka보다 먼저 뜨면 연결 실패로 죽는다 → Kafka 준비를 기다린다.
# 3) Connect 내부 토픽(config/offset/status)은 단일노드라 복제인자 1.
set -euo pipefail

# Railway Variables에서 주입:
#   KAFKA_BOOTSTRAP  예) kafka.railway.internal:9092
BOOTSTRAP="${KAFKA_BOOTSTRAP:?KAFKA_BOOTSTRAP 필요 (예: kafka.railway.internal:9092)}"

export BOOTSTRAP_SERVERS="${BOOTSTRAP}"
export GROUP_ID="${CONNECT_GROUP_ID:-fin-connect}"
export CONFIG_STORAGE_TOPIC="${CONFIG_STORAGE_TOPIC:-_connect_configs}"
export OFFSET_STORAGE_TOPIC="${OFFSET_STORAGE_TOPIC:-_connect_offsets}"
export STATUS_STORAGE_TOPIC="${STATUS_STORAGE_TOPIC:-_connect_status}"
export CONFIG_STORAGE_REPLICATION_FACTOR=1
export OFFSET_STORAGE_REPLICATION_FACTOR=1
export STATUS_STORAGE_REPLICATION_FACTOR=1
export KEY_CONVERTER="org.apache.kafka.connect.json.JsonConverter"
export VALUE_CONVERTER="org.apache.kafka.connect.json.JsonConverter"
export CONNECT_KEY_CONVERTER_SCHEMAS_ENABLE="false"
export CONNECT_VALUE_CONVERTER_SCHEMAS_ENABLE="false"
# Connect REST는 외부에서 커넥터 등록할 수 있게 0.0.0.0
export REST_ADVERTISED_HOST_NAME="${RAILWAY_PRIVATE_DOMAIN:-localhost}"

# --- Kafka 준비 대기 (기동순서 장애 대응) ---
HOST="${BOOTSTRAP%%:*}"
PORT="${BOOTSTRAP##*:}"
echo "[connect] Kafka(${HOST}:${PORT}) 준비 대기..."
for i in $(seq 1 60); do
  if (echo > "/dev/tcp/${HOST}/${PORT}") >/dev/null 2>&1; then
    echo "[connect] Kafka 연결 가능. Connect 시작."
    break
  fi
  echo "  ...대기 ${i}/60"; sleep 5
done

exec /docker-entrypoint.sh start
