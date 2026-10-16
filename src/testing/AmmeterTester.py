"""Unified measurement API: one reading, a timed sample, and its statistics."""
import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from Ammeters.client import request_current_from_ammeter
from src.testing.analysis import compute_statistics
from src.testing.models import Reading, Sample, Statistics
from src.utils.config import AmmeterSettings, FrameworkConfig, SamplingPlan
from src.utils.errors import (
    AmmeterConnectionError,
    AmmeterTimeoutError,
    InvalidResponseError,
)

READING_ERRORS = (AmmeterConnectionError, AmmeterTimeoutError, InvalidResponseError)


class AmmeterTester:
    """Measures and samples one configured ammeter."""

    def __init__(self, settings: AmmeterSettings, sampling: SamplingPlan,
                 request_timeout_s: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 logger: logging.Logger | None = None):
        self.settings = settings
        self.sampling = sampling
        self.request_timeout_s = request_timeout_s
        self._clock = clock
        self._sleep = sleep
        self._logger = logger or logging.getLogger(__name__)

    @classmethod
    def from_config(cls, config: FrameworkConfig, name: str,
                    logger: logging.Logger | None = None) -> "AmmeterTester":
        """Build a tester for the named ammeter of a config."""
        return cls(config.settings_for(name), config.sampling, config.request_timeout_s,
                   logger=logger)

    def measure(self) -> float:
        """Take one reading in amps; raises the typed client errors."""
        s = self.settings
        return request_current_from_ammeter(s.port, s.command, s.host, self.request_timeout_s)

    def sample(self, plan: SamplingPlan | None = None) -> Sample:
        """Take plan.count readings at absolute targets t0 + i * interval."""
        plan = plan or self.sampling
        interval = plan.interval_s
        start_wall = datetime.now(UTC)
        t0 = self._clock()
        readings = []
        for i in range(plan.count):
            self._sleep_until(t0 + i * interval)
            readings.append(self._read(i, i * interval, self._clock() - t0, start_wall))
        self._sleep_until(t0 + plan.count * interval)
        elapsed = self._clock() - t0
        return Sample(tuple(readings), _iso(start_wall, 0.0), _iso(start_wall, elapsed), elapsed)

    @staticmethod
    def analyze(readings: Sequence[Reading]) -> Statistics:
        """Statistics over the readings."""
        return compute_statistics(readings)

    def _sleep_until(self, target: float) -> None:
        """Sleep until the clock reaches target; never with a negative delay."""
        delay = target - self._clock()
        if delay > 0:
            self._sleep(delay)

    def _read(self, index: int, scheduled: float, actual: float, start_wall: datetime) -> Reading:
        """One reading at the given offset; a typed client error becomes an error reading."""
        stamp = _iso(start_wall, actual)
        try:
            return Reading(index, stamp, scheduled, actual, self.measure(), None)
        except READING_ERRORS as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._logger.warning("%s reading %d failed: %s", self.settings.name, index, error)
            return Reading(index, stamp, scheduled, actual, None, error)


def _iso(start_wall: datetime, offset_s: float) -> str:
    """Wall-clock ISO timestamp (microseconds) offset_s after start_wall."""
    return (start_wall + timedelta(seconds=offset_s)).isoformat(timespec="microseconds")
