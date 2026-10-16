"""Statistics over readings and the expected-range check."""
import statistics
from collections.abc import Sequence

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
    mean = statistics.fmean(values)
    stdev = statistics.stdev(values) if valid > 1 else None
    cv = stdev / abs(mean) * 100 if stdev is not None and mean != 0 else None
    return Statistics(**counts, mean=mean, median=statistics.median(values), stdev=stdev,
                      min=min(values), max=max(values), cv_percent=cv)


def out_of_range(readings: Sequence[Reading], expected: ExpectedRange) -> list[Reading]:
    """The valid readings outside the expected range; error readings are ignored."""
    return [r for r in readings if r.ok and not expected.contains(r.value_amps)]
