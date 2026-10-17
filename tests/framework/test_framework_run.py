"""AmmeterTestFramework end to end against real emulators, plus the text report."""
import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace

import pytest

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from src.testing.report import format_run_report
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import SamplingPlan, load_config
from src.utils.errors import ConfigError, ResultsWriteError
from src.utils.results import RUN_ID_PATTERN, load_run
from tests.helpers import fake_server, running_emulator, unused_port, write_config

CLASSES = {"greenlee": GreenleeAmmeter, "entes": EntesAmmeter, "circutor": CircutorAmmeter}
TWO = SamplingPlan(count=2, duration_s=0.1, frequency_hz=20.0)


def make_framework(tmp_path, ports):
    config = load_config(write_config(tmp_path / "config.yaml", ports))
    return AmmeterTestFramework(config=replace(config, results_dir=tmp_path / "results"))


@pytest.fixture
def framework(tmp_path):
    with ExitStack() as stack:
        ports = {name: stack.enter_context(running_emulator(cls)).port
                 for name, cls in CLASSES.items()}
        yield make_framework(tmp_path, ports)


def test_run_test_archives_a_result_that_loads_back_equal(framework):
    result = framework.run_test("greenlee")
    assert result.archive_path.exists()
    assert RUN_ID_PATTERN.match(result.run_id)
    assert load_run(result.run_id, framework.config.results_dir) == result.to_dict()


def test_custom_plan_is_used_and_recorded(framework):
    result = framework.run_test("greenlee", plan=TWO)
    assert len(result.sample.readings) == 2
    assert result.parameters["count"] == 2
    assert result.parameters["frequency_hz"] == 20.0
    assert result.parameters["command"] == "MEASURE_GREENLEE -get_measurement"


def test_to_dict_content_comes_from_config_and_run(framework):
    result = framework.run_test("entes", plan=TWO)
    record = result.to_dict()
    settings = framework.config.ammeters["entes"]
    assert record["ammeter"] == "entes"
    assert record["run_id"] == result.run_id
    assert record["parameters"]["port"] == settings.port
    assert record["parameters"]["command"] == "MEASURE_ENTES -get_data"
    assert record["parameters"]["duration_s"] == 0.1
    assert record["parameters"]["count"] == 2
    assert record["expected_range"] == {"min_amps": settings.expected_range.min_amps,
                                        "max_amps": settings.expected_range.max_amps}
    assert len(record["readings"]) == 2


def test_unknown_ammeter_raises_before_anything_is_created(framework):
    with pytest.raises(ConfigError, match="nope"):
        framework.run_test("nope")
    assert not framework.config.results_dir.exists()


def test_run_all_covers_every_ammeter_with_unique_ids(framework):
    results = framework.run_all()
    assert list(results) == list(framework.config.ammeters)
    ids = [r.run_id for r in results.values()]
    assert len(set(ids)) == len(ids)


def test_statistics_match_the_readings(framework):
    result = framework.run_test("entes")
    values = [r.value_amps for r in result.sample.readings if r.ok]
    stats = result.statistics
    assert stats.mean == pytest.approx(statistics.fmean(values))
    assert stats.valid_count == len(values) and stats.count == len(result.sample.readings)
    assert stats.error_count == stats.count - stats.valid_count


def test_report_has_the_required_parts(framework):
    result = framework.run_test("circutor", plan=TWO)
    text = format_run_report(result, framework.config.metrics)
    for part in ("circutor", result.run_id, "count=", "frequency="):
        assert part in text
    for metric in framework.config.metrics:
        assert metric in text
    assert str(result.archive_path) in text


def test_report_shows_n_a_for_undefined_values(tmp_path):
    framework = make_framework(tmp_path, {"greenlee": unused_port(), "entes": unused_port(),
                                          "circutor": unused_port()})
    result = framework.run_test("greenlee", plan=TWO)
    assert "n/a" in format_run_report(result, ("mean", "stdev"))


def test_error_readings_land_in_the_run_log(tmp_path):
    framework = make_framework(tmp_path, {"greenlee": unused_port(), "entes": unused_port(),
                                          "circutor": unused_port()})
    result = framework.run_test("greenlee", plan=TWO)
    assert result.statistics.error_count == 2
    logs = list((framework.config.results_dir / "logs").glob("*greenlee*.log"))
    assert len(logs) == 1
    assert "AmmeterConnectionError" in logs[0].read_text(encoding="utf-8")


def test_run_logger_is_closed_and_removed_afterwards(framework):
    result = framework.run_test("greenlee", plan=TWO)
    assert not [name for name in logging.Logger.manager.loggerDict if result.run_id in name]


def test_concurrent_runs_each_get_their_own_log(framework):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: framework.run_test("greenlee", plan=TWO), range(6)))
    logs = list((framework.config.results_dir / "logs").glob("*.log"))
    assert len(logs) == 6
    for result in results:
        [log] = [p for p in logs if result.run_id in p.name]
        text = log.read_text(encoding="utf-8")
        assert text.count("Run ID: ") == 1 and f"Run ID: {result.run_id}" in text


def test_results_dir_that_is_a_file_raises(framework, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    broken = AmmeterTestFramework(config=replace(framework.config, results_dir=blocker))
    with pytest.raises(ResultsWriteError):
        broken.run_test("greenlee", plan=TWO)


def test_unwritable_results_dir_fails_before_any_sampling(framework, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("src.testing.AmmeterTester.AmmeterTester.sample",
                        lambda self, plan=None: calls.append(plan))
    blocker = tmp_path / "blocker_file"
    blocker.write_text("x")
    broken = AmmeterTestFramework(config=replace(framework.config, results_dir=blocker))
    with pytest.raises(ResultsWriteError, match="blocker_file"):
        broken.run_test("greenlee", plan=TWO)
    assert calls == []


def test_overflowing_readings_are_archived_and_reported_as_n_a(tmp_path):
    with fake_server(reply=b"1e308") as port:
        framework = make_framework(tmp_path, {"greenlee": port, "entes": unused_port(),
                                              "circutor": unused_port()})
        result = framework.run_test("greenlee", plan=TWO)
    assert result.statistics.valid_count == 2 and result.statistics.mean is None
    assert load_run(result.run_id, framework.config.results_dir)["statistics"]["mean"] is None
    assert "n/a" in format_run_report(result, ("mean",))


def test_run_id_clash_before_sampling_picks_a_fresh_id_and_keeps_the_old_run(
        framework, monkeypatch):
    first = framework.run_test("greenlee", plan=TWO)
    before = first.archive_path.read_bytes()
    ids = iter([first.run_id, "20260101T000000Z_greenlee_aaaaaa"])
    monkeypatch.setattr("src.utils.results.new_run_id", lambda ammeter: next(ids))
    second = framework.run_test("greenlee", plan=TWO)
    assert second.run_id == "20260101T000000Z_greenlee_aaaaaa"
    assert second.archive_path.exists()
    assert first.archive_path.read_bytes() == before


def test_failed_sampling_leaves_no_empty_run_folder(framework, monkeypatch):
    def boom(self, plan=None):
        raise RuntimeError("sampling broke")

    monkeypatch.setattr("src.testing.AmmeterTester.AmmeterTester.sample", boom)
    with pytest.raises(RuntimeError):
        framework.run_test("greenlee", plan=TWO)
    results_dir = framework.config.results_dir
    assert [p.name for p in results_dir.iterdir()] == ["logs"]
