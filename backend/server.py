import datetime as dt
import os
import time
import urllib.parse

import psycopg
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

try:
    from backend import google_oauth
    from backend.auth_tokens import consume_action_token, create_action_token
    from backend.auth_utils import (
        build_auth_token,
        build_user_payload,
        normalize_display_name,
        normalize_email,
        normalize_optional_text,
        normalize_username,
        pwd,
        require_authenticated_user,
        validate_password,
    )
    from backend.demo_history import build_blockchain_demo_history
    from backend.email_utils import (
        send_find_id_email,
        send_reset_email,
        send_verification_email,
    )
    from backend.rtls_utils import (
        cache_location_updates,
        insert_location_history,
        load_active_tag_ids,
        load_all_cached_tag_locations,
        load_latest_db_tag_locations,
        load_reader_location_map,
        load_readers_for_admin,
        load_readers_with_status,
        load_tag_metadata,
        load_tags_last_seen,
        mark_tags_seen,
        normalize_nfc_token,
        resolve_tag_location_snapshot,
        update_reader_map_position,
        upsert_readers_from_ingest,
    )
    from backend.schemas import (
        ChangeEmailRequest,
        ChangePasswordRequest,
        FindIdRequest,
        ForgotPasswordRequest,
        GoogleCompleteRequest,
        LoginRequest,
        NfcMappingUpsertRequest,
        NfcUsageActionRequest,
        Payload,
        ReaderMapPositionRequest,
        RegisterRequest,
        ResendVerificationRequest,
        ResetPasswordRequest,
        SessionExchangeRequest,
        VerifyEmailRequest,
        WithdrawRequest,
    )
    from backend.settings import (
        APP_PUBLIC_URL,
        DATABASE_URL,
        DWELL_SEC,
        EMAIL_VERIFY_TTL_SEC,
        HYST_DB,
        OAUTH_HANDOFF_TTL_SEC,
        OAUTH_PENDING_TTL_SEC,
        PASSWORD_RESET_TTL_SEC,
        READER_LOCATION,
        READER_OFFLINE_SEC,
        STALE_SEC,
        TAG_OFFLINE_SEC,
    )
    from backend.usage_history_service import (
        anchor_usage_record_to_chain,
        build_my_usage_history_item,
        build_usage_history_item,
        persist_usage_chain_anchor_metadata,
        query_my_usage_history_rows,
        query_usage_history_rows,
        verify_usage_history_integrity,
    )
except ModuleNotFoundError as exc:
    if not exc.name or not exc.name.startswith("backend"):
        raise
    import google_oauth
    from auth_tokens import consume_action_token, create_action_token
    from auth_utils import (
        build_auth_token,
        build_user_payload,
        normalize_display_name,
        normalize_email,
        normalize_optional_text,
        normalize_username,
        pwd,
        require_authenticated_user,
        validate_password,
    )
    from demo_history import build_blockchain_demo_history
    from email_utils import (
        send_find_id_email,
        send_reset_email,
        send_verification_email,
    )
    from rtls_utils import (
        cache_location_updates,
        insert_location_history,
        load_active_tag_ids,
        load_all_cached_tag_locations,
        load_latest_db_tag_locations,
        load_reader_location_map,
        load_readers_for_admin,
        load_readers_with_status,
        load_tag_metadata,
        load_tags_last_seen,
        mark_tags_seen,
        normalize_nfc_token,
        resolve_tag_location_snapshot,
        update_reader_map_position,
        upsert_readers_from_ingest,
    )
    from schemas import (
        ChangeEmailRequest,
        ChangePasswordRequest,
        FindIdRequest,
        ForgotPasswordRequest,
        GoogleCompleteRequest,
        LoginRequest,
        NfcMappingUpsertRequest,
        NfcUsageActionRequest,
        Payload,
        ReaderMapPositionRequest,
        RegisterRequest,
        ResendVerificationRequest,
        ResetPasswordRequest,
        SessionExchangeRequest,
        VerifyEmailRequest,
        WithdrawRequest,
    )
    from settings import (
        APP_PUBLIC_URL,
        DATABASE_URL,
        DWELL_SEC,
        EMAIL_VERIFY_TTL_SEC,
        HYST_DB,
        OAUTH_HANDOFF_TTL_SEC,
        OAUTH_PENDING_TTL_SEC,
        PASSWORD_RESET_TTL_SEC,
        READER_LOCATION,
        READER_OFFLINE_SEC,
        STALE_SEC,
        TAG_OFFLINE_SEC,
    )
    from usage_history_service import (
        anchor_usage_record_to_chain,
        build_my_usage_history_item,
        build_usage_history_item,
        persist_usage_chain_anchor_metadata,
        query_my_usage_history_rows,
        query_usage_history_rows,
        verify_usage_history_integrity,
    )

app = FastAPI()


def get_allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS")
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return ["http://localhost:5173", "http://127.0.0.1:5173"]


def get_allowed_origin_regex() -> str:
    # 로컬 개발 중 동일 LAN 장치 접근을 허용한다.
    return (
        r"^https?://("
        r"localhost|"
        r"127\.0\.0\.1|"
        r"192\.168\.\d+\.\d+|"
        r"10\.\d+\.\d+\.\d+|"
        r"172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+"
        r")(:\d+)?$"
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_origin_regex=get_allowed_origin_regex(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 서버 메모리에서 태그별 관측 상태를 잠시 유지한다.
tag_obs: dict[str, dict[str, dict]] = {}
tag_state: dict[str, dict] = {}


def fetch_tag_by_nfc_token(cur, token: str):
    sql = """
    SELECT
      t.tag_id,
      t.equipment_name,
      t.equipment_type,
      t.serial_number,
      t.nfc_tag_uid,
      t.asset_status,
      t.current_holder_user_id,
      COALESCE(u.display_name, u.username) AS current_holder_name,
      t.current_usage_id,
      t.is_active
    FROM tags t
    LEFT JOIN users u ON u.user_id = t.current_holder_user_id
    WHERE t.nfc_tag_uid = %s
    FOR UPDATE OF t
    """
    cur.execute(sql, (token,))
    return cur.fetchone()


def insert_nfc_event(
    cur,
    *,
    usage_id: int | None,
    tag_id: str,
    user_id: int | None,
    equipment_nfc_uid: str,
    action: str,
    result: str,
    reader_id: str | None,
    location_name: str | None,
    reason: str | None,
):
    sql = """
    INSERT INTO usage_nfc_events (
      usage_id, tag_id, user_id, equipment_nfc_uid, action, result, reader_id, location_name, reason, occurred_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
    """
    cur.execute(
        sql,
        (usage_id, tag_id, user_id, equipment_nfc_uid, action, result, reader_id, location_name, reason),
    )


def pick_best_reader(tag_id: str, now: int):
    readers = tag_obs.get(tag_id, {})
    candidates = []

    for reader_id, observation in readers.items():
        if now - observation["recv_ts"] <= STALE_SEC:
            candidates.append((reader_id, observation["rssi"], observation["recv_ts"]))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates[0]


def _send_verification_email_for(user_id: int, email: str) -> None:
    """이메일 인증 토큰을 발급하고 인증 메일을 발송한다."""
    raw_token = create_action_token(
        purpose="email_verify",
        ttl_sec=EMAIL_VERIFY_TTL_SEC,
        user_id=user_id,
    )
    link = f"{APP_PUBLIC_URL}/verify-email?token={urllib.parse.quote(raw_token)}"
    send_verification_email(email, link)


@app.post("/auth/register")
def register(body: RegisterRequest):
    username = normalize_username(body.username)
    display_name = normalize_display_name(body.display_name)
    role = body.role.strip().lower()
    password = validate_password(body.password)
    email = normalize_email(body.email)
    position = normalize_optional_text(body.position, "position")
    department = normalize_optional_text(body.department, "department")

    if role not in ("admin", "staff"):
        raise HTTPException(400, "role은 admin 또는 staff여야 합니다.")
    if role == "staff" and not position:
        raise HTTPException(400, "staff 계정은 position이 필수입니다.")
    if role == "admin":
        position = None
        department = None

    password_hash = pwd.hash(password)

    sql = """
    INSERT INTO users (username, display_name, role, department, position, email,
                       password_hash, email_verified, is_active, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, %s, now())
    RETURNING user_id, username, display_name, role, department, position, email, email_verified, is_active
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    username,
                    display_name,
                    role,
                    department,
                    position,
                    email,
                    password_hash,
                    body.is_active,
                ),
            )
            row = cur.fetchone()
    except psycopg.errors.UniqueViolation as exc:
        # username 또는 email 중복 — 어느 쪽인지 제약 이름으로 구분한다.
        if "email" in str(getattr(exc, "diag", None) and exc.diag.constraint_name or "").lower():
            raise HTTPException(409, "이미 사용 중인 이메일입니다.")
        raise HTTPException(409, "이미 존재하는 username입니다.")
    except Exception:
        raise HTTPException(500, "회원가입 처리 중 데이터베이스 오류가 발생했습니다.")

    _send_verification_email_for(row[0], email)

    return {
        "ok": True,
        "email_verification_sent": True,
        "user": {
            **build_user_payload(row),
            "is_active": row[8],
        },
    }


@app.post("/auth/login")
def login(body: LoginRequest):
    username = normalize_username(body.username)
    requested_role = body.role.strip().lower()
    password = body.password
    if not password:
        raise HTTPException(400, "password는 비어 있을 수 없습니다.")
    if len(password) > 128:
        raise HTTPException(400, "password는 128자를 초과할 수 없습니다.")
    if requested_role not in ("admin", "staff"):
        raise HTTPException(400, "role은 admin 또는 staff여야 합니다.")

    sql = """
    SELECT user_id, username, display_name, role, department, position,
           email, email_verified, password_hash, is_active, token_version
    FROM users
    WHERE username = %s
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, (username,))
            row = cur.fetchone()
    except Exception:
        raise HTTPException(500, "로그인 처리 중 데이터베이스 오류가 발생했습니다.")

    if not row:
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")

    (
        user_id,
        db_username,
        display_name,
        role,
        department,
        position,
        email,
        email_verified,
        password_hash,
        is_active,
        token_version,
    ) = row

    if not is_active:
        raise HTTPException(403, "비활성화된 계정입니다.")
    if not password_hash or not pwd.verify(password, password_hash):
        # 비밀번호 미설정(Google 전용) 계정은 아이디/비밀번호 로그인을 허용하지 않는다.
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    if role != requested_role:
        raise HTTPException(403, "선택한 권한과 계정 권한이 일치하지 않습니다.")
    if not email_verified:
        raise HTTPException(
            403,
            detail={
                "code": "email_unverified",
                "message": "이메일 인증이 필요합니다. 메일함의 인증 링크를 확인해 주세요.",
                "email": email,
            },
        )

    token, expires_at = build_auth_token(user_id=user_id, token_version=token_version)

    return {
        "ok": True,
        "token": token,
        "expires_at": expires_at,
        "user": {
            "user_id": user_id,
            "username": db_username,
            "display_name": display_name,
            "role": role,
            "department": department,
            "position": position,
            "email": email,
            "email_verified": email_verified,
        },
    }


def _issue_session_for_user(user_id: int) -> dict:
    """user_id로 로그인 세션(bearer 토큰 + user)을 발급한다."""
    sql = """
    SELECT user_id, username, display_name, role, department, position,
           email, email_verified, is_active, token_version
    FROM users
    WHERE user_id = %s
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, (user_id,))
            row = cur.fetchone()
    except Exception:
        raise HTTPException(500, "세션 발급 중 데이터베이스 오류가 발생했습니다.")
    if not row:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    if not row[8]:
        raise HTTPException(403, "비활성화된 계정입니다.")
    token, expires_at = build_auth_token(user_id=row[0], token_version=row[9])
    return {
        "ok": True,
        "token": token,
        "expires_at": expires_at,
        "user": build_user_payload(row),
    }


@app.post("/auth/verify-email")
def verify_email(body: VerifyEmailRequest):
    consumed = consume_action_token(body.token.strip(), "email_verify")
    if not consumed or not consumed.get("user_id"):
        raise HTTPException(400, "유효하지 않거나 만료된 인증 링크입니다.")
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET email_verified = TRUE, updated_at = NOW() WHERE user_id = %s",
                (consumed["user_id"],),
            )
    except Exception:
        raise HTTPException(500, "이메일 인증 처리 중 데이터베이스 오류가 발생했습니다.")
    return {"ok": True, "message": "이메일 인증이 완료되었습니다. 이제 로그인할 수 있습니다."}


@app.post("/auth/resend-verification")
def resend_verification(body: ResendVerificationRequest):
    email = normalize_email(body.email)
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, email_verified FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
    except Exception:
        raise HTTPException(500, "요청 처리 중 데이터베이스 오류가 발생했습니다.")
    # 계정 존재 여부를 노출하지 않도록 항상 동일한 응답을 반환한다.
    if row and not row[1]:
        _send_verification_email_for(row[0], email)
    return {"ok": True, "message": "인증 메일을 다시 보냈습니다. 메일함을 확인해 주세요."}


@app.post("/auth/find-id")
def find_id(body: FindIdRequest):
    email = normalize_email(body.email)
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT username FROM users WHERE email = %s ORDER BY created_at",
                (email,),
            )
            usernames = [r[0] for r in cur.fetchall()]
    except Exception:
        raise HTTPException(500, "요청 처리 중 데이터베이스 오류가 발생했습니다.")
    if usernames:
        send_find_id_email(email, usernames)
    return {"ok": True, "message": "가입된 계정이 있다면 아이디를 메일로 보냈습니다."}


@app.post("/auth/forgot-password")
def forgot_password(body: ForgotPasswordRequest):
    email = normalize_email(body.email)
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
    except Exception:
        raise HTTPException(500, "요청 처리 중 데이터베이스 오류가 발생했습니다.")
    if row:
        raw_token = create_action_token(
            purpose="password_reset",
            ttl_sec=PASSWORD_RESET_TTL_SEC,
            user_id=row[0],
        )
        link = f"{APP_PUBLIC_URL}/reset-password?token={urllib.parse.quote(raw_token)}"
        send_reset_email(email, link)
    return {"ok": True, "message": "가입된 계정이 있다면 비밀번호 재설정 메일을 보냈습니다."}


@app.post("/auth/reset-password")
def reset_password(body: ResetPasswordRequest):
    password = validate_password(body.password)
    consumed = consume_action_token(body.token.strip(), "password_reset")
    if not consumed or not consumed.get("user_id"):
        raise HTTPException(400, "유효하지 않거나 만료된 재설정 링크입니다.")
    password_hash = pwd.hash(password)
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            # token_version 을 증가시켜 기존에 발급된 모든 세션 토큰을 무효화한다.
            cur.execute(
                """
                UPDATE users
                SET password_hash = %s,
                    token_version = token_version + 1,
                    updated_at = NOW()
                WHERE user_id = %s
                """,
                (password_hash, consumed["user_id"]),
            )
    except Exception:
        raise HTTPException(500, "비밀번호 재설정 중 데이터베이스 오류가 발생했습니다.")
    return {"ok": True, "message": "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해 주세요."}


# ---------------------------------------------------------------------------
# 마이페이지 / 계정 관리 (로그인 상태에서 본인 계정을 조회·변경)
# ---------------------------------------------------------------------------
def _verify_current_password(user_id: int, current_password: str) -> None:
    """본인 확인용으로 현재 비밀번호를 검증한다. 불일치 시 400."""
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
    except Exception:
        raise HTTPException(500, "계정 처리 중 데이터베이스 오류가 발생했습니다.")
    if not row or not row[0]:
        raise HTTPException(400, "비밀번호가 설정되어 있지 않습니다.")
    if not current_password or not pwd.verify(current_password, row[0]):
        raise HTTPException(400, "현재 비밀번호가 올바르지 않습니다.")


@app.get("/auth/me")
def auth_me(authorization: str | None = Header(default=None)):
    user = require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("SELECT created_at FROM users WHERE user_id = %s", (user["user_id"],))
            created_row = cur.fetchone()
            cur.execute(
                "SELECT 1 FROM user_oauth_identities WHERE user_id = %s AND provider = 'google' LIMIT 1",
                (user["user_id"],),
            )
            google_linked = cur.fetchone() is not None
    except Exception:
        raise HTTPException(500, "내 정보 조회 중 데이터베이스 오류가 발생했습니다.")
    return {
        "ok": True,
        "user": {
            **user,
            "created_at": created_row[0] if created_row else None,
            "google_linked": google_linked,
        },
    }


@app.post("/auth/change-password")
def change_password(
    body: ChangePasswordRequest,
    authorization: str | None = Header(default=None),
):
    user = require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    _verify_current_password(user["user_id"], body.current_password)
    new_hash = pwd.hash(validate_password(body.new_password))
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            # token_version++ 로 다른 기기의 기존 세션을 무효화한다.
            cur.execute(
                """
                UPDATE users
                SET password_hash = %s,
                    token_version = token_version + 1,
                    updated_at = NOW()
                WHERE user_id = %s
                """,
                (new_hash, user["user_id"]),
            )
    except Exception:
        raise HTTPException(500, "비밀번호 변경 중 데이터베이스 오류가 발생했습니다.")
    # 현재 창은 로그아웃되지 않도록 새 token_version 기준의 세션 토큰을 재발급한다.
    return _issue_session_for_user(user["user_id"])


@app.post("/auth/change-email")
def change_email(
    body: ChangeEmailRequest,
    authorization: str | None = Header(default=None),
):
    user = require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    _verify_current_password(user["user_id"], body.current_password)
    new_email = normalize_email(body.new_email)
    if new_email == (user.get("email") or "").strip().lower():
        raise HTTPException(400, "현재 이메일과 동일합니다.")
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET email = %s, email_verified = FALSE, updated_at = NOW()
                WHERE user_id = %s
                """,
                (new_email, user["user_id"]),
            )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "이미 사용 중인 이메일입니다.")
    except Exception:
        raise HTTPException(500, "이메일 변경 중 데이터베이스 오류가 발생했습니다.")
    _send_verification_email_for(user["user_id"], new_email)
    return {
        "ok": True,
        "message": "이메일이 변경되었습니다. 새 이메일로 보낸 인증 링크를 확인해 주세요.",
        "user": {**user, "email": new_email, "email_verified": False},
    }


@app.post("/auth/google/unlink")
def google_unlink(authorization: str | None = Header(default=None)):
    user = require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    # 모든 계정은 비밀번호 로그인이 가능하므로 연동 해제로 로그인 수단을 잃지 않는다.
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_oauth_identities WHERE user_id = %s AND provider = 'google'",
                (user["user_id"],),
            )
    except Exception:
        raise HTTPException(500, "Google 연동 해제 중 데이터베이스 오류가 발생했습니다.")
    return {"ok": True, "message": "Google 연동이 해제되었습니다.", "google_linked": False}


@app.post("/auth/withdraw")
def withdraw_account(
    body: WithdrawRequest,
    authorization: str | None = Header(default=None),
):
    user = require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    _verify_current_password(user["user_id"], body.current_password)
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            # 소프트 탈퇴: usage_history FK 보존을 위해 하드 삭제 대신 비활성화하고 세션을 무효화한다.
            cur.execute(
                """
                UPDATE users
                SET is_active = FALSE,
                    token_version = token_version + 1,
                    updated_at = NOW()
                WHERE user_id = %s
                """,
                (user["user_id"],),
            )
    except Exception:
        raise HTTPException(500, "회원 탈퇴 처리 중 데이터베이스 오류가 발생했습니다.")
    return {"ok": True, "message": "회원 탈퇴가 완료되었습니다."}


@app.get("/usage/me/history")
def usage_my_history(
    authorization: str | None = Header(default=None),
    limit: int = 100,
):
    user = require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    rows = query_my_usage_history_rows(user_id=user["user_id"], limit=limit)
    items = [build_my_usage_history_item(row) for row in rows]
    return {"ok": True, "count": len(items), "items": items}


# ---------------------------------------------------------------------------
# Google OAuth 2.0 (authorization code / redirect)
# ---------------------------------------------------------------------------


def _frontend_redirect(path: str, fragment_params: dict) -> RedirectResponse:
    fragment = urllib.parse.urlencode(fragment_params)
    return RedirectResponse(url=f"{APP_PUBLIC_URL}{path}#{fragment}", status_code=302)


@app.get("/auth/google/start")
def google_start(mode: str = Query(default="login")):
    if not google_oauth.is_google_configured():
        raise HTTPException(503, "Google 로그인이 설정되지 않았습니다.")
    mode = mode if mode in ("login", "signup") else "login"
    state = google_oauth.sign_state(mode)
    return RedirectResponse(url=google_oauth.build_authorization_url(state), status_code=302)


@app.get("/auth/google/callback")
def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    if error or not code or not state:
        return _frontend_redirect("/", {"oauth_error": error or "google_login_failed"})

    google_oauth.verify_state(state)
    info = google_oauth.exchange_code(code)
    provider = "google"

    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            # 1) 이미 연동된 신원인가?
            cur.execute(
                "SELECT user_id FROM user_oauth_identities WHERE provider = %s AND provider_subject = %s",
                (provider, info["sub"]),
            )
            identity = cur.fetchone()
            linked_user_id = identity[0] if identity else None

            # 2) 미연동이면, 동일 이메일의 인증된 계정에 자동 연동한다.
            if linked_user_id is None:
                cur.execute(
                    "SELECT user_id FROM users WHERE email = %s AND email_verified = TRUE",
                    (info["email"],),
                )
                existing = cur.fetchone()
                if existing:
                    linked_user_id = existing[0]
                    cur.execute(
                        """
                        INSERT INTO user_oauth_identities (user_id, provider, provider_subject, email)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (provider, provider_subject) DO NOTHING
                        """,
                        (linked_user_id, provider, info["sub"], info["email"]),
                    )
    except Exception:
        return _frontend_redirect("/", {"oauth_error": "google_login_failed"})

    if linked_user_id is not None:
        # 로그인 성립 → 일회성 handoff code 발급, 토큰은 URL에 직접 노출하지 않는다.
        handoff = create_action_token(
            purpose="oauth_handoff",
            ttl_sec=OAUTH_HANDOFF_TTL_SEC,
            user_id=linked_user_id,
        )
        return _frontend_redirect("/auth/callback", {"code": handoff})

    # 3) 계정 없음 → pending 토큰 발급 후 추가정보 입력 화면으로 유도한다.
    pending = create_action_token(
        purpose="oauth_pending",
        ttl_sec=OAUTH_PENDING_TTL_SEC,
        payload={"provider": provider, "sub": info["sub"], "email": info["email"], "name": info["name"]},
    )
    return _frontend_redirect(
        "/signup/complete",
        {"pending": pending, "email": info["email"], "name": info["name"]},
    )


@app.post("/auth/session/exchange")
def session_exchange(body: SessionExchangeRequest):
    consumed = consume_action_token(body.code.strip(), "oauth_handoff")
    if not consumed or not consumed.get("user_id"):
        raise HTTPException(400, "유효하지 않거나 만료된 로그인 코드입니다.")
    return _issue_session_for_user(consumed["user_id"])


@app.post("/auth/google/complete")
def google_complete(body: GoogleCompleteRequest):
    consumed = consume_action_token(body.pending_token.strip(), "oauth_pending")
    payload = consumed.get("payload") if consumed else None
    if not payload or not payload.get("email") or not payload.get("sub"):
        raise HTTPException(400, "유효하지 않거나 만료된 가입 요청입니다. 다시 시도해 주세요.")

    provider = payload.get("provider", "google")
    google_email = normalize_email(payload["email"])
    google_email_verified = True  # Google userinfo email은 신뢰 가능하다고 간주

    username = normalize_username(body.username)
    display_name = normalize_display_name(body.display_name or payload.get("name") or username)
    role = (body.role or "staff").strip().lower()
    position = normalize_optional_text(body.position, "position")
    department = normalize_optional_text(body.department, "department")

    if role not in ("admin", "staff"):
        raise HTTPException(400, "role은 admin 또는 staff여야 합니다.")
    if role == "staff" and not position:
        raise HTTPException(400, "staff 계정은 position이 필수입니다.")
    if role == "admin":
        position = None
        department = None

    # Google 첫 가입도 비밀번호를 필수로 받는다(아이디/비밀번호 로그인도 가능하도록).
    if not body.password:
        raise HTTPException(400, "비밀번호를 입력해 주세요.")
    password_hash = pwd.hash(validate_password(body.password))

    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username, display_name, role, department, position, email,
                                   password_hash, email_verified, is_active, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, now())
                RETURNING user_id
                """,
                (
                    username,
                    display_name,
                    role,
                    department,
                    position,
                    google_email,
                    password_hash,
                    google_email_verified,
                ),
            )
            new_user_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO user_oauth_identities (user_id, provider, provider_subject, email)
                VALUES (%s, %s, %s, %s)
                """,
                (new_user_id, provider, payload["sub"], google_email),
            )
    except psycopg.errors.UniqueViolation as exc:
        constraint = str(getattr(exc, "diag", None) and exc.diag.constraint_name or "").lower()
        if "email" in constraint:
            raise HTTPException(409, "이미 사용 중인 이메일입니다.")
        if "provider_subject" in constraint:
            raise HTTPException(409, "이미 연동된 Google 계정입니다.")
        raise HTTPException(409, "이미 존재하는 username입니다.")
    except Exception:
        raise HTTPException(500, "가입 처리 중 데이터베이스 오류가 발생했습니다.")

    return _issue_session_for_user(new_user_id)


@app.post("/ingest")
def ingest(payload: Payload):
    now = int(time.time())
    reader_id = payload.reader_id
    reader_locations = load_reader_location_map()
    upsert_readers_from_ingest({reader_id})
    db_updates: dict[str, tuple[str, int | None, int]] = {}

    last_tag_id = None
    last_best = None

    for observation in payload.observations:
        tag_id = observation.tag_id
        last_tag_id = tag_id

        tag_obs.setdefault(tag_id, {})
        tag_obs[tag_id][reader_id] = {
            "rssi": observation.rssi,
            "count": observation.count,
            "last_seen": observation.last_seen,
            "recv_ts": now,
        }

        best = pick_best_reader(tag_id, now)
        last_best = best
        if best is None:
            continue

        best_reader_id, best_rssi, _recv_ts = best
        state = tag_state.setdefault(
            tag_id,
            {
                "current_reader": None,
                "current_rssi": None,
                "candidate_reader": None,
                "candidate_since": None,
                "updated_at": None,
            },
        )

        current_reader = state["current_reader"]
        if current_reader is None:
            state["current_reader"] = best_reader_id
            state["current_rssi"] = best_rssi
            state["updated_at"] = now
            state["candidate_reader"] = None
            state["candidate_since"] = None
            db_updates[tag_id] = (best_reader_id, best_rssi, now)
            continue

        current_observation = tag_obs[tag_id].get(current_reader)
        current_rssi = (
            current_observation["rssi"]
            if current_observation and (now - current_observation["recv_ts"] <= STALE_SEC)
            else -999
        )

        if best_reader_id == current_reader:
            state["current_rssi"] = best_rssi
            state["candidate_reader"] = None
            state["candidate_since"] = None
            state["updated_at"] = now
            continue

        if best_rssi - current_rssi < HYST_DB:
            state["candidate_reader"] = None
            state["candidate_since"] = None
            state["current_rssi"] = current_rssi
            state["updated_at"] = now
            continue

        if state["candidate_reader"] != best_reader_id:
            state["candidate_reader"] = best_reader_id
            state["candidate_since"] = now
            continue

        if state["candidate_since"] and (now - state["candidate_since"] >= DWELL_SEC):
            state["current_reader"] = best_reader_id
            state["current_rssi"] = best_rssi
            state["updated_at"] = now
            state["candidate_reader"] = None
            state["candidate_since"] = None
            db_updates[tag_id] = (best_reader_id, best_rssi, now)

    insert_location_history(db_updates)
    cache_location_updates(db_updates, reader_locations=reader_locations)
    mark_tags_seen({obs.tag_id for obs in payload.observations}, now)

    if last_tag_id is not None and last_best is not None:
        print(f"[tag ID]\n{last_tag_id}")
        print("\n[readers]")
        for current_reader_id, observation in tag_obs.get(last_tag_id, {}).items():
            print(f"{current_reader_id}: rssi = {observation['rssi']}")
        print("\n[best]\n", last_best[0], ": ", last_best[1])

    return {"ok": True}


@app.get("/where/{tag_id}")
def where(tag_id: str, authorization: str | None = Header(default=None)):
    require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    snapshot = resolve_tag_location_snapshot(tag_id)
    if not snapshot:
        return {"ok": False, "reason": "unknown"}

    return {
        "ok": True,
        "tag_id": tag_id,
        "reader_id": snapshot["reader_id"],
        "location": snapshot["location"],
        "rssi": snapshot["rssi"],
        "updated_at": snapshot["updated_at"],
        "is_stale": snapshot["is_stale"],
    }


@app.get("/admin/readers")
def list_admin_readers(
    floor: int | None = Query(default=None, ge=1, le=5),
    authorization: str | None = Header(default=None),
):
    require_authenticated_user(authorization, allowed_roles={"admin"})
    try:
        items = load_readers_for_admin(floor)
    except Exception:
        raise HTTPException(500, "리더 목록 조회 중 데이터베이스 오류가 발생했습니다.")

    return {"ok": True, "count": len(items), "items": items}


@app.put("/admin/readers/{reader_id}/map-position")
def set_reader_map_position(
    reader_id: str,
    body: ReaderMapPositionRequest,
    authorization: str | None = Header(default=None),
):
    require_authenticated_user(authorization, allowed_roles={"admin"})
    try:
        item = update_reader_map_position(
            reader_id,
            body.floor,
            body.map_x,
            body.map_y,
            body.location_name,
        )
    except Exception:
        raise HTTPException(500, "리더 좌표 저장 중 데이터베이스 오류가 발생했습니다.")

    if not item:
        raise HTTPException(404, "리더를 찾을 수 없습니다.")

    return {"ok": True, "item": item}


@app.get("/admin/nfc-mappings")
def list_nfc_mappings(authorization: str | None = Header(default=None)):
    require_authenticated_user(authorization, allowed_roles={"admin"})
    sql = """
    SELECT
      t.tag_id,
      t.equipment_name,
      t.equipment_type,
      t.serial_number,
      t.nfc_tag_uid,
      t.asset_status,
      t.is_active
    FROM tags t
    WHERE t.is_active = TRUE
    ORDER BY t.equipment_name ASC, t.tag_id ASC
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception:
        raise HTTPException(500, "NFC 매핑 목록 조회 중 데이터베이스 오류가 발생했습니다.")

    now = int(time.time())
    reader_locations = load_reader_location_map()
    items = []
    for row in rows:
        location_snapshot = resolve_tag_location_snapshot(row[0], now=now, reader_locations=reader_locations)
        items.append(
            {
                "tag_id": row[0],
                "equipment_name": row[1],
                "equipment_type": row[2],
                "serial_number": row[3],
                "nfc_token": row[4],
                "asset_status": row[5],
                "is_active": row[6],
                "reader_id": location_snapshot["reader_id"] if location_snapshot else None,
                "location": location_snapshot["location"] if location_snapshot else None,
                "updated_at": location_snapshot["updated_at"] if location_snapshot else None,
                "is_stale": location_snapshot["is_stale"] if location_snapshot else True,
            }
        )

    return {
        "ok": True,
        "count": len(items),
        "items": items,
    }


@app.post("/admin/nfc-mappings")
def upsert_nfc_mapping(
    body: NfcMappingUpsertRequest,
    authorization: str | None = Header(default=None),
):
    require_authenticated_user(authorization, allowed_roles={"admin"})
    tag_id = body.tag_id.strip()
    token = normalize_nfc_token(body.nfc_token)
    if not tag_id:
        raise HTTPException(400, "tag_id는 필수입니다.")

    sql = """
    UPDATE tags
    SET nfc_tag_uid = %s, updated_at = now()
    WHERE tag_id = %s
    RETURNING tag_id, equipment_name, equipment_type, serial_number, nfc_tag_uid, asset_status
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, (token, tag_id))
            row = cur.fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "이미 다른 장비에 매핑된 NFC 토큰입니다.")
    except Exception:
        raise HTTPException(500, "NFC 매핑 저장 중 데이터베이스 오류가 발생했습니다.")

    if not row:
        raise HTTPException(404, "장비를 찾을 수 없습니다.")

    return {
        "ok": True,
        "item": {
            "tag_id": row[0],
            "equipment_name": row[1],
            "equipment_type": row[2],
            "serial_number": row[3],
            "nfc_token": row[4],
            "asset_status": row[5],
        },
    }


@app.delete("/admin/nfc-mappings/{tag_id}")
def remove_nfc_mapping(tag_id: str, authorization: str | None = Header(default=None)):
    require_authenticated_user(authorization, allowed_roles={"admin"})
    clean_tag_id = tag_id.strip()
    if not clean_tag_id:
        raise HTTPException(400, "tag_id는 필수입니다.")

    sql = """
    UPDATE tags
    SET nfc_tag_uid = NULL, updated_at = now()
    WHERE tag_id = %s
    RETURNING tag_id
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, (clean_tag_id,))
            row = cur.fetchone()
    except Exception:
        raise HTTPException(500, "NFC 매핑 해제 중 데이터베이스 오류가 발생했습니다.")

    if not row:
        raise HTTPException(404, "장비를 찾을 수 없습니다.")

    return {
        "ok": True,
        "tag_id": row[0],
    }


@app.get("/nfc/{token}")
def get_nfc_equipment(token: str, authorization: str | None = Header(default=None)):
    require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    clean_token = normalize_nfc_token(token)

    sql = """
    SELECT
      t.tag_id,
      t.equipment_name,
      t.equipment_type,
      t.serial_number,
      t.nfc_tag_uid,
      t.asset_status,
      t.current_holder_user_id,
      COALESCE(u.display_name, u.username) AS current_holder_name,
      t.current_usage_id
    FROM tags t
    LEFT JOIN users u ON u.user_id = t.current_holder_user_id
    WHERE t.nfc_tag_uid = %s
      AND t.is_active = TRUE
    LIMIT 1
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, (clean_token,))
            row = cur.fetchone()
    except Exception:
        raise HTTPException(500, "NFC 장비 조회 중 데이터베이스 오류가 발생했습니다.")

    if not row:
        raise HTTPException(404, "매핑되지 않은 NFC 태그입니다.")

    location_snapshot = resolve_tag_location_snapshot(row[0])
    return {
        "ok": True,
        "item": {
            "tag_id": row[0],
            "equipment_name": row[1],
            "equipment_type": row[2],
            "serial_number": row[3],
            "nfc_token": row[4],
            "asset_status": row[5],
            "current_holder_user_id": row[6],
            "current_holder_name": row[7],
            "current_usage_id": row[8],
            "reader_id": location_snapshot["reader_id"] if location_snapshot else None,
            "location": location_snapshot["location"] if location_snapshot else None,
            "updated_at": location_snapshot["updated_at"] if location_snapshot else None,
            "is_stale": location_snapshot["is_stale"] if location_snapshot else True,
        },
    }


@app.post("/usage/checkout")
def usage_checkout(body: NfcUsageActionRequest, authorization: str | None = Header(default=None)):
    actor = require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    token = normalize_nfc_token(body.nfc_token)
    now = dt.datetime.now(dt.UTC)

    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            tag_row = fetch_tag_by_nfc_token(cur, token)
            if not tag_row or not tag_row[9]:
                raise HTTPException(404, "매핑된 장비를 찾을 수 없습니다.")

            (
                tag_id,
                equipment_name,
                equipment_type,
                serial_number,
                nfc_uid,
                asset_status,
                current_holder_user_id,
                current_holder_name,
                current_usage_id,
                _is_active,
            ) = tag_row

            location_snapshot = resolve_tag_location_snapshot(tag_id)
            reader_id = location_snapshot["reader_id"] if location_snapshot else None
            location_name = location_snapshot["location"] if location_snapshot else None

            if asset_status == "checked_out":
                current_holder = current_holder_name or current_holder_user_id or "알 수 없음"
                raise HTTPException(409, f"이미 사용 중인 장비입니다. 현재 사용자: {current_holder}")
            if asset_status != "available":
                raise HTTPException(409, f"현재 상태({asset_status})에서는 사용 시작할 수 없습니다.")

            cur.execute(
                """
                INSERT INTO usage_history (
                  usage_status,
                  user_id,
                  user_name,
                  user_position,
                  user_department,
                  tag_id,
                  equipment_name,
                  equipment_type,
                  equipment_serial_number,
                  equipment_nfc_uid,
                  checkout_method,
                  checkout_reader_id,
                  checkout_location,
                  checkout_at,
                  created_at,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                RETURNING usage_id
                """,
                (
                    "checked_out",
                    actor["user_id"],
                    actor["display_name"],
                    actor["position"],
                    actor["department"],
                    tag_id,
                    equipment_name,
                    equipment_type,
                    serial_number,
                    nfc_uid,
                    "nfc",
                    reader_id,
                    location_name,
                    now,
                ),
            )
            usage_id = cur.fetchone()[0]

            cur.execute(
                """
                UPDATE tags
                SET
                  asset_status = 'checked_out',
                  current_holder_user_id = %s,
                  current_usage_id = %s,
                  last_checkout_at = %s,
                  updated_at = now()
                WHERE tag_id = %s
                """,
                (actor["user_id"], usage_id, now, tag_id),
            )

            insert_nfc_event(
                cur,
                usage_id=usage_id,
                tag_id=tag_id,
                user_id=actor["user_id"],
                equipment_nfc_uid=nfc_uid,
                action="checkout",
                result="accepted",
                reader_id=reader_id,
                location_name=location_name,
                reason=None,
            )
            conn.commit()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "장비 사용 시작 처리 중 데이터베이스 오류가 발생했습니다.")

    return {
        "ok": True,
        "usage_id": usage_id,
        "tag_id": tag_id,
        "asset_status": "checked_out",
        "current_holder_user_id": actor["user_id"],
        "current_holder_name": actor["display_name"],
    }


@app.post("/usage/return")
def usage_return(body: NfcUsageActionRequest, authorization: str | None = Header(default=None)):
    actor = require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    token = normalize_nfc_token(body.nfc_token)
    now = dt.datetime.now(dt.UTC)

    blockchain_result = None

    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            tag_row = fetch_tag_by_nfc_token(cur, token)
            if not tag_row or not tag_row[9]:
                raise HTTPException(404, "매핑된 장비를 찾을 수 없습니다.")

            (
                tag_id,
                _equipment_name,
                _equipment_type,
                _serial_number,
                nfc_uid,
                asset_status,
                current_holder_user_id,
                current_holder_name,
                current_usage_id,
                _is_active,
            ) = tag_row

            location_snapshot = resolve_tag_location_snapshot(tag_id)
            reader_id = location_snapshot["reader_id"] if location_snapshot else None
            location_name = location_snapshot["location"] if location_snapshot else None

            if asset_status != "checked_out" or not current_usage_id:
                raise HTTPException(409, "현재 사용 중인 장비가 아닙니다.")
            if actor["role"] != "admin" and current_holder_user_id != actor["user_id"]:
                raise HTTPException(403, "현재 대여 중인 사용자만 반납할 수 있습니다.")

            cur.execute(
                """
                UPDATE usage_history
                SET
                  usage_status = 'returned',
                  returned_by_user_id = %s,
                  returned_by_name = %s,
                  returned_by_position = %s,
                  returned_by_department = %s,
                  return_method = 'nfc',
                  return_reader_id = %s,
                  return_location = %s,
                  returned_at = %s,
                  updated_at = now()
                WHERE usage_id = %s
                """,
                (
                    actor["user_id"],
                    actor["display_name"],
                    actor["position"],
                    actor["department"],
                    reader_id,
                    location_name,
                    now,
                    current_usage_id,
                ),
            )

            cur.execute(
                """
                UPDATE tags
                SET
                  asset_status = 'available',
                  current_holder_user_id = NULL,
                  current_usage_id = NULL,
                  last_returned_at = %s,
                  updated_at = now()
                WHERE tag_id = %s
                """,
                (now, tag_id),
            )

            insert_nfc_event(
                cur,
                usage_id=current_usage_id,
                tag_id=tag_id,
                user_id=actor["user_id"],
                equipment_nfc_uid=nfc_uid,
                action="return",
                result="accepted",
                reader_id=reader_id,
                location_name=location_name,
                reason=None,
            )
            conn.commit()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "장비 사용 종료 처리 중 데이터베이스 오류가 발생했습니다.")

    try:
        blockchain_result = anchor_usage_record_to_chain(current_usage_id)
    except Exception:
        blockchain_result = {
            "ok": False,
            "status": "record_error",
            "detail": "반납 후 온체인 기록 중 오류가 발생했습니다.",
        }
    if blockchain_result.get("ok"):
        persist_usage_chain_anchor_metadata(current_usage_id, blockchain_result)

    return {
        "ok": True,
        "usage_id": current_usage_id,
        "tag_id": tag_id,
        "asset_status": "available",
        "current_holder_user_id": None,
        "current_holder_name": None,
        "blockchain": blockchain_result,
    }


@app.get("/rtls/live")
def rtls_live(authorization: str | None = Header(default=None)):
    user = require_authenticated_user(authorization, allowed_roles={"admin", "staff"})
    is_admin = user["role"] == "admin"
    now = int(time.time())
    reader_locations = load_reader_location_map()
    cached_locations = load_all_cached_tag_locations()
    db_locations = load_latest_db_tag_locations()

    merged_locations = dict(db_locations)
    merged_locations.update(cached_locations)

    missing_cache_keys = set(db_locations.keys()) - set(cached_locations.keys())
    if missing_cache_keys:
        cache_location_updates(
            {
                tag_id: (
                    location["reader_id"],
                    None,
                    location["changed_at"],
                )
                for tag_id, location in db_locations.items()
                if tag_id in missing_cache_keys
                and location.get("reader_id")
                and isinstance(location.get("changed_at"), int)
            },
            reader_locations=reader_locations,
        )

    # 전체 활성 태그 로스터 = (등록된 활성 태그) ∪ (위치가 잡힌 태그)
    roster_tag_ids = load_active_tag_ids() | set(merged_locations.keys())
    tag_metadata = load_tag_metadata(roster_tag_ids)
    tag_last_seen = load_tags_last_seen(roster_tag_ids)

    items = []
    for tag_id in roster_tag_ids:
        metadata = tag_metadata.get(tag_id, {})
        cached_location = merged_locations.get(tag_id) or {}
        reader_id = cached_location.get("reader_id")

        # last-seen: Redis 값 우선, 없으면 위치 변경 시각으로 폴백
        seen_epoch = tag_last_seen.get(tag_id)
        changed_at_epoch = cached_location.get("changed_at")
        effective_seen = seen_epoch if seen_epoch is not None else changed_at_epoch
        is_online = isinstance(effective_seen, int) and (now - effective_seen) <= TAG_OFFLINE_SEC

        location = None
        if reader_id:
            location = cached_location.get("location") or reader_locations.get(
                reader_id, READER_LOCATION.get(reader_id, reader_id)
            )

        item = {
            "tag_id": tag_id,
            "equipment_name": metadata.get("equipment_name"),
            "equipment_type": metadata.get("equipment_type"),
            "serial_number": metadata.get("serial_number"),
            "asset_status": metadata.get("asset_status") or "available",
            "current_holder_user_id": metadata.get("current_holder_user_id"),
            "current_holder_name": metadata.get("current_holder_name"),
            "reader_id": reader_id,
            "location": location,
            "rssi": None,
            "updated_at": changed_at_epoch,
            "last_seen": effective_seen,
            "is_online": is_online,
            "is_stale": not is_online,
        }
        if is_admin:
            item["is_real_hardware"] = metadata.get("is_real_hardware", True)
        items.append(item)

    items.sort(
        key=lambda item: (item["is_online"], item.get("last_seen") or 0),
        reverse=True,
    )

    readers = load_readers_with_status(now, READER_OFFLINE_SEC)
    if not is_admin:
        for reader in readers:
            reader.pop("is_real_hardware", None)
    readers_online = sum(1 for r in readers if r["is_online"])
    tags_online = sum(1 for item in items if item["is_online"])

    return {
        "ok": True,
        "count": len(items),
        "ts": now,
        "items": items,
        "readers": readers,
        "readers_online": readers_online,
        "readers_total": len(readers),
        "tags_online": tags_online,
        "tags_total": len(items),
    }


@app.get("/usage/history/blockchain-demo")
def usage_history_blockchain_demo(authorization: str | None = Header(default=None)):
    require_authenticated_user(authorization, allowed_roles={"admin"})
    return build_blockchain_demo_history()


@app.get("/usage/history")
def usage_history(
    authorization: str | None = Header(default=None),
    user: str | None = None,
    equipment: str | None = None,
    checkout_location: str | None = None,
    return_location: str | None = None,
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    sort_by: str = "time",
    sort_order: str = "desc",
    limit: int = 200,
    include_blockchain: bool = False,
):
    require_authenticated_user(authorization, allowed_roles={"admin"})
    safe_limit, rows = query_usage_history_rows(
        user=user,
        equipment=equipment,
        checkout_location=checkout_location,
        return_location=return_location,
        date=date,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        max_limit=200 if include_blockchain else 1000,
    )

    integrity_results = {}
    integrity_summary = None
    if include_blockchain:
        integrity_results, integrity_summary = verify_usage_history_integrity(rows)

    items = [
        build_usage_history_item(
            row,
            blockchain=integrity_results.get(row[0]) if include_blockchain else None,
        )
        for row in rows
    ]

    return {
        "ok": True,
        "count": len(items),
        "filters": {
            "user": user,
            "equipment": equipment,
            "checkout_location": checkout_location,
            "return_location": return_location,
            "date": date,
            "start_date": start_date,
            "end_date": end_date,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "limit": safe_limit,
            "include_blockchain": include_blockchain,
        },
        "integrity_summary": integrity_summary,
        "items": items,
    }
