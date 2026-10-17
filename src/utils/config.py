"""Load, default and validate the YAML config into typed, frozen objects."""
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from src.utils.errors import ConfigError

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_REQUEST_TIMEOUT_S = 2.0
DEFAULT_START_TIMEOUT_S = 5.0
DEFAULT_RESULTS_DIR = "results"
ALL_METRICS = ("mean", "median", "stdev", "min", "max", "cv_percent")
NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
RANGE_REL_TOL = 1e-9
SAMPLING_REL_TOL = 1e-6
SAMPLING_KEYS = ("measurements_count", "total_duration_seconds", "sampling_frequency_hz")
FAULT_TYPES = ("no_response", "stall", "garbage", "out_of_range")
SEED_MAX = 2**32 - 1
DEFAULT_SPIKE_FACTOR = 1000.0
SPIKE_FACTOR_MAX = 1e9
PROBABILITY_SUM_TOL = 1e-9


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
class ErrorSimulation:
    """Faults a managed emulator injects: a seed, per-request probabilities and parameters."""

    seed: int
    no_response: float = 0.0
    stall: float = 0.0
    garbage: float = 0.0
    out_of_range: float = 0.0
    stall_seconds: float | None = None
    spike_factor: float = DEFAULT_SPIKE_FACTOR

    def probabilities(self) -> dict[str, float]:
        """The four fault probabilities, in FAULT_TYPES order."""
        return {fault: getattr(self, fault) for fault in FAULT_TYPES}

    def as_record(self) -> dict:
        """All fields with JSON types only, for run.json."""
        return {"seed": self.seed, **self.probabilities(),
                "stall_seconds": self.stall_seconds, "spike_factor": self.spike_factor}


@dataclass(frozen=True, kw_only=True)
class AmmeterSettings:
    """Everything needed to talk to one ammeter."""

    name: str
    host: str = DEFAULT_HOST
    port: int
    command: bytes
    emulator: str | None
    expected_range: ExpectedRange
    simulate_errors: ErrorSimulation | None = None


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

    def settings_for(self, name: str) -> AmmeterSettings:
        """The settings of the named ammeter; an unknown name raises ConfigError."""
        if name not in self.ammeters:
            raise ConfigError(f"unknown ammeter {name!r}; known: {sorted(self.ammeters)}")
        return self.ammeters[name]

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
    """Validate the loaded YAML data and build the FrameworkConfig."""
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
    ammeters = _resolve_stalls(ammeters, sampling, request_timeout)
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
    _reject_unknown(entry, {"port", "command", "emulator", "host", "expected_range",
                              "simulate_errors"}, key)
    for required in ("port", "command", "expected_range"):
        if required not in entry:
            raise ConfigError(f"{key}.{required}: required key is missing")
    emulator = entry.get("emulator")
    if emulator is not None:
        emulator = _text(emulator, f"{key}.emulator")
    expected_range = _expected_range(entry["expected_range"], f"{key}.expected_range")
    simulation = entry.get("simulate_errors")
    if simulation is not None:
        simulation = _simulation(simulation, f"{key}.simulate_errors", emulator, expected_range)
    return AmmeterSettings(
        name=name,
        host=_text(entry.get("host", DEFAULT_HOST), f"{key}.host"),
        port=_port(entry["port"], f"{key}.port"),
        command=_text(entry["command"], f"{key}.command").encode("utf-8"),
        emulator=emulator,
        expected_range=expected_range,
        simulate_errors=simulation,
    )


def _simulation(value: object, key: str, emulator: str | None,
                expected: ExpectedRange) -> ErrorSimulation:
    """Validate one simulate_errors block."""
    entry = _require_mapping(value, key)
    _reject_unknown(entry, {"seed", *FAULT_TYPES, "stall_seconds", "spike_factor"}, key)
    if emulator is None:
        raise ConfigError(f"{key}: only a managed ammeter can be sabotaged; "
                          "set ammeters.<name>.emulator")
    seed = entry.get("seed")
    if seed is None:
        raise ConfigError(f"{key}.seed: required, an int in 0..{SEED_MAX}")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= SEED_MAX:
        raise ConfigError(f"{key}.seed: must be an int in 0..{SEED_MAX}, got {_short(seed)}")
    chances = {fault: _probability(entry.get(fault, 0.0), f"{key}.{fault}")
               for fault in FAULT_TYPES}
    if sum(chances.values()) > 1 + PROBABILITY_SUM_TOL:
        keys = ", ".join(f"{key}.{fault}" for fault in FAULT_TYPES)
        raise ConfigError(f"{keys}: probabilities must sum to at most 1, got {sum(chances.values())}")
    if not any(chance > 0 for chance in chances.values()):
        raise ConfigError(f"{key}: at least one of {list(FAULT_TYPES)} must be above 0")
    stall_seconds = entry.get("stall_seconds")
    if stall_seconds is not None:
        stall_seconds = _positive_number(stall_seconds, f"{key}.stall_seconds")
    spike = _as_float(entry.get("spike_factor", DEFAULT_SPIKE_FACTOR))
    if spike is None or not math.isfinite(spike) or not 1 < spike <= SPIKE_FACTOR_MAX:
        raise ConfigError(f"{key}.spike_factor: must be a number above 1 and at most "
                          f"{SPIKE_FACTOR_MAX:g}, got {_short(entry['spike_factor'])}")
    if chances["out_of_range"] > 0 and expected.min_amps > 0 \
            and spike * expected.min_amps <= expected.max_amps:
        raise ConfigError(f"{key}.spike_factor: {spike:g} * min_amps {expected.min_amps:g} "
                          f"must be above max_amps {expected.max_amps:g} "
                          "so every spike is out of range")
    return ErrorSimulation(seed=seed, **chances, stall_seconds=stall_seconds, spike_factor=spike)


def _probability(value: object, key: str) -> float:
    """Return a finite number from 0 to 1 (not a bool) or raise ConfigError naming `key`."""
    number = _as_float(value)
    if number is None or not math.isfinite(number) or not 0 <= number <= 1:
        raise ConfigError(f"{key}: must be a number from 0 to 1, got {_short(value)}")
    return number


def _resolve_stalls(ammeters: Mapping[str, AmmeterSettings], sampling: SamplingPlan,
                    request_timeout_s: float) -> dict[str, AmmeterSettings]:
    """Default or check stall_seconds: request timeout < stall_seconds < sampling interval."""
    interval = sampling.interval_s
    resolved: dict[str, AmmeterSettings] = {}
    for name, settings in ammeters.items():
        simulation = settings.simulate_errors
        if simulation is not None and simulation.stall > 0:
            key = f"ammeters.{name}.simulate_errors"
            if simulation.stall_seconds is None:
                if request_timeout_s >= interval:
                    raise ConfigError(
                        f"{key}.stall: needs testing.request_timeout_seconds "
                        f"({request_timeout_s:g}) below the sampling interval ({interval:g} s) "
                        "to default stall_seconds; set both so that "
                        "timeout < stall_seconds < interval")
                simulation = replace(simulation,
                                     stall_seconds=(request_timeout_s + interval) / 2)
            elif not request_timeout_s < simulation.stall_seconds < interval:
                raise ConfigError(
                    f"{key}.stall_seconds: must be above testing.request_timeout_seconds "
                    f"({request_timeout_s:g}) and below the sampling interval ({interval:g} s), "
                    f"got {simulation.stall_seconds:g}")
            settings = replace(settings, simulate_errors=simulation)
        resolved[name] = settings
    return resolved


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
    """Return `value` if it is a mapping, else raise ConfigError naming `key`."""
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key}: must be a mapping, got {value!r}")
    return value


def _optional_mapping(parent: Mapping, field: str, key: str) -> Mapping:
    """A section that may be absent or empty."""
    value = parent.get(field)
    return {} if value is None else _require_mapping(value, key)


def _reject_unknown(mapping: Mapping, allowed: set[str], key: str) -> None:
    """Raise ConfigError for any key of `mapping` that is not in `allowed`."""
    for field in mapping:
        if field not in allowed:
            dotted = f"{key}.{field}" if key else str(field)
            raise ConfigError(f"{dotted}: unknown key; allowed: {sorted(allowed)}")


def _name(value: object) -> str:
    """Return a valid ammeter name or raise ConfigError."""
    if not isinstance(value, str) or not NAME_PATTERN.match(value):
        raise ConfigError(f"ammeters.{value}: name must match {NAME_PATTERN.pattern}")
    return value


def _text(value: object, key: str) -> str:
    """Return a non-empty string or raise ConfigError naming `key`."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key}: must be a non-empty string, got {value!r}")
    return value


def _as_float(value: object) -> float | None:
    """Convert an int or float to float; None for anything else or an int too large."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value)
    except OverflowError:
        return None


def _number(value: object, key: str) -> float:
    """Return a finite number or raise ConfigError naming `key`."""
    number = _as_float(value)
    if number is None or not math.isfinite(number):
        raise ConfigError(f"{key}: must be a finite number, got {_short(value)}")
    return number


def _positive_number(value: object, key: str) -> float:
    """Return a finite number above zero or raise ConfigError naming `key`."""
    number = _as_float(value)
    if number is None or not math.isfinite(number) or number <= 0:
        raise ConfigError(f"{key}: must be a positive number, got {_short(value)}")
    return number


def _short(value: object) -> str:
    """repr(value), cut to 60 characters so a huge number stays readable."""
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _positive_int(value: object, key: str) -> int:
    """Return an integer above zero (not a bool) or raise ConfigError naming `key`."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{key}: must be a positive integer, got {value!r}")
    return value


def _port(value: object, key: str) -> int:
    """Return a TCP port from 1 to 65535 (not a bool) or raise ConfigError naming `key`."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ConfigError(f"{key}: must be an integer from 1 to 65535, got {value!r}")
    return value
