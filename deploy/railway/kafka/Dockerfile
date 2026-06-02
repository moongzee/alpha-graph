# Railway 전용 Kafka (KRaft 단일 노드)
# 핵심: ADVERTISED_LISTENERS를 Railway private domain에 맞춰야 Connect/consumer가 붙는다.
# 이 변수들은 Railway 서비스 Variables에서 주입한다(아래 railway.json 참고).
FROM confluentinc/cp-kafka:7.6.1

# 메모리 절약: KRaft heap을 낮게 (Railway Hobby 기준)
ENV KAFKA_HEAP_OPTS="-Xms256M -Xmx512M"

# Railway는 단일 컨테이너에 단일 포트 외부노출. Kafka는 내부통신이 핵심이라
# 보통 public domain 불필요(같은 프로젝트 내 private network로만 접근).
EXPOSE 9092
