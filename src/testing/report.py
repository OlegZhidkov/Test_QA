"""Format one run as a text block."""
from collections.abc import Sequence

from src.testing.models import RunResult


def format_run_report(result: RunResult, metrics: Sequence[str]) -> str:
    """One block: ammeter and run ID, parameters, statistics, readings and archive path."""
    p = result.parameters
    stats = result.statistics.to_dict()
    expected = result.expected_range
    lines = [
        f"Ammeter: {result.ammeter}   Run ID: {result.run_id}",
        f"Parameters: count={p['count']} duration={p['duration_s']:.6g} s "
        f"frequency={p['frequency_hz']:.6g} Hz interval={p['interval_s']:.6g} s "
        f"request_timeout={p['request_timeout_s']:.6g} s",
        f"Target: {p['host']}:{p['port']} command={p['command']!r}",
        "Statistics:",
    ]
    lines += [f"  {metric}: {_format_value(stats[metric])}" for metric in metrics]
    lines += [
        f"Readings: valid={result.statistics.valid_count} errors={result.statistics.error_count} "
        f"out_of_range={len(result.out_of_range)} "
        f"(expected {expected.min_amps:.6g} to {expected.max_amps:.6g} A)",
        f"Archive: {result.archive_path if result.archive_path else 'not archived'}",
    ]
    return "\n".join(lines)


def _format_value(value: float | None) -> str:
    """Six significant digits, or n/a for None."""
    return "n/a" if value is None else f"{value:.6g}"
