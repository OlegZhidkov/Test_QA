"""Shared test helpers. Every socket binds 127.0.0.1."""
import socket
import threading
from contextlib import contextmanager
from typing import Iterator

from Ammeters.base_ammeter import AmmeterEmulatorBase

HOST = "127.0.0.1"


def unused_port() -> int:
    """Return a port that was free a moment ago."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _serve_one(conn: socket.socket, reply: bytes | None, silent: bool,
               stop: threading.Event) -> None:
    """Handle one fake-device connection."""
    with conn:
        if silent:
            stop.wait()
            return
        conn.settimeout(1.0)
        try:
            while conn.recv(1024):
                pass
            if reply is not None:
                conn.sendall(reply)
        except OSError:
            return


@contextmanager
def fake_server(reply: bytes | None = None, silent: bool = False) -> Iterator[int]:
    """Run a fake device and yield its port.

    It sends `reply` and closes, closes without data when `reply` is None,
    or keeps the connection open without answering when `silent` is True.
    """
    stop = threading.Event()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((HOST, 0))
        server.listen()
        server.settimeout(0.1)

        def accept_loop() -> None:
            while not stop.is_set():
                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                threading.Thread(target=_serve_one, args=(conn, reply, silent, stop),
                                 daemon=True).start()

        thread = threading.Thread(target=accept_loop, daemon=True)
        thread.start()
        try:
            yield server.getsockname()[1]
        finally:
            stop.set()
            thread.join(2)


@contextmanager
def running_emulator(cls: type[AmmeterEmulatorBase], port: int = 0,
                     **kwargs) -> Iterator[AmmeterEmulatorBase]:
    """Start an emulator in a daemon thread, yield it once ready, then stop it."""
    emulator = cls(port, **kwargs)
    thread = threading.Thread(target=emulator.start_server, daemon=True)
    thread.start()
    if not emulator.ready.wait(5):
        emulator.stop()
        raise RuntimeError(f"{cls.__name__} did not become ready")
    try:
        yield emulator
    finally:
        emulator.stop()
        thread.join(2)
