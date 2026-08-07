import asyncio

from simulation.usage_sim import activity_factor, checkout_probability, kst_hour, return_worker

TABLE = [0.1 * i for i in range(24)]  # 0.0, 0.1, 0.2, ..., 2.3


class TestKstHour:
    def test_converts_utc_midnight_epoch_to_9am_kst(self):
        # 2024-01-01 00:00:00 UTC == epoch 1704067200, KST(UTC+9)로는 09시.
        assert kst_hour(1704067200) == 9

    def test_wraps_around_midnight(self):
        # 2024-01-01 15:00:00 UTC + 9h = 2024-01-02 00:00 KST -> 0시.
        assert kst_hour(1704067200 + 15 * 3600) == 0


class TestActivityFactor:
    def test_looks_up_the_hour_directly(self):
        assert activity_factor(5, TABLE, scale=1.0) == TABLE[5]

    def test_applies_the_scale_multiplier(self):
        assert activity_factor(10, TABLE, scale=2.0) == TABLE[10] * 2.0


class TestCheckoutProbability:
    def test_multiplies_base_probability_by_activity_factor(self):
        result = checkout_probability(base=0.02, hour=10, activity_by_hour=TABLE, scale=1.0)
        assert result == 0.02 * TABLE[10]

    def test_zero_activity_hour_yields_zero_probability(self):
        result = checkout_probability(base=0.02, hour=0, activity_by_hour=TABLE, scale=1.0)
        assert result == 0.0


class TestReturnWorker:
    def test_processes_queued_items_one_at_a_time_never_concurrently(self):
        async def scenario():
            queue = asyncio.Queue()
            concurrent = 0
            max_concurrent = 0

            async def handler(_item):
                nonlocal concurrent, max_concurrent
                concurrent += 1
                max_concurrent = max(max_concurrent, concurrent)
                await asyncio.sleep(0.01)
                concurrent -= 1

            worker_task = asyncio.create_task(return_worker(queue, handler))
            for i in range(5):
                await queue.put(f"item-{i}")
            await queue.join()
            worker_task.cancel()
            return max_concurrent

        assert asyncio.run(scenario()) == 1

    def test_continues_processing_after_a_handler_error(self):
        async def scenario():
            queue = asyncio.Queue()
            processed = []

            async def handler(item):
                if item == "bad":
                    raise ValueError("boom")
                processed.append(item)

            worker_task = asyncio.create_task(return_worker(queue, handler))
            await queue.put("bad")
            await queue.put("good")
            await queue.join()
            worker_task.cancel()
            return processed

        assert asyncio.run(scenario()) == ["good"]
