"""Session fixtures for the ammeter suite: emulators, framework, recorded runs, summary."""
import time
from collections.abc import Callable, Iterator

import pytest

from src.testing.emulators import start_emulators, stop_emulators
from src.testing.AmmeterTester import AmmeterTester
from src.testing.models import RunResult
from src.testing.report import format_run_report
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import DEFAULT_CONFIG_PATH, FrameworkConfig, SamplingPlan, load_config
from src.utils.errors import ConfigError

CONFIG_KEY = pytest.StashKey[FrameworkConfig]()
RUNS_KEY = pytest.StashKey[list[RunResult]]()


def pytest_configure(config: pytest.Config) -> None:
    """Load the shipped config once; a bad config stops the session with its message."""
    try:
        config.stash[CONFIG_KEY] = load_config(DEFAULT_CONFIG_PATH)
    except ConfigError as exc:
        raise pytest.UsageError(str(exc)) from exc
    config.stash[RUNS_KEY] = []


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Run every test that asks for `ammeter_name` once per configured ammeter."""
    if "ammeter_name" in metafunc.fixturenames:
        names = list(metafunc.config.stash[CONFIG_KEY].ammeters)
        metafunc.parametrize("ammeter_name", names, ids=names)


@pytest.fixture(scope="session")
def emulators(request: pytest.FixtureRequest) -> Iterator[dict]:
    """The configured emulators, started on free ports and stopped at the end."""
    config = request.config.stash[CONFIG_KEY]
    running = start_emulators(config, {name: 0 for name in config.ammeters})
    try:
        yield running
    finally:
        stop_emulators(running)


@pytest.fixture(scope="session")
def framework_config(request: pytest.FixtureRequest, emulators: dict) -> FrameworkConfig:
    """The config pointed at the ports the emulators actually bound."""
    config = request.config.stash[CONFIG_KEY]
    return config.with_ports({name: item.port for name, item in emulators.items()})


@pytest.fixture(scope="session")
def framework(framework_config: FrameworkConfig) -> AmmeterTestFramework:
    """The test framework over the live emulators."""
    return AmmeterTestFramework(config=framework_config)


@pytest.fixture(scope="session")
def record_run(request: pytest.FixtureRequest,
               framework: AmmeterTestFramework) -> Callable[..., RunResult]:
    """Run one ammeter and remember the result for the end-of-session report."""
    runs = request.config.stash[RUNS_KEY]

    def record(name: str, plan: SamplingPlan | None = None) -> RunResult:
        result = framework.run_test(name, plan)
        runs.append(result)
        return result

    return record


@pytest.fixture(scope="session")
def _run_cache() -> dict[str, RunResult]:
    """Configured-plan runs by ammeter name."""
    return {}


@pytest.fixture(scope="session")
def _run_wall_times() -> dict[str, float]:
    """Wall-clock seconds the configured-plan run of each ammeter took."""
    return {}


@pytest.fixture
def tester(framework: AmmeterTestFramework, ammeter_name: str) -> AmmeterTester:
    """A tester for the ammeter under test."""
    return framework.tester(ammeter_name)


@pytest.fixture
def run_result(record_run: Callable[..., RunResult], _run_cache: dict[str, RunResult],
               _run_wall_times: dict[str, float], ammeter_name: str) -> RunResult:
    """One configured-plan run of the ammeter under test, taken once per session."""
    if ammeter_name not in _run_cache:
        start = time.monotonic()
        _run_cache[ammeter_name] = record_run(ammeter_name)
        _run_wall_times[ammeter_name] = time.monotonic() - start
    return _run_cache[ammeter_name]


@pytest.fixture
def run_wall_s(run_result: RunResult, _run_wall_times: dict[str, float],
               ammeter_name: str) -> float:
    """Wall-clock seconds of the configured-plan run of the ammeter under test."""
    return _run_wall_times[ammeter_name]


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter, config: pytest.Config) -> None:
    """Print one report block per recorded run; nothing when no run was made."""
    runs = config.stash[RUNS_KEY]
    if not runs:
        return
    terminalreporter.section("Ammeter runs")
    for result in runs:
        terminalreporter.write_line(format_run_report(result, config.stash[CONFIG_KEY].metrics))
        terminalreporter.write_line("")
