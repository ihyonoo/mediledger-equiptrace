"""psycopg 연결 헬퍼. 데몬 기동 시 인벤토리를 로드하고 staff 비밀번호를 채우는
용도로만 쓰인다 — 위치/사용 활동 런타임 루프는 이후 순수 HTTP 클라이언트로 동작한다.
"""

from pathlib import Path

import psycopg
from passlib.context import CryptContext

from simulation import config

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

SEED_SQL_PATH = Path(__file__).resolve().parents[1] / "database" / "seed_demo_topology.sql"


def apply_seed_sql() -> None:
    """database/seed_demo_topology.sql을 적용한다. 멱등적(ON CONFLICT DO NOTHING)이라
    데몬을 재시작할 때마다 호출해도 안전하다 — 이미 존재하면 아무 것도 하지 않는다."""
    sql = SEED_SQL_PATH.read_text(encoding="utf-8")
    with psycopg.connect(config.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()


def load_sim_inventory() -> dict:
    with psycopg.connect(config.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT reader_id FROM readers WHERE is_real_hardware = FALSE ORDER BY reader_id")
        reader_ids = [row[0] for row in cur.fetchall()]

        cur.execute(
            "SELECT tag_id, nfc_tag_uid FROM tags "
            "WHERE is_real_hardware = FALSE AND nfc_tag_uid IS NOT NULL ORDER BY tag_id"
        )
        tag_nfc = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute("SELECT username FROM users WHERE is_real_hardware = FALSE AND role = 'staff' ORDER BY username")
        staff_usernames = [row[0] for row in cur.fetchall()]

    return {"reader_ids": reader_ids, "tag_nfc": tag_nfc, "staff_usernames": staff_usernames}


def ensure_staff_passwords(password: str) -> None:
    """플레이스홀더('x') 상태인 시뮬레이션 staff 계정에만 비밀번호 해시를 채운다.

    이미 해시가 채워진 계정은 건드리지 않는다 — bcrypt 해시는 매번 salt가 달라
    idempotent 비교가 불가능하므로, 최초 1회만 채우는 게 목적인 이 로직에선
    'x' 플레이스홀더 여부로 판단한다.
    """
    password_hash = pwd.hash(password)
    with psycopg.connect(config.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s "
            "WHERE is_real_hardware = FALSE AND role = 'staff' AND password_hash = 'x'",
            (password_hash,),
        )
        conn.commit()
