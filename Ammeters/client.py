"""Client that requests one current reading from an ammeter over TCP."""
import math
import socket

from src.utils.errors import (
    AmmeterConnectionError,
    AmmeterTimeoutError,
    EmptyResponseError,
    NonNumericResponseError,
)


def request_current_from_ammeter(port: int, command: bytes, host: str = "127.0.0.1",
                                 timeout_s: float = 2.0) -> float:
    """Send one command to an ammeter and return the reading in amps.

    Raises AmmeterTimeoutError, AmmeterConnectionError, EmptyResponseError or
    NonNumericResponseError; each message names the host and port.
    """
    try:
        with socket.create_connection((host, port), timeout_s) as s:
            s.sendall(command)
            s.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = s.recv(1024)
                if not chunk:
                    break
                chunks.append(chunk)
    except TimeoutError as exc:
        raise AmmeterTimeoutError(f"{host}:{port}: timed out after {timeout_s} s: {exc}") from exc
    except OSError as exc:
        raise AmmeterConnectionError(f"{host}:{port}: connection failed: {exc}") from exc

    data = b"".join(chunks)
    if not data:
        raise EmptyResponseError(f"{host}:{port}: the ammeter sent no data")
    try:
        value = float(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise NonNumericResponseError(
            f"{host}:{port}: reply is not a number: {data[:50]!r}") from exc
    if not math.isfinite(value):
        raise NonNumericResponseError(f"{host}:{port}: reply is not finite: {data[:50]!r}")
    return value
