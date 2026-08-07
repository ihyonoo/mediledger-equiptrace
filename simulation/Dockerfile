# simulation/Dockerfile
#
# backend/Dockerfile보다 훨씬 가볍다 — 앵커링은 backend 컨테이너가 subprocess로 처리하고,
# 이 컨테이너는 순수 HTTP 클라이언트(/ingest, /auth/login, /usage/checkout, /usage/return
# 호출)일 뿐이라 Node/besu 의존성이 필요 없다.

FROM python:3.12-slim

WORKDIR /app

COPY simulation/requirements.txt simulation/requirements.txt
RUN pip install --no-cache-dir -r simulation/requirements.txt

COPY simulation/ simulation/
COPY database/seed_demo_topology.sql database/seed_demo_topology.sql

# BACKEND_BASE_URL/DATABASE_URL/SIM_STAFF_PASSWORD 등은 docker-compose의
# env_file/environment로 런타임에 주입된다(simulation/.env는 이미지에 없음).
CMD ["python", "-m", "simulation.simulator"]
