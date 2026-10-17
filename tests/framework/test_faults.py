"""The seeded fault injector."""
import ast
import logging
import random
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

import src.testing.faults as faults_module
from Ammeters.client import request_current_from_ammeter
from src.testing.faults import GARBAGE_REPLIES, FaultInjector, fault_sequence
from src.utils.config import FAULT_TYPES, ErrorSimulation
from src.utils.errors import NonNumericResponseError
from tests.helpers import fake_server

MIX = {"no_response": 0.1, "stall": 0.2, "garbage": 0.3, "out_of_range": 0.15}


def sim(**kw) -> ErrorSimulation:
    """An ErrorSimulation with seed 7 and a short resolved stall unless given."""
    kw.setdefault("seed", 7)
    if kw.get("stall", 0) > 0:
        kw.setdefault("stall_seconds", 0.05)
    return ErrorSimulation(**kw)


def decisions(simulation: ErrorSimulation, count: int) -> list[str | None]:
    """The first `count` decisions of a new injector."""
    injector = FaultInjector(simulation, "t")
    return [injector.next_fault() for _ in range(count)]


def test_same_seed_gives_the_same_sequence():
    assert decisions(sim(garbage=0.5), 100) == decisions(sim(garbage=0.5), 100)


def test_other_seed_gives_another_sequence():
    assert decisions(sim(garbage=0.5), 100) != decisions(sim(seed=8, garbage=0.5), 100)


def test_injector_follows_fault_sequence():
    simulation = sim(**MIX)
    sequence = fault_sequence(simulation, 200)
    assert {*sequence} == {None, *FAULT_TYPES}
    assert decisions(simulation, 200) == sequence


def test_sequence_ignores_the_global_random_state():
    random.seed(1)
    first = decisions(sim(**MIX), 100)
    random.seed(2)
    assert decisions(sim(**MIX), 100) == first


def test_injector_does_not_touch_the_global_random_state():
    state = random.getstate()
    decisions(sim(**MIX), 1000)
    assert random.getstate() == state


def test_faults_module_never_calls_global_random_functions():
    tree = ast.parse(Path(faults_module.__file__).read_text(encoding="utf-8"))
    uses = [node for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "random"]
    assert uses
    assert all(node.attr == "Random" for node in uses)
    assert not [node for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "random"]


def test_probabilities_hold_on_a_large_sample():
    sequence = fault_sequence(sim(**MIX), 100_000)
    counts = Counter(sequence)
    for fault, chance in MIX.items():
        assert counts[fault] / len(sequence) == pytest.approx(chance, abs=0.01)
    assert counts[None] / len(sequence) == pytest.approx(0.25, abs=0.01)


def test_zero_probability_type_never_occurs():
    injector = FaultInjector(sim(garbage=0.5), "t")
    seen = {injector.next_fault() for _ in range(1000)}
    assert seen <= {None, "garbage"}
    counts = injector.counts
    assert set(counts) == set(FAULT_TYPES)
    assert counts["stall"] == counts["no_response"] == counts["out_of_range"] == 0
    counts["garbage"] = -1
    assert injector.counts["garbage"] > 0


def test_decisions_are_thread_safe():
    simulation = sim(**MIX)
    injector = FaultInjector(simulation, "t")

    def work() -> None:
        for _ in range(1000):
            injector.next_fault()

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    expected = Counter(fault_sequence(simulation, 8000))
    assert injector.decisions == 8000
    assert injector.counts == {fault: expected[fault] for fault in FAULT_TYPES}


class SignallingEvent(threading.Event):
    """An Event that signals when some thread starts waiting on it."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()

    def wait(self, timeout: float | None = None) -> bool:
        self.entered.set()
        return super().wait(timeout)


def test_lock_is_not_held_during_a_stall():
    injector = FaultInjector(sim(stall=1.0, stall_seconds=1.0), "t")
    stop = SignallingEvent()
    thread = threading.Thread(target=injector.respond, args=(1.0, stop))
    thread.start()
    try:
        assert stop.entered.wait(2)
        started = time.monotonic()
        injector.next_fault()
        assert time.monotonic() - started < 0.2
    finally:
        stop.set()
        thread.join(2)


@pytest.mark.parametrize("draw, expected", [
    (0.05, "no_response"), (0.1, "stall"), (0.35, "garbage"), (0.7, "out_of_range"),
    (0.9, None)])
def test_pick_uses_cumulative_thresholds_in_fixed_order(draw, expected):
    assert faults_module._pick(draw, sim(**MIX)) == expected


def test_stall_without_resolved_seconds_is_rejected():
    with pytest.raises(ValueError, match="stall_seconds must be resolved"):
        FaultInjector(ErrorSimulation(seed=7, stall=0.5), "t")


def test_no_fault_reply_is_the_base_format():
    simulation = sim(garbage=1e-9)
    assert fault_sequence(simulation, 1) == [None]
    assert FaultInjector(simulation, "t").respond(1.25, threading.Event()) == b"1.25"


@pytest.mark.parametrize("fault", FAULT_TYPES)
def test_each_fault_type_reply(fault):
    injector = FaultInjector(sim(**{fault: 1.0}, stall_seconds=0.05), "t")
    event = threading.Event()
    if fault == "no_response":
        assert injector.respond(1.25, event) is None
    elif fault == "garbage":
        replies = tuple(injector.respond(1.25, event) for _ in GARBAGE_REPLIES)
        assert replies == GARBAGE_REPLIES
    elif fault == "out_of_range":
        assert injector.respond(1.25, event) == b"1250.0"
    else:
        started = time.monotonic()
        assert injector.respond(1.25, event) is None
        assert time.monotonic() - started >= 0.05


@pytest.mark.parametrize("payload", GARBAGE_REPLIES)
def test_every_garbage_reply_is_rejected_by_the_client_parser(payload):
    with fake_server(payload) as port:
        with pytest.raises(NonNumericResponseError):
            request_current_from_ammeter(port, b"X")


def test_stall_returns_at_once_when_stop_is_set():
    injector = FaultInjector(sim(stall=1.0, stall_seconds=5), "t")
    event = threading.Event()
    threading.Timer(0.1, event.set).start()
    started = time.monotonic()
    assert injector.respond(1.0, event) is None
    assert time.monotonic() - started < 0.5


def test_each_decision_is_logged_at_debug(caplog):
    injector = FaultInjector(sim(garbage=1.0), "meter")
    with caplog.at_level(logging.DEBUG, logger="src.testing.faults"):
        injector.next_fault()
    assert any("meter" in r.getMessage() and "garbage" in r.getMessage()
               for r in caplog.records)
