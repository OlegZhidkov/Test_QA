"""The emulator's optional fault hook and its wiring in start_emulators."""
import logging
import threading
import time
from dataclasses import replace

import pytest

from Ammeters.base_ammeter import ACCEPT_TIMEOUT_S
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from src.testing.emulators import start_emulators, stop_emulators
from src.testing.faults import FaultInjector, fault_sequence
from src.utils.config import ErrorSimulation, load_config
from src.utils.errors import (
    AmmeterTimeoutError,
    EmptyResponseError,
    NonNumericResponseError,
)
from tests.framework.test_config import SHIPPED
from tests.helpers import running_emulator

COMMAND = GreenleeAmmeter(0).get_current_command


def sim(**kw) -> ErrorSimulation:
    """An ErrorSimulation with seed 7 unless given."""
    kw.setdefault("seed", 7)
    return ErrorSimulation(**kw)


def faulty(**kw):
    """A running Greenlee emulator with an injector for sim(**kw)."""
    return running_emulator(GreenleeAmmeter,
                            fault_injector=FaultInjector(sim(**kw), "greenlee").respond)


def test_no_response_fault_gives_empty_response_error():
    with faulty(no_response=1.0) as emulator:
        with pytest.raises(EmptyResponseError):
            request_current_from_ammeter(emulator.port, COMMAND)


def test_stall_fault_gives_timeout_error():
    with faulty(stall=1.0, stall_seconds=0.5) as emulator:
        with pytest.raises(AmmeterTimeoutError):
            request_current_from_ammeter(emulator.port, COMMAND, timeout_s=0.2)


def test_garbage_fault_gives_non_numeric_response_error():
    with faulty(garbage=1.0) as emulator:
        with pytest.raises(NonNumericResponseError):
            request_current_from_ammeter(emulator.port, COMMAND)


def test_out_of_range_fault_gives_a_spiked_valid_reading():
    with faulty(out_of_range=1.0, spike_factor=1e6) as emulator:
        assert request_current_from_ammeter(emulator.port, COMMAND) > 1e4


def test_stop_during_a_stall_ends_the_server_promptly():
    emulator = GreenleeAmmeter(
        0, fault_injector=FaultInjector(sim(stall=1.0, stall_seconds=5), "greenlee").respond)
    thread = threading.Thread(target=emulator.start_server, daemon=True)
    thread.start()
    assert emulator.ready.wait(5)
    with pytest.raises(AmmeterTimeoutError):
        request_current_from_ammeter(emulator.port, COMMAND, timeout_s=0.2)
    started = time.monotonic()
    emulator.stop()
    thread.join(1)
    assert not thread.is_alive()
    assert time.monotonic() - started < ACCEPT_TIMEOUT_S + 0.8


def test_server_keeps_serving_after_each_fault_type():
    simulation = sim(garbage=0.5, no_response=0.5)
    expected = fault_sequence(simulation, 6)
    outcomes = {"no_response": EmptyResponseError, "garbage": NonNumericResponseError}
    with faulty(garbage=0.5, no_response=0.5) as emulator:
        for fault in expected:
            with pytest.raises(outcomes[fault]):
                request_current_from_ammeter(emulator.port, COMMAND)


def test_raising_hook_drops_the_connection_and_keeps_serving(caplog):
    calls = []

    def hook(current, stop):
        calls.append(current)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return b"1.5"

    with caplog.at_level(logging.ERROR, logger="Ammeters.base_ammeter"):
        with running_emulator(GreenleeAmmeter, fault_injector=hook) as emulator:
            with pytest.raises(EmptyResponseError):
                request_current_from_ammeter(emulator.port, COMMAND)
            assert request_current_from_ammeter(emulator.port, COMMAND) == 1.5
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_without_injector_the_reply_is_unchanged():
    assert GreenleeAmmeter(0).fault_injector is None
    with running_emulator(GreenleeAmmeter) as emulator:
        assert 0.01 <= request_current_from_ammeter(emulator.port, COMMAND) <= 100


def test_start_emulators_wires_injectors_only_where_configured():
    config = load_config(SHIPPED)
    entes = replace(config.ammeters["entes"],
                    simulate_errors=ErrorSimulation(seed=1, garbage=0.5))
    config = replace(config, ammeters={**config.ammeters, "entes": entes})
    running = start_emulators(config, {name: 0 for name in config.ammeters})
    try:
        assert isinstance(running["entes"].injector, FaultInjector)
        assert running["greenlee"].injector is None
        assert running["circutor"].injector is None
        assert running["entes"].emulator.fault_injector == running["entes"].injector.respond
    finally:
        stop_emulators(running)
