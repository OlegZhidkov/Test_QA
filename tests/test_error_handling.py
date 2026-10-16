"""The client turns every failure into a typed error."""
import time

import pytest

from Ammeters.client import request_current_from_ammeter
from src.utils.errors import (
    AmmeterConnectionError,
    AmmeterTimeoutError,
    EmptyResponseError,
    NonNumericResponseError,
)
from tests.helpers import fake_server, unused_port

COMMAND = b"MEASURE_TEST"


def test_connection_refused_raises_connection_error() -> None:
    with pytest.raises(AmmeterConnectionError):
        request_current_from_ammeter(unused_port(), COMMAND, timeout_s=0.5)


def test_silent_device_raises_timeout_error() -> None:
    with fake_server(silent=True) as port:
        start = time.monotonic()
        with pytest.raises(AmmeterTimeoutError):
            request_current_from_ammeter(port, COMMAND, timeout_s=0.3)
        assert time.monotonic() - start < 1


def test_empty_reply_raises_empty_response_error() -> None:
    with fake_server(None) as port:
        with pytest.raises(EmptyResponseError):
            request_current_from_ammeter(port, COMMAND)


def test_non_numeric_reply_raises_non_numeric_response_error() -> None:
    with fake_server(b"abc") as port:
        with pytest.raises(NonNumericResponseError):
            request_current_from_ammeter(port, COMMAND)


def test_nan_reply_raises_non_numeric_response_error() -> None:
    with fake_server(b"nan") as port:
        with pytest.raises(NonNumericResponseError):
            request_current_from_ammeter(port, COMMAND)


def test_numeric_reply_is_returned_as_float() -> None:
    with fake_server(b"1.25") as port:
        assert request_current_from_ammeter(port, COMMAND) == 1.25
