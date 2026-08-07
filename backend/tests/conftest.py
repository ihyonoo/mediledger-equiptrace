import contextlib
import os

# backend/settings.py가 import 시점에 DATABASE_URL을 읽으므로, backend 하위 모듈을
# import하기 전에 반드시 먼저 테스트 DB로 덮어써야 한다.
os.environ["DATABASE_URL"] = "postgresql://mediledger:mediledger@localhost:5432/mediledger_test_db"

import psycopg
import pytest
from fastapi.testclient import TestClient

from backend.auth_utils import build_auth_token, pwd
from backend.rtls_utils import REDIS_LOCATION_KEY_PREFIX, get_redis_client
from backend.server import app, tag_obs, tag_state

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

# FK 의존 관계 상 어느 순서로 나열해도 무방하다(한 TRUNCATE 문 + CASCADE로 처리).
TABLES_TO_TRUNCATE = [
    "usage_nfc_events",
    "usage_history",
    "tag_state_history",
    "auth_action_tokens",
    "user_oauth_identities",
    "tags",
    "readers",
    "users",
]


def _flush_location_cache():
    """rtls:tag:* 캐시를 지운다.

    Redis는 이 프로세스 밖에 있는 공용 인스턴스라 DB TRUNCATE로는 안 지워진다.
    이전 테스트(예: test_ingest_flow.py)가 캐싱한 태그 위치가 남아 있으면, 다른
    테스트 파일이 TRUNCATE로 비운 readers/tags와 불일치해 FK 위반 등으로 깨질 수 있다.
    """
    client = get_redis_client()
    if client is None:
        return
    with contextlib.suppress(Exception):
        keys = list(client.scan_iter(match=f"{REDIS_LOCATION_KEY_PREFIX}*"))
        if keys:
            client.delete(*keys)


@pytest.fixture(autouse=True)
def _clean_state():
    """매 테스트 전, DB 테이블·Redis 캐시·서버 메모리 상태(tag_obs/tag_state)를 초기화한다."""
    tag_obs.clear()
    tag_state.clear()
    _flush_location_cache()
    with psycopg.connect(TEST_DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(f"TRUNCATE {', '.join(TABLES_TO_TRUNCATE)} RESTART IDENTITY CASCADE")
    yield


@pytest.fixture
def db_conn():
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        yield conn


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_tag(db_conn):
    """/ingest, /where, /usage/checkout·return 같은 통합 테스트용 태그를 하나 만들어준다."""

    def _seed(
        tag_id: str = "EQ-TEST-0001",
        equipment_name: str = "테스트 장비",
        nfc_tag_uid: str | None = None,
        is_real_hardware: bool = True,
    ):
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tags (tag_id, equipment_name, nfc_tag_uid, is_active, is_real_hardware)
                VALUES (%s, %s, %s, TRUE, %s)
                """,
                (tag_id, equipment_name, nfc_tag_uid, is_real_hardware),
            )
        db_conn.commit()
        return tag_id

    return _seed


@pytest.fixture
def seed_reader(db_conn):
    """관리자 핀 편집기·rtls/live 통합 테스트용 리더를 하나 만들어준다."""

    def _seed(
        reader_id: str = "M999",
        location_name: str | None = "테스트 리더",
        is_real_hardware: bool = True,
    ):
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO readers (reader_id, location_name, is_real_hardware) VALUES (%s, %s, %s)",
                (reader_id, location_name, is_real_hardware),
            )
        db_conn.commit()
        return reader_id

    return _seed


@pytest.fixture
def seed_user(db_conn):
    """인증이 필요한 통합 테스트용 사용자를 만들고 (user_id, Bearer 헤더)를 반환한다."""

    def _seed(
        username: str = "tester",
        role: str = "staff",
        is_active: bool = True,
        email_verified: bool = True,
        position: str | None = "간호사",
        password: str | None = None,
        email: str | None = None,
    ):
        password_hash = pwd.hash(password) if password else "x"
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username, display_name, role, position, password_hash,
                                    is_active, email_verified, token_version, email)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s)
                RETURNING user_id
                """,
                (username, username, role, position, password_hash, is_active, email_verified, email),
            )
            user_id = cur.fetchone()[0]
        db_conn.commit()
        token, _ = build_auth_token(user_id=user_id, token_version=0)
        return user_id, {"Authorization": f"Bearer {token}"}

    return _seed
