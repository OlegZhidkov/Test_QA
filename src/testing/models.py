"""Result dataclasses shared by the sampler, analysis, archive and report."""
from dataclasses import dataclass
from pathlib import Path

from src.utils.config import ExpectedRange


@dataclass(frozen=True)
class Reading:
    """One measurement: a value in amps, or an error string."""

    index: int
    timestamp_utc: str
    scheduled_offset_s: float
    actual_offset_s: float
    value_amps: float | None
    error: str | None

    @property
    def ok(self) -> bool:
        """True if the reading holds a value."""
        return self.error is None and self.value_amps is not None

    def to_dict(self) -> dict:
        """JSON-ready form."""
        return {"index": self.index, "timestamp_utc": self.timestamp_utc,
                "scheduled_offset_s": self.scheduled_offset_s,
                "actual_offset_s": self.actual_offset_s,
                "value_amps": self.value_amps, "error": self.error}


@dataclass(frozen=True)
class Sample:
    """All readings of one sampling pass."""

    readings: tuple[Reading, ...]
    started_at_utc: str
    finished_at_utc: str
    elapsed_s: float


@dataclass(frozen=True)
class Statistics:
    """Statistics over the valid readings; None where undefined."""

    count: int
    valid_count: int
    error_count: int
    mean: float | None
    median: float | None
    stdev: float | None
    min: float | None
    max: float | None
    cv_percent: float | None

    def to_dict(self) -> dict:
        """JSON-ready form."""
        return {"count": self.count, "valid_count": self.valid_count,
                "error_count": self.error_count, "mean": self.mean, "median": self.median,
                "stdev": self.stdev, "min": self.min, "max": self.max,
                "cv_percent": self.cv_percent}


@dataclass(frozen=True)
class RunResult:
    """Everything known about one finished run."""

    run_id: str
    ammeter: str
    parameters: dict
    expected_range: ExpectedRange
    sample: Sample
    statistics: Statistics
    out_of_range: tuple[Reading, ...]
    archive_path: Path | None = None
    simulation: dict | None = None

    def to_dict(self) -> dict:
        """The run.json record; archive_path is left out, simulation only when set."""
        record = {
            "run_id": self.run_id,
            "ammeter": self.ammeter,
            "started_at_utc": self.sample.started_at_utc,
            "finished_at_utc": self.sample.finished_at_utc,
            "elapsed_s": self.sample.elapsed_s,
            "parameters": dict(self.parameters),
            "expected_range": {"min_amps": self.expected_range.min_amps,
                               "max_amps": self.expected_range.max_amps},
            "statistics": self.statistics.to_dict(),
            "out_of_range_count": len(self.out_of_range),
            "readings": [r.to_dict() for r in self.sample.readings],
        }
        if self.simulation is not None:
            record["simulation"] = dict(self.simulation)
        return record
