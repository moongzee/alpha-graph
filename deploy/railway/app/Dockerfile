# Railway용 App (파이프라인 컨슈머 + 부트스트랩 + 에이전트)
FROM python:3.12-slim

WORKDIR /app

# 빌드 의존성(psycopg, confluent-kafka용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc librdkafka-dev curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 기본 실행: 부트스트랩(스키마+커넥터) 후 컨슈머 상시 가동
CMD ["bash", "deploy/railway/app/start.sh"]
