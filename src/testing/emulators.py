"""Start and stop the configured emulators in daemon threads."""
import logging
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module

from Ammeters.base_ammeter import AmmeterEmulatorBase
from src.utils.config import AmmeterSettings, FrameworkConfig
from src.utils.errors import ConfigError, EmulatorStartError

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 0.05
JOIN_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class RunningEmulator:
    """A started emulator and the thread serving it."""

    name: str
    emulator: AmmeterEmulatorBase
    thread: threading.Thread

    @property
    def port(self) -> int:
        """The port the emulator is really bound to."""
        return self.emulator.port


def load_emulator_class(settings: AmmeterSettings) -> type[AmmeterEmulatorBase]:
    """Import the `module:Class` named in the settings and check it is an emulator."""
    key = f"ammeters.{settings.name}.emulator"
    module_name, separator, class_name = (settings.emulator or "").partition(":")
    if not separator or not module_name or not class_name:
        raise ConfigError(f"{key}: expected 'module:Class', got {settings.emulator!r}")
    try:
        cls = getattr(import_module(module_name), class_name)
    except ImportError as exc:
        raise ConfigError(f"{key}: cannot import module {module_name!r}: {exc}") from exc
    except AttributeError as exc:
        raise ConfigError(f"{key}: module {module_name!r} has no {class_name!r}") from exc
    if not (isinstance(cls, type) and issubclass(cls, AmmeterEmulatorBase)):
        raise ConfigError(f"{key}: {settings.emulator!r} is not an AmmeterEmulatorBase subclass")
    return cls


def start_emulators(config: FrameworkConfig,
                    port_overrides: Mapping[str, int] | None = None) -> dict[str, RunningEmulator]:
    """Start every ammeter that has an `emulator` entry and wait until each is ready.

    Raises EmulatorStartError (after stopping the ones already started) if one dies or
    does not become ready in time.
    """
    _make_streams_tolerant()
    overrides = port_overrides or {}
    classes = {name: load_emulator_class(settings)
               for name, settings in config.ammeters.items() if settings.emulator}
    running: dict[str, RunningEmulator] = {}
    for name, cls in classes.items():
        emulator = cls(overrides.get(name, config.ammeters[name].port))
        thread = threading.Thread(target=_serve, args=(emulator,), name=f"emulator-{name}",
                                  daemon=True)
        entry = RunningEmulator(name, emulator, thread)
        thread.start()
        running[name] = entry
        try:
            _wait_until_ready(entry, config.emulator_start_timeout_s)
        except EmulatorStartError:
            stop_emulators(running)
            raise
    return running


def stop_emulators(running: Mapping[str, RunningEmulator]) -> None:
    """Stop every emulator and wait for its thread, so the ports are released."""
    for entry in running.values():
        entry.emulator.stop()
    for entry in running.values():
        entry.thread.join(JOIN_TIMEOUT_S)
        if entry.thread.is_alive():
            logger.warning("emulator %s did not stop within %s s", entry.name, JOIN_TIMEOUT_S)


def _make_streams_tolerant() -> None:
    """Make stdout and stderr replace unencodable characters instead of raising.

    The Greenlee emulator prints an omega; on a console that cannot encode it
    (cp1252) the print would raise and the reply would be lost.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def _serve(emulator: AmmeterEmulatorBase) -> None:
    """Thread target: run the server and keep a bind error instead of crashing the thread."""
    try:
        emulator.start_server()
    except OSError as exc:
        emulator.start_error = exc


def _wait_until_ready(entry: RunningEmulator, timeout_s: float) -> None:
    """Wait for `ready`; fail fast if the thread dies, or on timeout."""
    deadline = time.monotonic() + timeout_s
    while not entry.emulator.ready.wait(POLL_INTERVAL_S):
        if not entry.thread.is_alive():
            raise EmulatorStartError(_start_failure(entry, "stopped before it was ready"))
        if time.monotonic() >= deadline:
            raise EmulatorStartError(_start_failure(entry, f"not ready after {timeout_s} s"))


def _start_failure(entry: RunningEmulator, reason: str) -> str:
    """Message for a failed emulator start, with the bind error when there is one."""
    message = f"emulator {entry.name!r} on port {entry.port}: {reason}"
    if entry.emulator.start_error is not None:
        message += f": {entry.emulator.start_error}"
    return message
