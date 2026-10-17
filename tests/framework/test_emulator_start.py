"""Starting and stopping configured emulators."""
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from src.testing.emulators import load_emulator_class, start_emulators, stop_emulators
from src.utils.config import load_config
from src.utils.errors import ConfigError, EmulatorStartError
from tests.helpers import HOST, running_emulator

SHIPPED = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def zero_ports(config):
    return {name: 0 for name in config.ammeters}


def with_emulator(config, name, emulator):
    settings = replace(config.ammeters[name], emulator=emulator)
    return replace(config, ammeters={**config.ammeters, name: settings})


def test_each_emulator_is_ready_on_its_real_port():
    config = load_config(SHIPPED)
    running = start_emulators(config, zero_ports(config))
    try:
        assert set(running) == set(config.ammeters)
        assert all(r.port != 0 and r.emulator.ready.is_set() for r in running.values())
    finally:
        stop_emulators(running)


def test_entries_without_emulator_are_skipped():
    config = load_config(SHIPPED)
    config = with_emulator(config, "entes", None)
    running = start_emulators(config, zero_ports(config))
    try:
        assert set(running) == {"greenlee", "circutor"}
    finally:
        stop_emulators(running)


def test_port_is_released_after_stop():
    config = load_config(SHIPPED)
    running = start_emulators(config, zero_ports(config))
    port = running["greenlee"].port
    stop_emulators(running)
    start = time.monotonic()
    again = start_emulators(config, {**zero_ports(config), "greenlee": port})
    try:
        assert again["greenlee"].port == port
        assert time.monotonic() - start < 1
    finally:
        stop_emulators(again)


@pytest.mark.parametrize("path", ["no.such.module:Thing", "Ammeters.Greenlee_Ammeter:Nope",
                                  "nocolon", "Ammeters.client:request_current_from_ammeter",
                                  "src.utils.config:SamplingPlan"])
def test_bad_emulator_path_names_the_key(path):
    config = with_emulator(load_config(SHIPPED), "entes", path)
    with pytest.raises(ConfigError, match=r"ammeters\.entes\.emulator"):
        load_emulator_class(config.ammeters["entes"])
    with pytest.raises(ConfigError, match=r"ammeters\.entes\.emulator"):
        start_emulators(config, zero_ports(config))


def test_bind_failure_raises_start_error_and_stops_the_others(recwarn):
    config = load_config(SHIPPED)
    before = set(threading.enumerate())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind((HOST, 0))
        holder.listen()
        held = holder.getsockname()[1]
        with pytest.raises(EmulatorStartError) as info:
            start_emulators(config, {**zero_ports(config), "entes": held})
    message = str(info.value)
    assert "entes" in message and str(held) in message
    assert "in use" in message.lower() or "errno" in message.lower() or "[" in message
    assert not [t for t in set(threading.enumerate()) - before if t.is_alive()]
    assert len(recwarn) == 0


def test_wrong_command_is_dropped_at_once_without_waiting_for_the_timeout() -> None:
    with running_emulator(GreenleeAmmeter, recv_timeout_s=2.0) as emulator:
        with socket.create_connection((HOST, emulator.port), timeout=2) as s:
            s.sendall(b"MEASURE_UNKNOWN")
            start = time.monotonic()
            assert s.recv(1024) == b""
            assert time.monotonic() - start < 0.5


CP1252_SCRIPT = """
from Ammeters.client import request_current_from_ammeter
from src.testing.emulators import start_emulators, stop_emulators
from src.utils.config import DEFAULT_CONFIG_PATH, load_config

config = load_config(DEFAULT_CONFIG_PATH)
running = start_emulators(config, {name: 0 for name in config.ammeters})
try:
    for name, settings in config.ammeters.items():
        print("READING", name, request_current_from_ammeter(running[name].port, settings.command))
finally:
    stop_emulators(running)
"""


def test_readings_survive_a_cp1252_console():
    """Greenlee prints an omega; start_emulators must keep that from losing the reply."""
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    done = subprocess.run([sys.executable, "-c", CP1252_SCRIPT], cwd=SHIPPED.parents[1],
                          env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    readings = [line.split() for line in done.stdout.splitlines() if line.startswith("READING")]
    assert [(r[1], float(r[2]) > 0) for r in readings] == [
        ("greenlee", True), ("entes", True), ("circutor", True)]
