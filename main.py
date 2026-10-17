"""Command line entry point: start the configured emulators and print one reading per ammeter."""
import sys
from pathlib import Path

from Ammeters.client import request_current_from_ammeter
from src.testing.emulators import start_emulators, stop_emulators
from src.utils.config import DEFAULT_CONFIG_PATH, load_config
from src.utils.errors import AmmeterFrameworkError, ConfigError, EmulatorStartError


def main(config_path: Path = DEFAULT_CONFIG_PATH) -> int:
    """Start the configured emulators, print one reading per ammeter and return an exit code.

    0 all readings printed, 1 a reading or an emulator failed, 2 invalid config.
    """
    try:
        config = load_config(config_path)
        running = start_emulators(config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    except EmulatorStartError as exc:
        print(exc, file=sys.stderr)
        return 1
    exit_code = 0
    try:
        for name, settings in config.ammeters.items():
            port = running[name].port if name in running else settings.port
            try:
                value = request_current_from_ammeter(
                    port, settings.command, settings.host, config.request_timeout_s)
            except AmmeterFrameworkError as exc:
                print(f"{name}: {exc}", file=sys.stderr)
                exit_code = 1
            else:
                print(f"{name}: {value} A")
    finally:
        stop_emulators(running)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
