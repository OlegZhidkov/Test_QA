"""Statistics over readings and the expected-range check."""
import math
import statistics
from collections.abc import Callable, Sequence

from src.testing.models import Reading, Statistics
from src.utils.config import ExpectedRange


def compute_statistics(readings: Sequence[Reading]) -> Statistics:
    """Statistics over the valid readings; undefined metrics are None."""
    values = [r.value_amps for r in readings if r.ok]
    valid = len(values)
    counts = {"count": len(readings), "valid_count": valid, "error_count": len(readings) - valid}
    if not values:
        return Statistics(**counts, mean=None, median=None, stdev=None, min=None, max=None,
                          cv_percent=None)
    mean = _or_none(statistics.fmean, values)
    stdev = _or_none(statistics.stdev, values) if valid > 1 else None
    cv = stdev / abs(mean) * 100 if stdev is not None and mean else None
    return Statistics(**counts, mean=mean, median=_or_none(statistics.median, values),
                      stdev=stdev, min=min(values), max=max(values), cv_percent=cv)


def _or_none(metric: Callable[[list[float]], float], values: list[float]) -> float | None:
    """The metric over the values, or None when it overflows (for example 1e308 twice)."""
    try:
        result = metric(values)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def out_of_range(readings: Sequence[Reading], expected: ExpectedRange) -> list[Reading]:
    """The valid readings outside the expected range; error readings are ignored."""
    return [r for r in readings if r.ok and not expected.contains(r.value_amps)]
