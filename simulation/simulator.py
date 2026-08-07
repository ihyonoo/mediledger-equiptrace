"""상시 가동 시뮬레이터 진입점.

위치 이동(position_sim)과 사용 활동(usage_sim: 체크아웃 + 반납 직렬화 워커)을
하나의 asyncio 프로세스로 실행한다. SIGINT/SIGTERM을 받으면 새 작업 스케줄링을
멈추고 모든 태스크가 정리될 때까지 기다린 뒤 종료한다.

실행: python -m simulation.simulator (저장소 루트에서, simulation/.env 필요)
"""

import asyncio
import signal

from simulation import config, db
from simulation.api_client import ApiClient
from simulation.position_sim import run_position_loop
from simulation.usage_sim import CheckoutState, make_return_handler, return_worker, run_checkout_loop


async def run() -> None:
    if not config.SIM_STAFF_PASSWORD:
        raise SystemExit("SIM_STAFF_PASSWORD 환경변수가 필요합니다 (simulation/.env 참고).")

    print("[simulator] seeding topology...")
    db.apply_seed_sql()
    db.ensure_staff_passwords(config.SIM_STAFF_PASSWORD)
    inventory = db.load_sim_inventory()
    print(
        f"[simulator] loaded {len(inventory['reader_ids'])} readers, "
        f"{len(inventory['tag_nfc'])} tags, {len(inventory['staff_usernames'])} staff"
    )

    api_client = ApiClient()
    staff_credentials = [(username, config.SIM_STAFF_PASSWORD) for username in inventory["staff_usernames"]]
    checkout_state = CheckoutState.from_tag_ids(list(inventory["tag_nfc"].keys()))
    return_queue: asyncio.Queue = asyncio.Queue()
    return_handler = make_return_handler(checkout_state, inventory["tag_nfc"], staff_credentials, api_client)

    tasks = [
        asyncio.create_task(run_position_loop(inventory["reader_ids"], list(inventory["tag_nfc"].keys()), api_client)),
        asyncio.create_task(
            run_checkout_loop(checkout_state, inventory["tag_nfc"], staff_credentials, api_client, return_queue)
        ),
        asyncio.create_task(return_worker(return_queue, return_handler)),
    ]

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    print("[simulator] running")
    await stop_event.wait()

    print("[simulator] stopping...")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await api_client.aclose()
    print("[simulator] stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
