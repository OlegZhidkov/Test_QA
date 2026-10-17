"""Error simulation: every injected fault is detected at the reading where it was injected."""
import statistics

import pytest

from src.testing.faults import fault_sequence
from src.testing.report import format_run_report
from src.utils.config import FAULT_TYPES
from src.utils.results import load_run

EXPECTED_ERROR = {"no_response": "EmptyResponseError", "stall": "AmmeterTimeoutError",
                  "garbage": "NonNumericResponseError"}
SCHEDULE_TOLERANCE_S = 0.05


def test_every_injected_fault_is_detected_at_its_reading(scenario_run, scenario_config):
    expected = fault_sequence(scenario_run.settings.simulate_errors, scenario_config.sampling.count)
    limits = scenario_run.settings.expected_range
    mismatches = []
    for reading, fault in zip(scenario_run.result.sample.readings, expected, strict=True):
        if fault in EXPECTED_ERROR:
            actual = (reading.error or "ok").split(":")[0]
            good = actual == EXPECTED_ERROR[fault]
        else:
            actual = "ok" if reading.ok else reading.error
            inside = reading.ok and limits.min_amps <= reading.value_amps <= limits.max_amps
            good = reading.ok and inside == (fault is None)
        if not good:
            mismatches.append(f"reading {reading.index}: expected {fault}, got {actual} "
                              f"({reading.value_amps})")
    assert not mismatches, "\n".join(mismatches)


def test_error_and_out_of_range_counts_match_the_configured_plan(scenario_run, scenario_config):
    expected = fault_sequence(scenario_run.settings.simulate_errors, scenario_config.sampling.count)
    counts = {fault: expected.count(fault) for fault in FAULT_TYPES}
    stats = scenario_run.result.statistics
    assert stats.error_count == counts["no_response"] + counts["stall"] + counts["garbage"]
    assert len(scenario_run.result.out_of_range) == counts["out_of_range"]
    assert scenario_run.injector.decisions == scenario_config.sampling.count


def test_statistics_use_only_the_valid_readings(scenario_run, scenario_config):
    result = scenario_run.result
    values = [r.value_amps for r in result.sample.readings if r.ok]
    stats = result.statistics
    assert stats.valid_count + stats.error_count == scenario_config.sampling.count
    assert stats.valid_count == len(values)
    assert stats.mean == pytest.approx(statistics.mean(values))
    assert stats.median == pytest.approx(statistics.median(values))
    assert stats.min == min(values)
    assert stats.max == max(values)


def test_simulated_run_is_archived_with_its_seed(scenario_run, scenario_config):
    result = scenario_run.result
    record = load_run(result.run_id, scenario_config.results_dir)
    assert record == result.to_dict()
    assert record["simulation"] == scenario_run.settings.simulate_errors.as_record()


def test_report_has_exactly_one_simulation_line(scenario_run, scenario_config):
    seed = scenario_run.settings.simulate_errors.seed
    report = format_run_report(scenario_run.result, scenario_config.metrics)
    assert report.splitlines().count(f"Simulation: errors injected (seed {seed})") == 1


def test_stalls_do_not_shift_the_schedule(scenario_run):
    late = [(r.index, r.actual_offset_s - r.scheduled_offset_s)
            for r in scenario_run.result.sample.readings
            if abs(r.actual_offset_s - r.scheduled_offset_s) > SCHEDULE_TOLERANCE_S]
    assert not late


def test_scenario_seeds_exercise_every_configured_fault_type(scenario_config):
    for name, settings in scenario_config.ammeters.items():
        simulation = settings.simulate_errors
        seen = set(fault_sequence(simulation, scenario_config.sampling.count))
        configured = {fault for fault, chance in simulation.probabilities().items() if chance > 0}
        assert configured <= seen, f"{name}: {configured - seen} never injected"
