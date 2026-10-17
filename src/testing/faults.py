"""Seeded, thread-safe fault decisions and replies for error simulation."""
import logging
import random
import threading

from src.utils.config import FAULT_TYPES, ErrorSimulation

logger = logging.getLogger(__name__)

GARBAGE_REPLIES: tuple[bytes, ...] = (b"ERROR", b"--.--", b"12.3A", b"\xff\xfe")


def fault_sequence(simulation: ErrorSimulation, count: int) -> list[str | None]:
    """The first `count` fault decisions for the simulation's seed; None means no fault."""
    rng = random.Random(simulation.seed)
    return [_pick(rng.random(), simulation) for _ in range(count)]


class FaultInjector:
    """Decides, per served request, whether and how an emulator misbehaves."""

    def __init__(self, simulation: ErrorSimulation, name: str):
        self._simulation = simulation
        self._name = name
        self._rng = random.Random(simulation.seed)
        self._lock = threading.Lock()
        self._counts = {fault: 0 for fault in FAULT_TYPES}
        self._decisions = 0

    @property
    def counts(self) -> dict[str, int]:
        """A copy of the number of injected faults per type, zeros included."""
        with self._lock:
            return dict(self._counts)

    @property
    def decisions(self) -> int:
        """How many requests have been decided so far."""
        with self._lock:
            return self._decisions

    def next_fault(self) -> str | None:
        """Decide the next request: a fault type or None."""
        return self._decide()[0]

    def respond(self, current: float, stop: threading.Event) -> bytes | None:
        """Emulator hook: the reply bytes for this request, or None to close without data."""
        fault, garbage_index = self._decide()
        if fault is None:
            return str(current).encode("utf-8")
        if fault == "stall":
            stop.wait(self._simulation.stall_seconds or 0.0)
            return None
        if fault == "garbage":
            return GARBAGE_REPLIES[garbage_index % len(GARBAGE_REPLIES)]
        if fault == "out_of_range":
            return str(current * self._simulation.spike_factor).encode("utf-8")
        return None

    def _decide(self) -> tuple[str | None, int]:
        """Draw, count and log one decision; returns the fault and the garbage index."""
        with self._lock:
            fault = _pick(self._rng.random(), self._simulation)
            index = self._decisions
            self._decisions += 1
            if fault is not None:
                self._counts[fault] += 1
            label = "no fault" if fault is None else fault
            if fault == "stall":
                label = f"stall {self._simulation.stall_seconds} s"
            logger.debug("%s: request %d: %s", self._name, index, label)
            return fault, self._counts["garbage"] - 1 if fault == "garbage" else -1


def _pick(draw: float, simulation: ErrorSimulation) -> str | None:
    """Map a draw in [0, 1) to a fault type by cumulative probability, else None."""
    cumulative = 0.0
    for fault, chance in simulation.probabilities().items():
        cumulative += chance
        if draw < cumulative:
            return fault
    return None
