"""위치 시뮬레이션: 태그를 방 사이에 무작위로 이동시키고 /ingest 페이로드를 만든다.

방 전환 판정(히스테리시스·체류·신선도)은 백엔드가 그대로 다시 계산하므로, 여기서는
실제 rtls_reader/send_to_server.py와 같은 배치 포맷으로 관측치를 보내기만 하면 된다.
"""

import asyncio
import random
import time

from simulation import config
from simulation.api_client import ApiClient


def pick_next_room(current_room: str, room_ids: list[str], rng: random.Random) -> str:
    candidates = [r for r in room_ids if r != current_room]
    if not candidates:
        return current_room
    return rng.choice(candidates)


def build_ingest_payloads(
    room_to_tags: dict[str, list[str]],
    now: int,
    rssi_min: int,
    rssi_max: int,
    rng: random.Random,
) -> list[dict]:
    payloads = []
    for reader_id, tag_ids in room_to_tags.items():
        if not tag_ids:
            continue
        observations = [
            {
                "tag_id": tag_id,
                "rssi": rng.randint(rssi_min, rssi_max),
                "count": 1,
                "last_seen": now,
            }
            for tag_id in tag_ids
        ]
        payloads.append({"reader_id": reader_id, "ts": now, "observations": observations})
    return payloads


class PositionState:
    """태그별 현재 방·다음 이동 시각, 리더/태그별 일시 무신호 상태를 메모리에 유지한다."""

    def __init__(self, reader_ids: list[str], tag_ids: list[str], rng: random.Random, now: float):
        self.reader_ids = reader_ids
        self.rng = rng
        self.tag_room: dict[str, str] = {}
        self.tag_next_change_at: dict[str, float] = {}
        self.reader_down_until: dict[str, float] = {}
        self.tag_quiet_until: dict[str, float] = {}
        for tag_id in tag_ids:
            room = rng.choice(reader_ids)
            self.tag_room[tag_id] = room
            self.tag_next_change_at[tag_id] = now + rng.uniform(config.ROOM_DWELL_MIN_SEC, config.ROOM_DWELL_MAX_SEC)

    def tick(self, now: float) -> dict[str, list[str]]:
        rng = self.rng

        # 낮은 확률로 리더를 일시 오프라인 처리(이미 오프라인인 리더가 없을 때만).
        no_reader_down = not any(until > now for until in self.reader_down_until.values())
        if no_reader_down and rng.random() < config.READER_OUTAGE_PROBABILITY_PER_TICK:
            room = rng.choice(self.reader_ids)
            self.reader_down_until[room] = now + rng.uniform(config.READER_OUTAGE_MIN_SEC, config.READER_OUTAGE_MAX_SEC)

        room_to_tags: dict[str, list[str]] = {r: [] for r in self.reader_ids}
        for tag_id, room in self.tag_room.items():
            if rng.random() < config.TAG_STALE_PROBABILITY_PER_TICK and now >= self.tag_quiet_until.get(tag_id, 0):
                self.tag_quiet_until[tag_id] = now + rng.uniform(config.TAG_STALE_MIN_SEC, config.TAG_STALE_MAX_SEC)

            if now >= self.tag_next_change_at[tag_id]:
                new_room = pick_next_room(room, self.reader_ids, rng)
                self.tag_room[tag_id] = new_room
                room = new_room
                self.tag_next_change_at[tag_id] = now + rng.uniform(
                    config.ROOM_DWELL_MIN_SEC, config.ROOM_DWELL_MAX_SEC
                )

            if now < self.tag_quiet_until.get(tag_id, 0):
                continue
            if now < self.reader_down_until.get(room, 0):
                continue
            room_to_tags[room].append(tag_id)

        return room_to_tags


async def run_position_loop(reader_ids: list[str], tag_ids: list[str], api_client: ApiClient) -> None:
    rng = random.Random()
    state = PositionState(reader_ids, tag_ids, rng, time.time())
    while True:
        now = time.time()
        room_to_tags = state.tick(now)
        payloads = build_ingest_payloads(room_to_tags, int(now), config.RSSI_MIN, config.RSSI_MAX, rng)
        await asyncio.gather(*(api_client.ingest(p) for p in payloads), return_exceptions=True)
        await asyncio.sleep(config.POSITION_TICK_SEC)
