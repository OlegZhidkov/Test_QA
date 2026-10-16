"""Load, default and validate the YAML config into typed, frozen objects."""
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from src.utils.errors import ConfigError

DEFAULT_CONFIG_PATH = Path("config/config.yaml")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_REQUEST_TIMEOUT_S = 2.0
DEFAULT_START_TIMEOUT_S = 5.0
DEFAULT_RESULTS_DIR = "results"
ALL_METRICS = ("mean", "median", "stdev", "min", "max", "cv_percent")
NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
RANGE_REL_TOL = 1e-9
SAMPLING_REL_TOL = 1e-6
SAMPLING_KEYS = ("measurements_count", "total_duration_seconds", "sampling_frequency_hz")


@dataclass(frozen=True)
class SamplingPlan:
    """How many readings to take, over how long, at what rate."""

    count: int
    duration_s: float
    frequency_hz: float

    @property
    def interval_s(self) -> float:
        """Seconds between the start of two readings."""
        return 1.0 / self.frequency_hz


@dataclass(frozen=True)
class ExpectedRange:
    """Inclusive range of plausible readings, in amps."""

    min_amps: float
    max_amps: float

    def contains(self, value: float) -> bool:
        """True if value is inside the range, bounds included (relative tolerance 1e-9)."""
        above = value >= self.min_amps or math.isclose(value, self.min_amps, rel_tol=RANGE_REL_TOL)
        below = value <= self.max_amps or math.isclose(value, self.max_amps, rel_tol=RANGE_REL_TOL)
        return above and below


@dataclass(frozen=True, kw_only=True)
class AmmeterSettings:
    """Everything needed to talk to one ammeter."""

    name: str
    host: str = DEFAULT_HOST
    port: int
    command: bytes
    emulator: str | None
    expected_range: ExpectedRange


@dataclass(frozen=True)
class FrameworkConfig:
    """The validated configuration."""

    sampling: SamplingPlan
    request_timeout_s: float
    emulator_start_timeout_s: float
    ammeters: Mapping[str, AmmeterSettings]
    metrics: tuple[str, ...]
    results_dir: Path
    source: str

    def with_ports(self, ports: Mapping[str, int]) -> "FrameworkConfig":
        """Return a copy with the given ammeters moved to other ports."""
        unknown = sorted(set(ports) - set(self.ammeters))
        if unknown:
            raise ConfigError(f"with_ports: unknown ammeters {unknown}; "
                              f"known: {sorted(self.ammeters)}")
        ammeters = {name: replace(settings, port=ports.get(name, settings.port))
                    for name, settings in self.ammeters.items()}
        return replace(self, ammeters=ammeters)


def load_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> FrameworkConfig:
    """Read and validate a YAML config file; every problem is a ConfigError."""
    path = Path(config_path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    return parse_config(data, str(path))


def parse_config(data: object, source: str) -> FrameworkConfig:
    """Validate already-parsed YAML data; messages start with the dotted key."""
    try:
        return _parse(data, source)
    except ConfigError as exc:
        raise ConfigError(f"{exc} ({source})") from exc


def resolve_sampling(count: object, duration_s: object, frequency_hz: object,
                     key: str) -> SamplingPlan:
    """Fill in the missing one of count, duration and frequency, or check all three."""
    keys = ", ".join(f"{key}.{k}" for k in SAMPLING_KEYS)
    given = [v is not None for v in (count, duration_s, frequency_hz)]
    if sum(given) < 2:
        raise ConfigError(f"{key}: give at least two of {keys}")
    n = None if count is None else _positive_int(count, f"{key}.{SAMPLING_KEYS[0]}")
    d = None if duration_s is None else _positive_number(duration_s, f"{key}.{SAMPLING_KEYS[1]}")
    f = None if frequency_hz is None else _positive_number(frequency_hz,
                                                           f"{key}.{SAMPLING_KEYS[2]}")
    if n is not None and d is not None and f is not None:
        if not math.isclose(n, d * f, rel_tol=SAMPLING_REL_TOL):
            raise ConfigError(f"{key}: {keys} are inconsistent: "
                              f"count {n} != duration {d} * frequency {f}")
        return SamplingPlan(n, d, f)
    if n is not None and d is not None:
        return SamplingPlan(n, d, n / d)
    if n is not None and f is not None:
        return SamplingPlan(n, n / f, f)
    product = d * f
    rounded = round(product)
    if rounded < 1 or not math.isclose(product, rounded, rel_tol=0, abs_tol=SAMPLING_REL_TOL):
        raise ConfigError(f"{key}: duration * frequency = {product} must be a whole number "
                          f"of at least 1 ({keys})")
    return SamplingPlan(rounded, d, f)


def _parse(data: object, source: str) -> FrameworkConfig:
    top = _require_mapping(data, "top level")
    _reject_unknown(top, {"testing", "ammeters", "analysis", "result_management"}, "")
    testing = _optional_mapping(top, "testing", "testing")
    _reject_unknown(testing, {"sampling", "request_timeout_seconds",
                              "emulator_start_timeout_seconds"}, "testing")
    sampling_data = _optional_mapping(testing, "sampling", "testing.sampling")
    _reject_unknown(sampling_data, set(SAMPLING_KEYS), "testing.sampling")
    sampling = resolve_sampling(*(sampling_data.get(k) for k in SAMPLING_KEYS), "testing.sampling")
    request_timeout = _positive_number(
        testing.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_S),
        "testing.request_timeout_seconds")
    start_timeout = _positive_number(
        testing.get("emulator_start_timeout_seconds", DEFAULT_START_TIMEOUT_S),
        "testing.emulator_start_timeout_seconds")

    if "ammeters" not in top:
        raise ConfigError("ammeters: required section is missing")
    ammeters_data = _require_mapping(top["ammeters"], "ammeters")
    if not ammeters_data:
        raise ConfigError("ammeters: define at least one ammeter")
    ammeters = {name: _ammeter(name, value) for name, value in ammeters_data.items()}
    _reject_shared_ports(ammeters)

    analysis = _optional_mapping(top, "analysis", "analysis")
    _reject_unknown(analysis, {"statistical_metrics"}, "analysis")
    results = _optional_mapping(top, "result_management", "result_management")
    _reject_unknown(results, {"results_dir"}, "result_management")
    results_dir = results.get("results_dir", DEFAULT_RESULTS_DIR)
    if not isinstance(results_dir, str) or not results_dir.strip():
        raise ConfigError("result_management.results_dir: must be a non-empty string, "
                          f"got {results_dir!r}")
    return FrameworkConfig(
        sampling=sampling,
        request_timeout_s=request_timeout,
        emulator_start_timeout_s=start_timeout,
        ammeters=ammeters,
        metrics=_metrics(analysis.get("statistical_metrics", list(ALL_METRICS))),
        results_dir=Path(results_dir),
        source=source,
    )


def _ammeter(name: object, value: object) -> AmmeterSettings:
    """Validate one ammeter entry."""
    name = _name(name)
    key = f"ammeters.{name}"
    entry = _require_mapping(value, key)
    _reject_unknown(entry, {"port", "command", "emulator", "host", "expected_range"}, key)
    for required in ("port", "command", "expected_range"):
        if required not in entry:
            raise ConfigError(f"{key}.{required}: required key is missing")
    emulator = entry.get("emulator")
    if emulator is not None:
        emulator = _text(emulator, f"{key}.emulator")
    return AmmeterSettings(
        name=name,
        host=_text(entry.get("host", DEFAULT_HOST), f"{key}.host"),
        port=_port(entry["port"], f"{key}.port"),
        command=_text(entry["command"], f"{key}.command").encode("utf-8"),
        emulator=emulator,
        expected_range=_expected_range(entry["expected_range"], f"{key}.expected_range"),
    )


def _expected_range(value: object, key: str) -> ExpectedRange:
    """Validate an expected_range mapping."""
    entry = _require_mapping(value, key)
    _reject_unknown(entry, {"min_amps", "max_amps"}, key)
    for required in ("min_amps", "max_amps"):
        if required not in entry:
            raise ConfigError(f"{key}.{required}: required key is missing")
    low = _number(entry["min_amps"], f"{key}.min_amps")
    high = _number(entry["max_amps"], f"{key}.max_amps")
    if low >= high:
        raise ConfigError(f"{key}: min_amps ({low}) must be below max_amps ({high})")
    return ExpectedRange(low, high)


def _metrics(value: object) -> tuple[str, ...]:
    """Validate the list of statistical metrics."""
    key = "analysis.statistical_metrics"
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{key}: must be a non-empty list, got {value!r}")
    unknown = [m for m in value if m not in ALL_METRICS]
    if unknown:
        raise ConfigError(f"{key}: unknown metrics {unknown}; allowed: {list(ALL_METRICS)}")
    return tuple(value)


def _reject_shared_ports(ammeters: Mapping[str, AmmeterSettings]) -> None:
    """Two ammeters must not use the same host and port."""
    seen: dict[tuple[str, int], str] = {}
    for name, settings in ammeters.items():
        address = (settings.host, settings.port)
        if address in seen:
            raise ConfigError(f"ammeters.{name}.port: {settings.port} is already used by "
                              f"ammeters.{seen[address]}.port")
        seen[address] = name


def _require_mapping(value: object, key: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key}: must be a mapping, got {value!r}")
    return value


def _optional_mapping(parent: Mapping, field: str, key: str) -> Mapping:
    """A section that may be absent or empty."""
    value = parent.get(field)
    return {} if value is None else _require_mapping(value, key)


def _reject_unknown(mapping: Mapping, allowed: set[str], key: str) -> None:
    for field in mapping:
        if field not in allowed:
            dotted = f"{key}.{field}" if key else str(field)
            raise ConfigError(f"{dotted}: unknown key; allowed: {sorted(allowed)}")


def _name(value: object) -> str:
    if not isinstance(value, str) or not NAME_PATTERN.match(value):
        raise ConfigError(f"ammeters.{value}: name must match {NAME_PATTERN.pattern}")
    return value


def _text(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key}: must be a non-empty string, got {value!r}")
    return value


def _number(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{key}: must be a finite number, got {value!r}")
    return float(value)


def _positive_number(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{key}: must be a positive number, got {value!r}")
    return float(value)


def _positive_int(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{key}: must be a positive integer, got {value!r}")
    return value


def _port(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ConfigError(f"{key}: must be an integer from 1 to 65535, got {value!r}")
    return value
