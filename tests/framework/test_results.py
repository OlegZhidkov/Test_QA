"""Result archive: save, load, list, compare."""
import json
import logging
import os
from datetime import UTC, datetime

import pytest

from src.utils.errors import (
    ResultsCorruptError,
    ResultsError,
    ResultsNotFoundError,
    ResultsWriteError,
)
from src.utils.results import (
    RUN_ID_PATTERN,
    compare_runs,
    list_runs,
    load_run,
    new_run_id,
    release_run,
    reserve_run,
    save_run,
)

STAT_KEYS = ("count", "valid_count", "error_count", "mean", "median", "stdev", "min", "max",
             "cv_percent")


def record(run_id: str, ammeter: str = "greenlee", mean: float | None = 2.0) -> dict:
    stats = dict.fromkeys(STAT_KEYS, 1.0)
    stats["mean"] = mean
    return {"run_id": run_id, "ammeter": ammeter, "started_at_utc": "2026-01-01T00:00:00+00:00",
            "finished_at_utc": "2026-01-01T00:00:02+00:00", "elapsed_s": 2.0,
            "parameters": {"count": 2}, "expected_range": {"min_amps": 0.0, "max_amps": 9.0},
            "statistics": stats, "out_of_range_count": 0, "readings": []}


def make(tmp_path, ammeter="greenlee", mean=2.0):
    run_id = new_run_id(ammeter)
    save_run(record(run_id, ammeter, mean), tmp_path)
    return run_id


def test_save_then_load_round_trips(tmp_path):
    run_id = new_run_id("greenlee")
    rec = record(run_id)
    path = save_run(rec, tmp_path)
    assert path == tmp_path / run_id / "run.json"
    assert load_run(run_id, tmp_path) == rec


def test_ids_in_the_same_second_differ_and_match_the_pattern():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    a, b = new_run_id("entes", now), new_run_id("entes", now)
    assert a != b
    assert RUN_ID_PATTERN.match(a) and a.startswith("20260101T000000Z_entes_")


def test_no_tmp_file_remains(tmp_path):
    run_id = make(tmp_path)
    assert [p.name for p in (tmp_path / run_id).iterdir()] == ["run.json"]


def test_existing_run_is_not_overwritten(tmp_path):
    run_id = make(tmp_path)
    with pytest.raises(ResultsWriteError):
        save_run(record(run_id), tmp_path)


def test_results_dir_that_is_a_file_names_the_path(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(ResultsWriteError, match="file"):
        save_run(record(new_run_id("greenlee")), blocker)


def write_raw(tmp_path, text):
    run_id = new_run_id("greenlee")
    (tmp_path / run_id).mkdir()
    (tmp_path / run_id / "run.json").write_text(text, encoding="utf-8")
    return run_id


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", "3"])
def test_unreadable_content_is_corrupt(tmp_path, text):
    with pytest.raises(ResultsCorruptError):
        load_run(write_raw(tmp_path, text), tmp_path)


@pytest.mark.parametrize("missing", ["ammeter", "started_at_utc"])
def test_missing_key_is_corrupt(tmp_path, missing):
    run_id = new_run_id("greenlee")
    rec = record(run_id)
    del rec[missing]
    (tmp_path / run_id).mkdir()
    (tmp_path / run_id / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(ResultsCorruptError, match=missing):
        load_run(run_id, tmp_path)


def test_unknown_id_is_not_found(tmp_path):
    with pytest.raises(ResultsNotFoundError):
        load_run(new_run_id("greenlee"), tmp_path)


@pytest.mark.parametrize("bad", ["../x", "a/b", "a\\b", "..", "", "nope",
                                 "20260101T000000Z_Greenlee_abcdef",
                                 "20260101T000000Z_greenlee_abcdef/..",
                                 "20260101T000000Z_greenlee_abcdef\n"])
def test_bad_run_ids_are_rejected_before_any_path_is_built(tmp_path, bad):
    with pytest.raises(ResultsError):
        save_run(record(bad), tmp_path)
    with pytest.raises(ResultsError):
        load_run(bad, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_list_runs_skips_logs_and_corrupt_runs_with_warnings(tmp_path, caplog):
    first = make(tmp_path, "entes")
    second = make(tmp_path, "greenlee")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "a.log").write_text("x")
    write_raw(tmp_path, "{broken")
    (tmp_path / "badname").mkdir()
    (tmp_path / "badname" / "run.json").write_text("{}", encoding="utf-8")
    (tmp_path / "stray.txt").write_text("x")
    with caplog.at_level(logging.WARNING):
        runs = list_runs(tmp_path)
    assert [r["run_id"] for r in runs] == sorted([first, second])
    assert set(runs[0]) == {"run_id", "ammeter", "started_at_utc", "path"}
    assert len(caplog.records) == 2


def test_list_runs_of_a_missing_folder_is_empty(tmp_path):
    assert list_runs(tmp_path / "nope") == []


def test_compare_runs_deltas(tmp_path):
    a = make(tmp_path, "greenlee", mean=2.0)
    b = make(tmp_path, "greenlee", mean=5.0)
    result = compare_runs(a, b, tmp_path)
    assert result["same_ammeter"] is True
    assert result["statistics"]["mean"] == {"a": 2.0, "b": 5.0, "delta": 3.0}


def test_compare_runs_keeps_none_and_flags_other_ammeters(tmp_path):
    a = make(tmp_path, "greenlee", mean=None)
    b = make(tmp_path, "entes", mean=5.0)
    result = compare_runs(a, b, tmp_path)
    assert result["same_ammeter"] is False
    assert result["statistics"]["mean"] == {"a": None, "b": 5.0, "delta": None}


def test_failed_save_leaves_no_folder_and_a_retry_succeeds(tmp_path):
    run_id = new_run_id("greenlee")
    bad = record(run_id)
    bad["parameters"] = {"x": object()}
    with pytest.raises(ResultsWriteError):
        save_run(bad, tmp_path)
    assert list(tmp_path.iterdir()) == []
    save_run(record(run_id), tmp_path)
    assert load_run(run_id, tmp_path)["run_id"] == run_id


def test_colliding_run_is_never_touched_by_a_failed_save(tmp_path):
    run_id = make(tmp_path)
    before = (tmp_path / run_id / "run.json").read_bytes()
    with pytest.raises(ResultsWriteError):
        save_run(record(run_id), tmp_path)
    assert (tmp_path / run_id / "run.json").read_bytes() == before


@pytest.mark.parametrize("key,value", [("statistics", []), ("parameters", "x"),
                                       ("readings", {})])
def test_wrong_container_types_are_corrupt(tmp_path, key, value):
    run_id = new_run_id("greenlee")
    rec = record(run_id)
    rec[key] = value
    (tmp_path / run_id).mkdir()
    (tmp_path / run_id / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(ResultsCorruptError, match=key):
        load_run(run_id, tmp_path)


def test_record_with_another_run_id_is_corrupt(tmp_path):
    run_id = new_run_id("greenlee")
    other = new_run_id("greenlee")
    (tmp_path / run_id).mkdir()
    (tmp_path / run_id / "run.json").write_text(json.dumps(record(other)), encoding="utf-8")
    with pytest.raises(ResultsCorruptError, match="run_id"):
        load_run(run_id, tmp_path)


def test_compare_runs_non_numeric_metric_gives_none_delta(tmp_path):
    a = make(tmp_path, "greenlee", mean=2.0)
    b = make(tmp_path, "greenlee", mean="oops")
    assert compare_runs(a, b, tmp_path)["statistics"]["mean"]["delta"] is None


def test_unreadable_results_dir_raises_results_error(tmp_path, monkeypatch):
    def boom(self):
        raise PermissionError("denied")
    monkeypatch.setattr(type(tmp_path), "iterdir", boom)
    with pytest.raises(ResultsError, match="denied"):
        list_runs(tmp_path)


def test_data_is_synced_before_the_atomic_rename(tmp_path, monkeypatch):
    calls = []
    real_fsync, real_replace = os.fsync, type(tmp_path).replace
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(type(tmp_path), "replace",
                        lambda self, target: (calls.append("replace"),
                                              real_replace(self, target))[1])
    make(tmp_path)
    assert calls == ["fsync", "replace"]


def test_reserve_run_creates_the_folder_and_save_run_fills_it(tmp_path):
    run_id = reserve_run("greenlee", tmp_path)
    assert (tmp_path / run_id).is_dir() and not (tmp_path / run_id / "run.json").exists()
    assert save_run(record(run_id), tmp_path) == tmp_path / run_id / "run.json"


def test_reserve_run_skips_a_taken_id(tmp_path, monkeypatch):
    taken = make(tmp_path)
    ids = iter([taken, "20260101T000000Z_greenlee_bbbbbb"])
    monkeypatch.setattr("src.utils.results.new_run_id", lambda ammeter: next(ids))
    assert reserve_run("greenlee", tmp_path) == "20260101T000000Z_greenlee_bbbbbb"
    assert (tmp_path / taken / "run.json").exists()


def test_reserve_run_gives_up_after_the_attempts(tmp_path, monkeypatch):
    taken = make(tmp_path)
    monkeypatch.setattr("src.utils.results.new_run_id", lambda ammeter: taken)
    with pytest.raises(ResultsWriteError, match="no free run id"):
        reserve_run("greenlee", tmp_path, attempts=3)


def test_release_run_removes_only_an_empty_folder(tmp_path):
    empty = reserve_run("greenlee", tmp_path)
    full = make(tmp_path)
    release_run(empty, tmp_path)
    release_run(full, tmp_path)
    assert not (tmp_path / empty).exists() and (tmp_path / full / "run.json").exists()
