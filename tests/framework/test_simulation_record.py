"""A simulated run is archived with its seed; a plan shorter than a stall is refused."""
from dataclasses import replace

import pytest

from src.testing.emulators import start_emulators, stop_emulators
from src.testing.faults import fault_sequence
from src.testing.report import format_run_report
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import ErrorSimulation, FrameworkConfig, SamplingPlan
from src.utils.errors import ConfigError
from src.utils.results import load_run
from tests.helpers import TWO, make_framework, unused_port

NAMES = ("greenlee", "entes", "circutor")
LINE = "Simulation: errors injected (seed 7)"


def simulated_config(tmp_path, simulation: ErrorSimulation, **changes) -> FrameworkConfig:
    """The test config with `simulation` on greenlee, then `changes` applied."""
    config = make_framework(tmp_path, {name: unused_port() for name in NAMES}).config
    ammeters = dict(config.ammeters)
    ammeters["greenlee"] = replace(ammeters["greenlee"], simulate_errors=simulation)
    return replace(config, ammeters=ammeters, **changes)


def run_on_fresh_emulators(config: FrameworkConfig):
    """Start the emulators on free ports, run greenlee once, stop them."""
    running = start_emulators(config, {name: 0 for name in config.ammeters})
    try:
        ports = {name: item.port for name, item in running.items()}
        framework = AmmeterTestFramework(config=config.with_ports(ports))
        return framework, framework.run_test("greenlee")
    finally:
        stop_emulators(running)


def error_types(result) -> list[str | None]:
    """The error type name of every reading, None for a good one."""
    return [r.error.split(":")[0] if r.error else None for r in result.sample.readings]


def test_simulated_run_is_archived_with_its_seed_and_loads_back_equal(tmp_path):
    simulation = ErrorSimulation(seed=7, garbage=0.5)
    config = simulated_config(tmp_path, simulation)
    framework, result = run_on_fresh_emulators(config)
    record = load_run(result.run_id, config.results_dir)
    assert record == result.to_dict()
    assert record["simulation"]["seed"] == 7
    expected = fault_sequence(simulation, 4)
    assert result.statistics.error_count == expected.count("garbage")
    report = format_run_report(result, config.metrics)
    assert report.splitlines().count(LINE) == 1


def test_same_seed_on_fresh_emulators_gives_the_same_error_pattern(tmp_path):
    simulation = ErrorSimulation(seed=7, garbage=0.5)
    config = simulated_config(tmp_path, simulation)
    first = error_types(run_on_fresh_emulators(config)[1])
    second = error_types(run_on_fresh_emulators(config)[1])
    expected = ["NonNumericResponseError" if f == "garbage" else None
                for f in fault_sequence(simulation, 4)]
    assert first == second == expected


def test_plan_shorter_than_the_stall_is_rejected_before_any_folder_is_created(tmp_path):
    simulation = ErrorSimulation(seed=1, stall=0.5, stall_seconds=0.15)
    config = simulated_config(tmp_path, simulation, request_timeout_s=0.1,
                              sampling=SamplingPlan(4, 1.0, 4.0))
    with pytest.raises(ConfigError, match=r"simulate_errors\.stall_seconds"):
        AmmeterTestFramework(config=config).run_test("greenlee", TWO)
    assert not config.results_dir.exists()
