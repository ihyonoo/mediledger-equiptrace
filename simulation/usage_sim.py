"""사용 활동 시뮬레이션: 시간대별 활동률에 따라 체크아웃을 발생시키고, 반납은 실제
온체인 앵커링(30초 블록 주기 + 30초 백엔드 타임아웃)을 트리거하므로 동시 트랜잭션
nonce 충돌을 피하기 위해 단일 워커가 큐에서 하나씩 순차 처리한다.
"""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from simulation import config
from simulation.api_client import ApiClient


def kst_hour(epoch_seconds: float) -> int:
    # 컨테이너의 시스템 타임존 설정에 의존하지 않도록 UTC+9(KST)를 직접 계산한다.
    return int((epoch_seconds // 3600 + 9) % 24)


def activity_factor(hour: int, activity_by_hour: list[float], scale: float) -> float:
    return activity_by_hour[hour] * scale


def checkout_probability(base: float, hour: int, activity_by_hour: list[float], scale: float) -> float:
    return base * activity_factor(hour, activity_by_hour, scale)


async def return_worker(queue: asyncio.Queue, handler: Callable[[str], Awaitable[None]]) -> None:
    """큐에 들어온 항목을 항상 하나씩만 처리한다 — 동시 반납(체인 앵커링) 방지."""
    while True:
        item = await queue.get()
        try:
            await handler(item)
        except Exception:
            pass
        finally:
            queue.task_done()


@dataclass
class CheckoutState:
    available_tags: set[str]
    checked_out_tags: dict[str, float]  # tag_id -> return_at(epoch)

    @classmethod
    def from_tag_ids(cls, tag_ids: list[str]) -> "CheckoutState":
        return cls(available_tags=set(tag_ids), checked_out_tags={})


async def run_checkout_loop(
    state: CheckoutState,
    tag_nfc: dict[str, str],
    staff_credentials: list[tuple[str, str]],
    api_client: ApiClient,
    return_queue: asyncio.Queue,
) -> None:
    rng = random.Random()

    while True:
        now = time.time()
        hour = kst_hour(now)

        due = [tag_id for tag_id, return_at in state.checked_out_tags.items() if now >= return_at]
        for tag_id in due:
            del state.checked_out_tags[tag_id]
            await return_queue.put(tag_id)

        prob = checkout_probability(
            config.BASE_CHECKOUT_PROBABILITY_PER_TICK, hour, config.ACTIVITY_BY_HOUR, config.SIM_ACTIVITY_SCALE
        )
        for tag_id in list(state.available_tags):
            if rng.random() >= prob:
                continue
            username, password = rng.choice(staff_credentials)
            try:
                token = await api_client.login(username, password)
                response = await api_client.checkout(token, tag_nfc[tag_id])
                if response.status_code != 200:
                    continue
            except Exception:
                continue
            state.available_tags.discard(tag_id)
            duration = rng.uniform(config.USAGE_DURATION_MIN_SEC, config.USAGE_DURATION_MAX_SEC)
            state.checked_out_tags[tag_id] = now + duration

        await asyncio.sleep(config.CHECKOUT_CHECK_INTERVAL_SEC)


def make_return_handler(
    state: CheckoutState,
    tag_nfc: dict[str, str],
    staff_credentials: list[tuple[str, str]],
    api_client: ApiClient,
) -> Callable[[str], Awaitable[None]]:
    rng = random.Random()

    async def handler(tag_id: str) -> None:
        try:
            username, password = rng.choice(staff_credentials)
            token = await api_client.login(username, password)
            response = await api_client.return_equipment(token, tag_nfc[tag_id])
            ok = response.status_code == 200
        except Exception:
            ok = False

        if ok:
            state.available_tags.add(tag_id)
        else:
            # 실패(체인 미구성, 네트워크 오류 등)한 반납은 짧은 지연 뒤 재시도 큐에 다시 넣는다.
            state.checked_out_tags[tag_id] = time.time() + config.CHECKOUT_CHECK_INTERVAL_SEC

    return handler
