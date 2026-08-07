import contextlib
import json
import time

import psycopg
from fastapi import HTTPException

try:
    from backend.settings import (
        DATABASE_URL,
        READER_LOCATION,
        REDIS_CONNECT_TIMEOUT_SEC,
        REDIS_LOCATION_KEY_PREFIX,
        REDIS_RETRY_COOLDOWN_SEC,
        REDIS_URL,
        STALE_SEC,
    )
except ModuleNotFoundError as exc:
    if not exc.name or not exc.name.startswith("backend"):
        raise
    from settings import (
        DATABASE_URL,
        READER_LOCATION,
        REDIS_CONNECT_TIMEOUT_SEC,
        REDIS_LOCATION_KEY_PREFIX,
        REDIS_RETRY_COOLDOWN_SEC,
        REDIS_URL,
        STALE_SEC,
    )

try:
    import redis
except Exception:
    redis = None

redis_client = None
redis_retry_after = 0.0


def get_redis_client():
    global redis_client, redis_retry_after

    if redis is None:
        return None
    if redis_client is not None:
        return redis_client
    if time.time() < redis_retry_after:
        return None

    try:
        client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SEC,
            socket_timeout=REDIS_CONNECT_TIMEOUT_SEC,
        )
        client.ping()
        redis_client = client
        return redis_client
    except Exception:
        redis_retry_after = time.time() + REDIS_RETRY_COOLDOWN_SEC
        redis_client = None
        return None


def get_tag_location_cache_key(tag_id: str) -> str:
    return f"{REDIS_LOCATION_KEY_PREFIX}{tag_id}:current"


def get_tag_seen_cache_key(tag_id: str) -> str:
    return f"{REDIS_LOCATION_KEY_PREFIX}{tag_id}:seen"


def mark_tags_seen(tag_ids: set[str], seen_epoch: int) -> None:
    if not tag_ids:
        return
    client = get_redis_client()
    if client is None:
        return
    with contextlib.suppress(Exception):
        pipe = client.pipeline()
        for tag_id in tag_ids:
            pipe.set(get_tag_seen_cache_key(tag_id), seen_epoch)
        pipe.execute()


def load_tags_last_seen(tag_ids: set[str]) -> dict[str, int]:
    if not tag_ids:
        return {}
    client = get_redis_client()
    if client is None:
        return {}
    keys = {tag_id: get_tag_seen_cache_key(tag_id) for tag_id in tag_ids}
    try:
        pipe = client.pipeline()
        for key in keys.values():
            pipe.get(key)
        raw_values = pipe.execute()
    except Exception:
        return {}
    results: dict[str, int] = {}
    for tag_id, raw in zip(keys.keys(), raw_values, strict=True):
        if raw is None:
            continue
        try:
            results[tag_id] = int(raw)
        except (TypeError, ValueError):
            continue
    return results


def read_cached_tag_location(tag_id: str) -> dict | None:
    client = get_redis_client()
    if client is None:
        return None

    try:
        raw = client.get(get_tag_location_cache_key(tag_id))
    except Exception:
        return None

    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None


def load_cached_tag_locations(tag_ids: set[str]) -> dict[str, dict]:
    if not tag_ids:
        return {}

    client = get_redis_client()
    if client is None:
        return {}

    keys = {tag_id: get_tag_location_cache_key(tag_id) for tag_id in tag_ids}
    try:
        pipe = client.pipeline()
        for key in keys.values():
            pipe.get(key)
        raw_values = pipe.execute()
    except Exception:
        return {}

    results: dict[str, dict] = {}
    for tag_id, raw in zip(keys.keys(), raw_values, strict=True):
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            results[tag_id] = payload
    return results


def load_all_cached_tag_locations() -> dict[str, dict]:
    client = get_redis_client()
    if client is None:
        return {}

    try:
        keys = list(client.scan_iter(match=f"{REDIS_LOCATION_KEY_PREFIX}*:current"))
    except Exception:
        return {}

    if not keys:
        return {}

    try:
        raw_values = client.mget(keys)
    except Exception:
        return {}

    results: dict[str, dict] = {}
    for raw in raw_values:
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        tag_id = payload.get("tag_id")
        if isinstance(tag_id, str) and tag_id:
            results[tag_id] = payload
    return results


def fetch_latest_db_tag_location(tag_id: str) -> dict | None:
    sql = """
    SELECT
      h.tag_id,
      h.reader_id,
      COALESCE(r.location_name, h.reader_id) AS location,
      EXTRACT(EPOCH FROM h.decided_at)::BIGINT AS updated_at_epoch
    FROM tag_state_history h
    LEFT JOIN readers r ON r.reader_id = h.reader_id
    WHERE h.tag_id = %s
    ORDER BY h.decided_at DESC
    LIMIT 1
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, (tag_id,))
            row = cur.fetchone()
    except Exception:
        raise HTTPException(500, "현재 위치 조회 중 데이터베이스 오류가 발생했습니다.")

    if not row:
        return None

    return {
        "tag_id": row[0],
        "reader_id": row[1],
        "location": row[2],
        "changed_at": row[3],
    }


def load_latest_db_tag_locations() -> dict[str, dict]:
    sql = """
    SELECT DISTINCT ON (h.tag_id)
      h.tag_id,
      h.reader_id,
      COALESCE(r.location_name, h.reader_id) AS location,
      EXTRACT(EPOCH FROM h.decided_at)::BIGINT AS updated_at_epoch
    FROM tag_state_history h
    LEFT JOIN readers r ON r.reader_id = h.reader_id
    ORDER BY h.tag_id, h.decided_at DESC
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception:
        raise HTTPException(500, "실시간 위치 목록 조회 중 데이터베이스 오류가 발생했습니다.")

    return {
        row[0]: {
            "tag_id": row[0],
            "reader_id": row[1],
            "location": row[2],
            "changed_at": row[3],
        }
        for row in rows
    }


def cache_tag_location_snapshot(
    tag_id: str,
    reader_id: str,
    changed_at_epoch: int,
    reader_locations: dict[str, str] | None = None,
) -> None:
    client = get_redis_client()
    if client is None:
        return

    locations = reader_locations or READER_LOCATION
    payload = {
        "tag_id": tag_id,
        "reader_id": reader_id,
        "location": locations.get(reader_id, READER_LOCATION.get(reader_id, reader_id)),
        "changed_at": changed_at_epoch,
    }
    with contextlib.suppress(Exception):
        client.set(get_tag_location_cache_key(tag_id), json.dumps(payload, ensure_ascii=False))


def cache_location_updates(
    updates: dict[str, tuple[str, int | None, int]],
    reader_locations: dict[str, str] | None = None,
) -> None:
    for tag_id, (reader_id, _last_rssi, changed_at_epoch) in updates.items():
        cache_tag_location_snapshot(
            tag_id,
            reader_id,
            changed_at_epoch,
            reader_locations=reader_locations,
        )


def upsert_readers_from_ingest(reader_ids: set[str]) -> None:
    if not reader_ids:
        return

    sql = """
    INSERT INTO readers (reader_id, location_name, is_active, last_seen_at, created_at)
    VALUES (%s, %s, TRUE, now(), now())
    ON CONFLICT (reader_id) DO UPDATE
    SET
      location_name = COALESCE(readers.location_name, EXCLUDED.location_name),
      is_active = TRUE,
      last_seen_at = now()
    """
    with contextlib.suppress(Exception):
        rows = [(reader_id, READER_LOCATION.get(reader_id, reader_id)) for reader_id in reader_ids]
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.executemany(sql, rows)


def insert_location_history(updates: dict[str, tuple[str, int | None, int]]) -> None:
    if not updates:
        return

    known_tag_ids: set[str] = set()
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("SELECT tag_id FROM tags WHERE tag_id = ANY(%s)", (list(updates.keys()),))
            known_tag_ids = {row[0] for row in cur.fetchall()}
    except Exception:
        return

    if not known_tag_ids:
        return

    sql = """
    INSERT INTO tag_state_history (tag_id, reader_id, rssi, decided_at)
    VALUES (%s, %s, %s, to_timestamp(%s))
    """
    rows = [
        (tag_id, reader_id, last_rssi, changed_at_epoch)
        for tag_id, (reader_id, last_rssi, changed_at_epoch) in updates.items()
        if tag_id in known_tag_ids
    ]
    if not rows:
        return
    with contextlib.suppress(Exception), psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.executemany(sql, rows)


def load_reader_location_map() -> dict[str, str]:
    sql = """
    SELECT reader_id, COALESCE(location_name, reader_id) AS location
    FROM readers
    ORDER BY reader_id
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception:
        return dict(READER_LOCATION)

    mapping = dict(rows)
    if not mapping:
        return dict(READER_LOCATION)
    return mapping


def load_readers_with_status(now_epoch: int, offline_sec: int) -> list[dict]:
    sql = """
    SELECT
      reader_id,
      COALESCE(location_name, reader_id) AS location,
      EXTRACT(EPOCH FROM last_seen_at)::bigint AS last_seen,
      floor,
      map_x,
      map_y,
      is_real_hardware
    FROM readers
    ORDER BY reader_id
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception:
        return []

    readers: list[dict] = []
    for reader_id, location, last_seen, floor, map_x, map_y, is_real_hardware in rows:
        last_seen_int = int(last_seen) if last_seen is not None else None
        is_online = last_seen_int is not None and (now_epoch - last_seen_int) <= offline_sec
        readers.append(
            {
                "reader_id": reader_id,
                "location": location,
                "last_seen": last_seen_int,
                "is_online": is_online,
                "floor": floor,
                "map_x": float(map_x) if map_x is not None else None,
                "map_y": float(map_y) if map_y is not None else None,
                "is_real_hardware": is_real_hardware,
            }
        )
    return readers


def load_readers_for_admin(floor: int | None = None) -> list[dict]:
    sql = """
    SELECT reader_id, location_name, floor, map_x, map_y, is_active, is_real_hardware, last_seen_at
    FROM readers
    """
    params: tuple = ()
    if floor is not None:
        sql += " WHERE floor = %s"
        params = (floor,)
    sql += " ORDER BY reader_id"

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {
            "reader_id": reader_id,
            "location_name": location_name,
            "floor": floor_value,
            "map_x": float(map_x) if map_x is not None else None,
            "map_y": float(map_y) if map_y is not None else None,
            "is_active": is_active,
            "is_real_hardware": is_real_hardware,
            "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
        }
        for reader_id, location_name, floor_value, map_x, map_y, is_active, is_real_hardware, last_seen_at in rows
    ]


def update_reader_map_position(
    reader_id: str,
    floor: int,
    map_x: float,
    map_y: float,
    location_name: str | None = None,
) -> dict | None:
    sql = """
    UPDATE readers
    SET floor = %s, map_x = %s, map_y = %s,
        location_name = COALESCE(%s, location_name),
        updated_at = now()
    WHERE reader_id = %s
    RETURNING reader_id, location_name, floor, map_x, map_y, is_real_hardware
    """
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, (floor, map_x, map_y, location_name, reader_id))
        row = cur.fetchone()

    if not row:
        return None

    return {
        "reader_id": row[0],
        "location_name": row[1],
        "floor": row[2],
        "map_x": float(row[3]) if row[3] is not None else None,
        "map_y": float(row[4]) if row[4] is not None else None,
        "is_real_hardware": row[5],
    }


def load_tag_metadata(tag_ids: set[str]) -> dict[str, dict]:
    if not tag_ids:
        return {}

    sql = """
    SELECT
      t.tag_id,
      t.equipment_name,
      t.equipment_type,
      t.serial_number,
      t.asset_status,
      t.current_holder_user_id,
      COALESCE(u.display_name, u.username) AS current_holder_name,
      t.is_real_hardware
    FROM tags t
    LEFT JOIN users u ON u.user_id = t.current_holder_user_id
    WHERE tag_id = ANY(%s)
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, (list(tag_ids),))
            rows = cur.fetchall()
    except Exception:
        return {}

    return {
        row[0]: {
            "equipment_name": row[1],
            "equipment_type": row[2],
            "serial_number": row[3],
            "asset_status": row[4],
            "current_holder_user_id": row[5],
            "current_holder_name": row[6],
            "is_real_hardware": row[7],
        }
        for row in rows
    }


def load_active_tag_ids() -> set[str]:
    sql = "SELECT tag_id FROM tags WHERE is_active = TRUE"
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception:
        return set()
    return {row[0] for row in rows}


def normalize_nfc_token(raw: str) -> str:
    token = raw.strip()
    if not token:
        raise HTTPException(400, "nfc_token은 비어 있을 수 없습니다.")
    if any(ch.isspace() for ch in token) or "/" in token or "?" in token or "#" in token:
        raise HTTPException(400, "nfc_token에는 공백, '/', '?', '#' 문자를 사용할 수 없습니다.")
    return token


def resolve_tag_location_snapshot(
    tag_id: str,
    now: int | None = None,
    reader_locations: dict[str, str] | None = None,
):
    current_ts = now if now is not None else int(time.time())
    locations = reader_locations if reader_locations is not None else load_reader_location_map()

    cached_location = read_cached_tag_location(tag_id)
    if not cached_location:
        cached_location = fetch_latest_db_tag_location(tag_id)
        if not cached_location:
            return None
        if cached_location.get("reader_id") and isinstance(cached_location.get("changed_at"), int):
            cache_tag_location_snapshot(
                tag_id,
                cached_location["reader_id"],
                cached_location["changed_at"],
                reader_locations=locations,
            )

    rid = cached_location.get("reader_id")
    if not rid:
        return None

    changed_at_epoch = cached_location.get("changed_at")
    is_stale = False
    if isinstance(changed_at_epoch, int):
        is_stale = (current_ts - changed_at_epoch) > (STALE_SEC * 2)

    return {
        "reader_id": rid,
        "location": cached_location.get("location") or locations.get(rid, READER_LOCATION.get(rid, rid)),
        "rssi": None,
        "updated_at": changed_at_epoch,
        "is_stale": is_stale,
    }
