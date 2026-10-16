"""The client turns every failure into a typed error."""
import socket
import time
from pathlib import Path

import pytest

from Ammeters.client import request_current_from_ammeter
from src.testing.emulators import start_emulators
from src.utils.config import load_config
from src.utils.errors import (
    AmmeterConnectionError,
    AmmeterTimeoutError,
    EmptyResponseError,
    EmulatorStartError,
    NonNumericResponseError,
)
from tests.helpers import HOST, fake_server, unused_port

COMMAND = b"MEASURE_TEST"


def test_connection_refused_raises_connection_error() -> None:
    """A port nobody listens on raises AmmeterConnectionError."""
    with pytest.raises(AmmeterConnectionError):
        request_current_from_ammeter(unused_port(), COMMAND, timeout_s=0.5)


def test_silent_device_raises_timeout_error() -> None:
    """A device that never replies raises AmmeterTimeoutError, quickly."""
    with fake_server(silent=True) as port:
        start = time.monotonic()
        with pytest.raises(AmmeterTimeoutError):
            request_current_from_ammeter(port, COMMAND, timeout_s=0.3)
        assert time.monotonic() - start < 1


def test_empty_reply_raises_empty_response_error() -> None:
    """A connection closed without data raises EmptyResponseError."""
    with fake_server(None) as port:
        with pytest.raises(EmptyResponseError):
            request_current_from_ammeter(port, COMMAND)


def test_non_numeric_reply_raises_non_numeric_response_error() -> None:
    """A reply that is not a number raises NonNumericResponseError."""
    with fake_server(b"abc") as port:
        with pytest.raises(NonNumericResponseError):
            request_current_from_ammeter(port, COMMAND)


def test_nan_reply_raises_non_numeric_response_error() -> None:
    """A reply of nan raises NonNumericResponseError."""
    with fake_server(b"nan") as port:
        with pytest.raises(NonNumericResponseError):
            request_current_from_ammeter(port, COMMAND)


def test_numeric_reply_is_returned_as_float() -> None:
    """A numeric reply is returned as a float."""
    with fake_server(b"1.25") as port:
        assert request_current_from_ammeter(port, COMMAND) == 1.25


def test_port_already_in_use_raises_emulator_start_error() -> None:
    """Starting an emulator on a busy port raises EmulatorStartError."""
    config = load_config(Path(__file__).resolve().parent.parent / "config" / "config.yaml")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind((HOST, 0))
        holder.listen()
        held = holder.getsockname()[1]
        overrides = {name: 0 for name in config.ammeters}
        overrides[next(iter(config.ammeters))] = held
        with pytest.raises(EmulatorStartError, match=str(held)):
            start_emulators(config, overrides)
