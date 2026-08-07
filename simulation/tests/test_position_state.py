from simulation.position_sim import PositionState


class FixedRng:
    """예측 가능한 값만 반환하는 테스트용 가짜 RNG. choices는 rng.choice() 호출 순서대로 소비된다."""

    def __init__(self, choices=None, random_value=1.0, uniform_value=50.0, randint_value=-55):
        self._choices = list(choices or [])
        self.random_value = random_value
        self.uniform_value = uniform_value
        self.randint_value = randint_value

    def random(self):
        return self.random_value

    def uniform(self, _a, _b):
        return self.uniform_value

    def choice(self, seq):
        return self._choices.pop(0) if self._choices else seq[0]

    def randint(self, _a, _b):
        return self.randint_value


class TestPositionStateTick:
    def test_keeps_tag_in_its_room_before_dwell_expires(self):
        rng = FixedRng(choices=["M101"])
        state = PositionState(["M101", "M102"], ["EQ-0001"], rng, now=0)

        result = state.tick(now=10)  # dwell expires at 0 + uniform(50) = 50

        assert result["M101"] == ["EQ-0001"]
        assert result["M102"] == []

    def test_moves_tag_to_a_new_room_after_dwell_expires(self):
        rng = FixedRng(choices=["M101", "M102"])  # 1st: initial room, 2nd: room chosen on dwell expiry
        state = PositionState(["M101", "M102"], ["EQ-0001"], rng, now=0)

        result = state.tick(now=100)  # past dwell expiry (50)

        assert result["M102"] == ["EQ-0001"]
        assert result["M101"] == []

    def test_excludes_a_tag_that_is_currently_quiet(self):
        rng = FixedRng(choices=["M101"])
        state = PositionState(["M101", "M102"], ["EQ-0001"], rng, now=0)
        state.tag_quiet_until["EQ-0001"] = 1000

        result = state.tick(now=10)

        assert result["M101"] == []
        assert result["M102"] == []

    def test_excludes_tags_in_a_currently_down_reader(self):
        rng = FixedRng(choices=["M101"])
        state = PositionState(["M101", "M102"], ["EQ-0001"], rng, now=0)
        state.reader_down_until["M101"] = 1000

        result = state.tick(now=10)

        assert result["M101"] == []
        assert result["M102"] == []
