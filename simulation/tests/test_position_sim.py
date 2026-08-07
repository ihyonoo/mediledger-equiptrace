import random

from simulation.position_sim import build_ingest_payloads, pick_next_room


class TestPickNextRoom:
    def test_never_returns_the_current_room_when_alternatives_exist(self):
        rng = random.Random(1)
        for _ in range(50):
            next_room = pick_next_room("M101", ["M101", "M102", "M103"], rng)
            assert next_room != "M101"

    def test_returns_the_only_room_when_no_alternative_exists(self):
        rng = random.Random(1)
        assert pick_next_room("M101", ["M101"], rng) == "M101"


class TestBuildIngestPayloads:
    def test_groups_tags_by_room_into_one_payload_each(self):
        rng = random.Random(1)
        room_to_tags = {"M101": ["EQ-0001", "EQ-0002"], "M102": ["EQ-0003"]}

        payloads = build_ingest_payloads(room_to_tags, now=1000, rssi_min=-70, rssi_max=-45, rng=rng)

        by_reader = {p["reader_id"]: p for p in payloads}
        assert set(by_reader) == {"M101", "M102"}
        assert {o["tag_id"] for o in by_reader["M101"]["observations"]} == {"EQ-0001", "EQ-0002"}
        assert by_reader["M102"]["observations"][0]["tag_id"] == "EQ-0003"

    def test_observation_fields_are_within_configured_rssi_range_and_use_now(self):
        rng = random.Random(1)
        room_to_tags = {"M101": ["EQ-0001"]}

        payloads = build_ingest_payloads(room_to_tags, now=1234, rssi_min=-70, rssi_max=-45, rng=rng)

        observation = payloads[0]["observations"][0]
        assert -70 <= observation["rssi"] <= -45
        assert observation["count"] == 1
        assert observation["last_seen"] == 1234
        assert payloads[0]["ts"] == 1234

    def test_empty_input_produces_no_payloads(self):
        rng = random.Random(1)
        assert build_ingest_payloads({}, now=0, rssi_min=-70, rssi_max=-45, rng=rng) == []
