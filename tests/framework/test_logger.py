"""TestLogger writes its own file and releases it on close."""
import logging

import pytest

from src.utils.errors import ResultsWriteError
from src.utils.logger import TestLogger


def test_info_message_reaches_the_log_file(tmp_path):
    log = TestLogger("a", tmp_path / "logs")
    log.info("hello world")
    log.close()
    assert "hello world" in log.log_file.read_text(encoding="utf-8")
    assert log.log_file.parent == tmp_path / "logs"


def test_second_logger_with_same_name_has_its_own_file(tmp_path):
    first = TestLogger("same", tmp_path)
    second = TestLogger("same", tmp_path)
    second.info("only for second")
    second.close()
    first.close()
    assert first.log_file != second.log_file
    assert "only for second" not in first.log_file.read_text(encoding="utf-8")
    assert second.log_file.read_text(encoding="utf-8").count("only for second") == 1


def test_close_removes_handlers_and_releases_the_file(tmp_path):
    log = TestLogger("c", tmp_path)
    log.info("x")
    log.close()
    assert log.logger.handlers == []
    log.log_file.unlink()
    assert not log.log_file.exists()


def test_folder_is_created(tmp_path):
    target = tmp_path / "a" / "b"
    log = TestLogger("d", target)
    log.close()
    assert target.is_dir()


def test_log_dir_below_a_file_raises_results_write_error(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ResultsWriteError, match="file.txt"):
        TestLogger("e", blocker / "logs")


def test_debug_is_not_written_but_warning_is(tmp_path):
    log = TestLogger("f", tmp_path)
    log.debug("quiet")
    log.warning("loud")
    log.close()
    text = log.log_file.read_text(encoding="utf-8")
    assert "quiet" not in text and "loud" in text


def test_run_id_names_the_logger_and_the_file_and_close_removes_the_logger(tmp_path):
    log = TestLogger("g", tmp_path, run_id="20260101T000000Z_g_abcdef")
    assert "20260101T000000Z_g_abcdef" in log.logger.name
    assert "20260101T000000Z_g_abcdef" in log.log_file.name
    log.close()
    assert log.logger.name not in logging.Logger.manager.loggerDict


def test_loggers_for_different_runs_do_not_share_handlers(tmp_path):
    first = TestLogger("h", tmp_path, run_id="20260101T000000Z_h_000001")
    second = TestLogger("h", tmp_path, run_id="20260101T000000Z_h_000002")
    first.close()
    second.info("still open")
    second.close()
    assert "still open" in second.log_file.read_text(encoding="utf-8")
