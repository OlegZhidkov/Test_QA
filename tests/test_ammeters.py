"""Public suite: every configured ammeter, end to end against its emulator."""
import math
import time

import pytest

from Ammeters.client import request_current_from_ammeter
from src.testing.analysis import out_of_range
from src.utils.errors import EmptyResponseError

IGNORED_REPLY_LIMIT_S = 0.5


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
