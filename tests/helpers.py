"""Shared test helpers. Every socket binds 127.0.0.1."""
import socket
import statistics
import threading
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

from Ammeters.base_ammeter import AmmeterEmulatorBase
from src.testing import analysis
from src.testing.models import Reading, RunResult, Sample
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import ExpectedRange, SamplingPlan, load_config

HOST = "127.0.0.1"
# One OS scheduling pause can delay a single reading (seen: 0.05 s idle, 0.12 s under CPU load);
# the schedule is absolute, so it never carries over. A real defect shifts many readings.
MAX_LATENESS_S = 0.15
TYPICAL_LATENESS_S = 0.025


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


CONFIG_TEMPLATE = """\
testing:
  sampling:
    measurements_count: 4
    total_duration_seconds: 0.4
    sampling_frequency_hz: NULL
  request_timeout_seconds: 2.0
  emulator_start_timeout_seconds: 5.0
ammeters:
  greenlee:
    port: {greenlee}
    command: "MEASURE_GREENLEE -get_measurement"
    emulator: "Ammeters.Greenlee_Ammeter:GreenleeAmmeter"
    expected_range: {{min_amps: 0.01, max_amps: 100.0}}
  entes:
    port: {entes}
    command: "MEASURE_ENTES -get_data"
    emulator: "Ammeters.Entes_Ammeter:EntesAmmeter"
    expected_range: {{min_amps: 5.0, max_amps: 200.0}}
  circutor:
    port: {circutor}
    command: "MEASURE_CIRCUTOR -get_measurement -current"
    emulator: "Ammeters.Circutor_Ammeter:CircutorAmmeter"
    expected_range: {{min_amps: 0.001, max_amps: 0.1}}
"""

TWO = SamplingPlan(count=2, duration_s=0.1, frequency_hz=20.0)


def write_config(path: Path, ports: Mapping[str, int]) -> Path:
    """Write a valid three-ammeter config with the given ports and return its path."""
    path.write_text(CONFIG_TEMPLATE.format(**ports), encoding="utf-8")
    return path


def make_framework(tmp_path: Path, ports: Mapping[str, int]) -> AmmeterTestFramework:
    """A framework over a written three-ammeter test config, archiving under tmp_path/results."""
    config = load_config(write_config(tmp_path / "config.yaml", ports))
    return AmmeterTestFramework(config=replace(config, results_dir=tmp_path / "results"))


def synthetic_result(values: Sequence[float | None], *, ammeter: str = "greenlee",
                     expected: tuple[float, float] = (0.01, 100.0),
                     run_id: str | None = None) -> RunResult:
    """A RunResult built from values (None is a timeout error), without any I/O."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    stamps = [(start + timedelta(seconds=i * 0.2)).isoformat(timespec="microseconds")
              for i in range(len(values) + 1)]
    readings = tuple(
        Reading(i, stamps[i], i * 0.2, i * 0.2, value,
                None if value is not None else "AmmeterTimeoutError: simulated")
        for i, value in enumerate(values))
    n = len(values)
    limits = ExpectedRange(*expected)
    parameters = {"count": n, "duration_s": n * 0.2, "frequency_hz": 5.0, "interval_s": 0.2,
                  "request_timeout_s": 2.0, "host": HOST, "port": 5000, "command": "X"}
    return RunResult(
        run_id or f"20260101T000000Z_{ammeter}_abcdef", ammeter, parameters, limits,
        Sample(readings, stamps[0], stamps[n], n * 0.2),
        analysis.compute_statistics(readings),
        tuple(analysis.out_of_range(readings, limits)))


def off_schedule(readings: Sequence[Reading]) -> list[str]:
    """Describe how the readings miss their schedule; empty when they keep it.

    A reading may be late by up to MAX_LATENESS_S (a one-off pause), but the median
    lateness must stay within TYPICAL_LATENESS_S, which catches drift and a shifted schedule.
    """
    problems = [f"reading {r.index}: {r.actual_offset_s - r.scheduled_offset_s:+.3f} s"
                for r in readings
                if abs(r.actual_offset_s - r.scheduled_offset_s) > MAX_LATENESS_S]
    median = statistics.median(r.actual_offset_s - r.scheduled_offset_s for r in readings)
    if abs(median) > TYPICAL_LATENESS_S:
        problems.append(f"median lateness {median:+.3f} s")
    return problems
