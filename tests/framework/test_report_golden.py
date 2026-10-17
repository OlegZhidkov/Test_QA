"""The report and run record of a run without simulation stay exactly as they were."""
from dataclasses import replace

from src.testing.report import format_run_report
from src.utils.config import ALL_METRICS, ErrorSimulation
from src.utils.results import RECORD_KEYS
from tests.helpers import synthetic_result

GOLDEN_REPORT = """\
Ammeter: greenlee   Run ID: 20260101T000000Z_greenlee_abcdef
Parameters: count=2 duration=0.4 s frequency=5 Hz interval=0.2 s request_timeout=2 s
Target: 127.0.0.1:5000 command='X'
Statistics:
  mean: 1.5
  median: 1.5
  stdev: 0.707107
  min: 1
  max: 2
  cv_percent: 47.1405
Readings: valid=2 errors=0 out_of_range=0 (expected 0.01 to 100 A)
Archive: not archived"""

GOLDEN_RECORD = {
    "run_id": "20260101T000000Z_greenlee_abcdef",
    "ammeter": "greenlee",
    "started_at_utc": "2026-01-01T00:00:00.000000+00:00",
    "finished_at_utc": "2026-01-01T00:00:00.400000+00:00",
    "elapsed_s": 0.4,
    "parameters": {"count": 2, "duration_s": 0.4, "frequency_hz": 5.0, "interval_s": 0.2,
                   "request_timeout_s": 2.0, "host": "127.0.0.1", "port": 5000,
                   "command": "X"},
    "expected_range": {"min_amps": 0.01, "max_amps": 100.0},
    "statistics": {"count": 2, "valid_count": 2, "error_count": 0, "mean": 1.5,
                   "median": 1.5, "stdev": 0.7071067811865476, "min": 1.0, "max": 2.0,
                   "cv_percent": 47.14045207910317},
    "out_of_range_count": 0,
    "readings": [
        {"index": 0, "timestamp_utc": "2026-01-01T00:00:00.000000+00:00",
         "scheduled_offset_s": 0.0, "actual_offset_s": 0.0, "value_amps": 1.0,
         "error": None},
        {"index": 1, "timestamp_utc": "2026-01-01T00:00:00.200000+00:00",
         "scheduled_offset_s": 0.2, "actual_offset_s": 0.2, "value_amps": 2.0,
         "error": None},
    ],
}


def test_report_without_simulation_is_unchanged():
    assert format_run_report(synthetic_result([1.0, 2.0]), ALL_METRICS) == GOLDEN_REPORT


def test_record_without_simulation_is_unchanged():
    record = synthetic_result([1.0, 2.0]).to_dict()
    assert record == GOLDEN_RECORD
    assert list(record) == list(RECORD_KEYS)


def test_simulated_result_adds_one_report_line_and_one_record_key():
    simulation = ErrorSimulation(seed=7, garbage=0.5)
    result = replace(synthetic_result([1.0, 2.0]), simulation=simulation.as_record())
    target = "Target: 127.0.0.1:5000 command='X'\n"
    expected = GOLDEN_REPORT.replace(target, target + "Simulation: errors injected (seed 7)\n")
    assert format_run_report(result, ALL_METRICS) == expected
    record = result.to_dict()
    assert list(record) == [*RECORD_KEYS, "simulation"]
    assert record["simulation"] == simulation.as_record()
    assert {key: value for key, value in record.items() if key != "simulation"} == GOLDEN_RECORD
