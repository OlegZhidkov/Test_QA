"""Public suite: every configured ammeter, end to end against its emulator."""
import dataclasses
import math
import statistics
import time
from datetime import datetime

import pytest

from Ammeters.client import request_current_from_ammeter
from src.testing.analysis import out_of_range
from src.testing.report import format_run_report
from src.utils.errors import EmptyResponseError
from src.utils.results import compare_runs, list_runs, load_run

IGNORED_REPLY_LIMIT_S = 0.5
TIMING_TOLERANCE_S = 0.05
DURATION_TOLERANCE_S = 0.15


def ask(settings, command: bytes) -> float:
    """Send one command to the ammeter of `settings` and return the reading."""
    return request_current_from_ammeter(settings.port, command, settings.host, 2.0)


def test_responds_to_its_command_with_a_numeric_value(tester) -> None:
    """The ammeter answers its configured command with a finite number."""
    assert math.isfinite(tester.measure())


def test_ignores_a_wrong_command_without_sending_data_or_stalling(
        framework_config, ammeter_name) -> None:
    """A command the ammeter does not know gets no data, and quickly."""
    settings = framework_config.ammeters[ammeter_name]
    start = time.monotonic()
    with pytest.raises(EmptyResponseError):
        ask(settings, b"MEASURE_UNKNOWN -get_data")
    assert time.monotonic() - start < IGNORED_REPLY_LIMIT_S


def test_ignores_a_truncated_command(framework_config, ammeter_name) -> None:
    """The configured command minus its last byte gets no data, and quickly."""
    settings = framework_config.ammeters[ammeter_name]
    start = time.monotonic()
    with pytest.raises(EmptyResponseError):
        ask(settings, settings.command[:-1])
    assert time.monotonic() - start < IGNORED_REPLY_LIMIT_S


def test_every_reading_is_inside_the_expected_range(run_result, framework_config,
                                                    ammeter_name) -> None:
    """All readings succeed and lie inside the configured expected range."""
    expected = framework_config.ammeters[ammeter_name].expected_range
    readings = run_result.sample.readings
    failed = [r.error for r in readings if not r.ok]
    outside = [r.value_amps for r in out_of_range(readings, expected)]
    assert not failed and not outside, (
        f"{ammeter_name}: expected {expected.min_amps} to {expected.max_amps} A; "
        f"outside: {outside}; failed readings: {failed}")


def test_sample_count_matches_the_configured_count(run_result, framework_config) -> None:
    """The run takes exactly the configured number of readings."""
    assert len(run_result.sample.readings) == framework_config.sampling.count
    assert run_result.statistics.count == framework_config.sampling.count


def test_readings_follow_the_configured_frequency(run_result, framework_config) -> None:
    """Readings are scheduled at i * interval and taken within the timing tolerance."""
    interval = framework_config.sampling.interval_s
    for i, reading in enumerate(run_result.sample.readings):
        assert reading.scheduled_offset_s == pytest.approx(i * interval)
        assert abs(reading.actual_offset_s - reading.scheduled_offset_s) <= TIMING_TOLERANCE_S


def test_sample_lasts_the_configured_duration(run_result, framework_config) -> None:
    """The whole sample takes the configured duration, within tolerance."""
    duration = framework_config.sampling.duration_s
    assert abs(run_result.sample.elapsed_s - duration) <= DURATION_TOLERANCE_S


def test_every_reading_is_timestamped_in_order(run_result) -> None:
    """Timestamps are UTC ISO strings that strictly increase and lie inside the run."""
    sample = run_result.sample
    stamps = [datetime.fromisoformat(r.timestamp_utc) for r in sample.readings]
    assert all(s.utcoffset().total_seconds() == 0 for s in stamps)
    assert all(a < b for a, b in zip(stamps, stamps[1:]))
    assert datetime.fromisoformat(sample.started_at_utc) <= stamps[0]
    assert stamps[-1] <= datetime.fromisoformat(sample.finished_at_utc)


def test_statistics_are_consistent(run_result) -> None:
    """Min, median, mean and max are ordered, stdev is not negative, and mean matches."""
    stats = run_result.statistics
    values = [r.value_amps for r in run_result.sample.readings if r.ok]
    assert stats.min <= stats.median <= stats.max
    assert stats.min <= stats.mean <= stats.max
    assert stats.stdev >= 0
    assert stats.mean == pytest.approx(statistics.fmean(values))


def test_repeated_readings_vary(run_result) -> None:
    """The ammeter does not return one constant value."""
    assert len({r.value_amps for r in run_result.sample.readings}) > 1


def test_consistency_cv_is_reported(run_result, framework_config) -> None:
    """cv_percent equals stdev / |mean| * 100 and appears in the report."""
    stats = run_result.statistics
    assert stats.cv_percent == pytest.approx(stats.stdev / abs(stats.mean) * 100)
    assert "cv_percent" in format_run_report(run_result, framework_config.metrics)


def test_run_is_archived_with_a_unique_id_and_metadata_and_can_be_retrieved(
        run_result, record_run, framework_config, ammeter_name) -> None:
    """The run is saved, listed and loadable, a second run gets a new ID, and both compare."""
    results_dir = framework_config.results_dir
    assert run_result.archive_path.exists()
    record = load_run(run_result.run_id, results_dir)
    for key in ("run_id", "ammeter", "started_at_utc", "parameters", "expected_range",
                "statistics", "readings"):
        assert key in record
    assert record == run_result.to_dict()
    assert run_result.run_id in [run["run_id"] for run in list_runs(results_dir)]

    plan = framework_config.sampling
    second = record_run(ammeter_name,
                        dataclasses.replace(plan, count=2, duration_s=2 * plan.interval_s))
    assert second.run_id != run_result.run_id
    comparison = compare_runs(run_result.run_id, second.run_id, results_dir)
    assert comparison["same_ammeter"] is True
    assert comparison["statistics"]["mean"]["delta"] == pytest.approx(
        second.statistics.mean - run_result.statistics.mean)


def test_report_names_ammeter_run_id_parameters_and_statistics(run_result,
                                                               framework_config) -> None:
    """The report shows the ammeter, run ID, parameters and every configured statistic."""
    report = format_run_report(run_result, framework_config.metrics)
    settings = framework_config.ammeters[run_result.ammeter]
    plan = framework_config.sampling
    expected = [run_result.ammeter, run_result.run_id, f"count={plan.count}",
                f"{settings.host}:{settings.port}", *framework_config.metrics]
    assert [item for item in expected if item not in report] == []
    assert "frequency=" in report
