"""Statistics, range counting and RunResult serialisation."""
import json
import math

from src.testing.analysis import compute_statistics, out_of_range
from src.testing.models import Reading, RunResult, Sample
from src.utils.config import ExpectedRange


def reading(index: int, value: float | None, error: str | None = None) -> Reading:
    return Reading(index, f"2026-01-01T00:00:0{index}.000000+00:00", float(index), float(index),
                   value, error)


def readings(*values: float | None) -> list[Reading]:
    return [reading(i, v, None if v is not None else "AmmeterTimeoutError: x")
            for i, v in enumerate(values)]


def test_basic_statistics():
    s = compute_statistics(readings(1, 2, 3, 4))
    assert (s.count, s.valid_count, s.error_count) == (4, 4, 0)
    assert s.mean == 2.5 and s.median == 2.5 and s.min == 1 and s.max == 4
    assert math.isclose(s.stdev, 1.2909944, rel_tol=1e-6)
    assert math.isclose(s.cv_percent, 51.6397779, rel_tol=1e-6)


def test_single_value():
    s = compute_statistics(readings(7))
    assert s.stdev is None and s.cv_percent is None
    assert s.mean == s.median == s.min == s.max == 7


def test_no_valid_values():
    s = compute_statistics(readings(None, None))
    assert (s.count, s.valid_count, s.error_count) == (2, 0, 2)
    assert all(v is None for v in (s.mean, s.median, s.stdev, s.min, s.max, s.cv_percent))


def test_errors_are_excluded_and_counted():
    s = compute_statistics(readings(1, None, 3))
    assert (s.count, s.valid_count, s.error_count) == (3, 2, 1)
    assert s.mean == 2


def test_zero_mean_gives_no_cv():
    assert compute_statistics(readings(-1, 1)).cv_percent is None


def test_negative_mean_uses_absolute_value():
    assert compute_statistics(readings(-1, -2, -3)).cv_percent > 0


def test_out_of_range_keeps_bounds_and_ignores_errors():
    rng = ExpectedRange(1.0, 3.0)
    rs = readings(0.5, 1.0, 2.0, 3.0, 3.5, None)
    assert [r.index for r in out_of_range(rs, rng)] == [0, 4]


def make_result() -> RunResult:
    rs = readings(1, 2, None, 9)
    rng = ExpectedRange(0.5, 5.0)
    sample = Sample(tuple(rs), "2026-01-01T00:00:00.000000+00:00",
                    "2026-01-01T00:00:04.000000+00:00", 4.0)
    return RunResult("20260101T000000Z_greenlee_abcdef", "greenlee", {"count": 4}, rng, sample,
                     compute_statistics(rs), tuple(out_of_range(rs, rng)))


def test_run_result_dict_matches_the_record():
    result = make_result()
    d = result.to_dict()
    assert set(d) == {"run_id", "ammeter", "started_at_utc", "finished_at_utc", "elapsed_s",
                      "parameters", "expected_range", "statistics", "out_of_range_count",
                      "readings"}
    assert d["out_of_range_count"] == len(result.out_of_range) == 1
    assert len(d["readings"]) == 4
    assert json.loads(json.dumps(d)) == d


def test_reading_ok_property():
    assert reading(0, 1.0).ok
    assert not reading(0, None, "boom").ok
