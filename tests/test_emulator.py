"""The emulator survives odd clients and still matches commands byte for byte."""
import socket
import struct
import time

import pytest

from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from src.utils.errors import EmptyResponseError
from tests.helpers import HOST, running_emulator

COMMAND = GreenleeAmmeter(0).get_current_command


def _raw_exchange(port: int, chunks: list[bytes], pause_s: float = 0.0) -> bytes:
    """Send the chunks on a raw socket, half-close and return what comes back."""
    with socket.create_connection((HOST, port), timeout=2) as s:
        for i, chunk in enumerate(chunks):
            if i:
                time.sleep(pause_s)
            s.sendall(chunk)
        s.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            part = s.recv(1024)
            if not part:
                return data
            data += part


def test_emulator_replies_with_a_number_to_its_command() -> None:
    """The emulator answers its own command with a positive number."""
    with running_emulator(GreenleeAmmeter) as emulator:
        assert request_current_from_ammeter(emulator.port, COMMAND) > 0


def test_command_with_trailing_bytes_gets_no_data() -> None:
    """A command followed by extra bytes gets no data."""
    with running_emulator(GreenleeAmmeter) as emulator:
        assert _raw_exchange(emulator.port, [COMMAND + b"x"]) == b""


def test_command_split_across_two_sends_is_accepted() -> None:
    """A command that arrives in two segments is still accepted."""
    with running_emulator(GreenleeAmmeter) as emulator:
        data = _raw_exchange(emulator.port, [COMMAND[:10], COMMAND[10:]], pause_s=0.05)
        assert float(data.decode("utf-8")) > 0


def test_silent_client_does_not_block_the_next_client() -> None:
    """A client that connects and sends nothing does not block the next one."""
    with running_emulator(GreenleeAmmeter, recv_timeout_s=0.3) as emulator:
        with socket.create_connection((HOST, emulator.port), timeout=2):
            start = time.monotonic()
            assert request_current_from_ammeter(emulator.port, COMMAND, timeout_s=2) > 0
            assert time.monotonic() - start < 0.3 + 1


def test_client_disconnect_does_not_stop_the_emulator() -> None:
    """A client that resets the connection does not stop the emulator."""
    with running_emulator(GreenleeAmmeter) as emulator:
        s = socket.create_connection((HOST, emulator.port), timeout=2)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        s.close()
        assert request_current_from_ammeter(emulator.port, COMMAND) > 0


class _FailingOnceAmmeter(GreenleeAmmeter):
    """Emulator whose first measurement raises an encoding error."""

    def __init__(self, port: int, recv_timeout_s: float = 2.0) -> None:
        """Create the emulator with a call counter."""
        super().__init__(port, recv_timeout_s)
        self._calls = 0

    def measure_current(self) -> float:
        """Raise on the first call, return 1.0 afterwards."""
        self._calls += 1
        if self._calls == 1:
            raise UnicodeEncodeError("charmap", "Ω", 0, 1,
                                     "character maps to <undefined>")
        return 1.0


def test_measurement_error_does_not_stop_the_emulator() -> None:
    """An error in measure_current() drops that reply but the emulator keeps serving."""
    with running_emulator(_FailingOnceAmmeter) as emulator:
        with pytest.raises(EmptyResponseError):
            request_current_from_ammeter(emulator.port, COMMAND)
        assert request_current_from_ammeter(emulator.port, COMMAND) == 1.0
