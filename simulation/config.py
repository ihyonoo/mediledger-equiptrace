import os
from pathlib import Path

from dotenv import load_dotenv

# 로컬 실행 시 simulation/.env에서 읽는다. 홈서버 컨테이너에서는 이 파일이 이미지에
# 없으므로 조용히 무시되고, 대신 docker-compose의 env_file/environment로 주입된
# OS 환경변수가 그대로 쓰인다 (backend/settings.py와 동일한 패턴).
load_dotenv(Path(__file__).resolve().parent / ".env")

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://mediledger:mediledger@localhost:5432/mediledger_db")
SIM_STAFF_PASSWORD = os.getenv("SIM_STAFF_PASSWORD")

# 위치 시뮬레이션 루프
POSITION_TICK_SEC = float(os.getenv("POSITION_TICK_SEC", "3"))
ROOM_DWELL_MIN_SEC = float(os.getenv("ROOM_DWELL_MIN_SEC", "20"))
ROOM_DWELL_MAX_SEC = float(os.getenv("ROOM_DWELL_MAX_SEC", "90"))
RSSI_MIN = int(os.getenv("RSSI_MIN", "-70"))
RSSI_MAX = int(os.getenv("RSSI_MAX", "-45"))
READER_OUTAGE_PROBABILITY_PER_TICK = float(os.getenv("READER_OUTAGE_PROBABILITY_PER_TICK", "0.003"))
READER_OUTAGE_MIN_SEC = float(os.getenv("READER_OUTAGE_MIN_SEC", "15"))
READER_OUTAGE_MAX_SEC = float(os.getenv("READER_OUTAGE_MAX_SEC", "60"))
TAG_STALE_PROBABILITY_PER_TICK = float(os.getenv("TAG_STALE_PROBABILITY_PER_TICK", "0.002"))
TAG_STALE_MIN_SEC = float(os.getenv("TAG_STALE_MIN_SEC", "6"))
TAG_STALE_MAX_SEC = float(os.getenv("TAG_STALE_MAX_SEC", "20"))

# 사용 활동(체크아웃/반납) 시뮬레이션 루프
CHECKOUT_CHECK_INTERVAL_SEC = float(os.getenv("CHECKOUT_CHECK_INTERVAL_SEC", "15"))
BASE_CHECKOUT_PROBABILITY_PER_TICK = float(os.getenv("BASE_CHECKOUT_PROBABILITY_PER_TICK", "0.02"))
SIM_ACTIVITY_SCALE = float(os.getenv("SIM_ACTIVITY_SCALE", "1.0"))
USAGE_DURATION_MIN_SEC = float(os.getenv("USAGE_DURATION_MIN_SEC", "300"))
USAGE_DURATION_MAX_SEC = float(os.getenv("USAGE_DURATION_MAX_SEC", "2700"))
RETURN_HTTP_TIMEOUT_SEC = float(os.getenv("RETURN_HTTP_TIMEOUT_SEC", "40"))

# 시간대별(0~23시) 활동 배율. 심야에 낮고, 출근/오전·오후 진료 시간에 높다.
ACTIVITY_BY_HOUR = [
    0.05, 0.03, 0.03, 0.03, 0.05, 0.10,  # 00~05시
    0.25, 0.50, 0.80, 0.95, 1.00, 0.90,  # 06~11시
    0.70, 0.85, 0.95, 0.90, 0.75, 0.55,  # 12~17시
    0.40, 0.30, 0.20, 0.15, 0.10, 0.07,  # 18~23시
]  # fmt: skip
