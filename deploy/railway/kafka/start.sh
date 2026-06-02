#!/usr/bin/env bash
# Railway용 Kafka(KRaft 단일노드) 기동 스크립트.
#
# ★ 트러블슈팅 핵심 ★
# Kafka가 "어떤 주소로 접속하라"고 광고(advertised)하는 주소가 틀리면
# Connect/consumer가 절대 못 붙는다. Railway에서는 private domain을 써야 한다.
#
# Railway Variables에서 주입할 값:
#   RAILWAY_PRIVATE_DOMAIN   (Railway가 자동 제공: 예) kafka.railway.internal
#   KAFKA_INTERNAL_PORT      (기본 9092)
set -euo pipefail

PRIV="${RAILWAY_PRIVATE_DOMAIN:-localhost}"
PORT="${KAFKA_INTERNAL_PORT:-9092}"
CTRL_PORT="${KAFKA_CONTROLLER_PORT:-29093}"

# KRaft 클러스터 ID: 고정값을 Variables로 주거나 최초 1회 생성.
CLUSTER_ID="${KAFKA_CLUSTER_ID:-fin-cluster-0000000000}"

export KAFKA_NODE_ID=1
export KAFKA_PROCESS_ROLES=broker,controller
export KAFKA_CONTROLLER_QUORUM_VOTERS="1@${PRIV}:${CTRL_PORT}"

# ★ 리스너: Railway private network는 IPv6. 0.0.0.0(IPv4)만 바인딩하면
#   내부 통신이 안 될 수 있으므로 :: (모든 IPv6/IPv4) 로 바인딩.
export KAFKA_LISTENERS="PLAINTEXT://[::]:${PORT},CONTROLLER://[::]:${CTRL_PORT}"
# ★ advertised: 클라이언트가 실제로 접속할 주소 = Railway private domain
export KAFKA_ADVERTISED_LISTENERS="PLAINTEXT://${PRIV}:${PORT}"
export KAFKA_CONTROLLER_LISTENER_NAMES="CONTROLLER"
export KAFKA_LISTENER_SECURITY_PROTOCOL_MAP="CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT"
export KAFKA_INTER_BROKER_LISTENER_NAME="PLAINTEXT"

# 단일 노드이므로 복제 인자 전부 1
export KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1
export KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1
export KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1
export KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0

# 데이터 디렉토리(Railway Volume을 /var/lib/kafka/data에 마운트 권장)
export KAFKA_LOG_DIRS="${KAFKA_LOG_DIRS:-/var/lib/kafka/data}"
export CLUSTER_ID

echo "[kafka] advertised=${KAFKA_ADVERTISED_LISTENERS}"
echo "[kafka] listeners=${KAFKA_LISTENERS}"
echo "[kafka] cluster_id=${CLUSTER_ID}  log_dirs=${KAFKA_LOG_DIRS}"

# confluent 이미지의 표준 엔트리포인트로 위임
exec /etc/confluent/docker/run
