"""AmmeterTester sampling with a fake clock, error readings and logging."""
import logging
from datetime import datetime
from pathlib import Path

import pytest

from src.testing.AmmeterTester import AmmeterTester
from src.utils.config import SamplingPlan, load_config
from src.utils.errors import AmmeterTimeoutError, ConfigError
from tests.helpers import unused_port

SHIPPED = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
PLAN = SamplingPlan(count=5, duration_s=0.5, frequency_hz=10.0)


class FakeTime:
    """A clock that only moves when sleep or a stub measurement advances it."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_tester(fake: FakeTime, measure_cost_s: float = 0.0, logger=None, outcome=None):
    config = load_config(SHIPPED)
    tester = AmmeterTester(config.ammeters["greenlee"], PLAN, 1.0, clock=fake.clock,
                           sleep=fake.sleep, logger=logger)

    def measure() -> float:
        fake.now += measure_cost_s
        if outcome is not None:
            return outcome()
        return 1.5

    tester.measure = measure
    return tester


def test_targets_are_exactly_multiples_of_the_interval():
    sample = make_tester(FakeTime()).sample()
    assert [r.scheduled_offset_s for r in sample.readings] == [i * 0.1 for i in range(5)]
    for r in sample.readings:
        assert r.actual_offset_s == pytest.approx(r.scheduled_offset_s)


def test_slow_reading_does_not_shift_later_targets():
    fake = FakeTime()
    outcomes = iter([0.35, 0.0, 0.0, 0.0, 0.0])
    tester = make_tester(fake)
    tester.measure = lambda: (setattr(fake, "now", fake.now + next(outcomes)), 1.0)[1]
    sample = tester.sample()
    actual = [r.actual_offset_s for r in sample.readings]
    assert actual[1] == pytest.approx(0.35)
    assert actual[2] == pytest.approx(0.35)
    assert actual[4] == pytest.approx(0.4)
    assert [r.scheduled_offset_s for r in sample.readings] == [i * 0.1 for i in range(5)]


def test_sleep_is_never_negative():
    for cost in (0.0, 0.05, 0.25):
        fake = FakeTime()
        make_tester(fake, measure_cost_s=cost).sample()
        assert all(s > 0 for s in fake.sleeps)


def test_sampler_sleeps_to_the_end_of_the_duration():
    fake = FakeTime()
    sample = make_tester(fake).sample()
    assert fake.now == pytest.approx(1000.0 + 0.5)
    assert sample.elapsed_s == pytest.approx(0.5)


def test_reading_count_equals_the_plan():
    assert len(make_tester(FakeTime()).sample().readings) == PLAN.count
    other = SamplingPlan(3, 0.3, 10.0)
    assert len(make_tester(FakeTime()).sample(other).readings) == 3


def raise_timeout() -> float:
    raise AmmeterTimeoutError("no answer")


def test_typed_error_becomes_an_error_reading():
    sample = make_tester(FakeTime(), outcome=raise_timeout).sample()
    assert all(r.value_amps is None and r.error.startswith("AmmeterTimeoutError")
               for r in sample.readings)


def test_other_exceptions_propagate():
    def boom() -> float:
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        make_tester(FakeTime(), outcome=boom).sample()


def test_timestamps_follow_offsets_and_increase():
    fake = FakeTime()
    sample = make_tester(fake).sample()
    start = datetime.fromisoformat(sample.started_at_utc)
    stamps = [datetime.fromisoformat(r.timestamp_utc) for r in sample.readings]
    assert all(s.utcoffset().total_seconds() == 0 for s in stamps)
    assert all(a < b for a, b in zip(stamps, stamps[1:]))
    for r, s in zip(sample.readings, stamps):
        assert (s - start).total_seconds() == pytest.approx(r.actual_offset_s, abs=1e-6)
    finish = datetime.fromisoformat(sample.finished_at_utc)
    assert (finish - start).total_seconds() == pytest.approx(sample.elapsed_s, abs=1e-6)


def test_error_reading_is_logged_on_the_given_logger(caplog):
    logger = logging.getLogger("dev.custom")
    with caplog.at_level(logging.WARNING):
        make_tester(FakeTime(), logger=logger, outcome=raise_timeout).sample()
    assert [r.name for r in caplog.records] == ["dev.custom"] * 5
    assert all(r.levelno == logging.WARNING for r in caplog.records)


def test_default_logger_is_the_module_logger(caplog):
    with caplog.at_level(logging.WARNING):
        make_tester(FakeTime(), outcome=raise_timeout).sample()
    assert {r.name for r in caplog.records} == {"src.testing.AmmeterTester"}


def test_missing_emulator_gives_error_readings_without_raising():
    config = load_config(SHIPPED).with_ports({"greenlee": unused_port()})
    tester = AmmeterTester.from_config(config, "greenlee")
    sample = tester.sample(SamplingPlan(2, 0.1, 20.0))
    stats = AmmeterTester.analyze(sample.readings)
    assert len(sample.readings) == 2
    assert (stats.error_count, stats.valid_count) == (2, 0)


def test_unknown_ammeter_lists_known_names():
    with pytest.raises(ConfigError, match="greenlee"):
        AmmeterTester.from_config(load_config(SHIPPED), "nope")
