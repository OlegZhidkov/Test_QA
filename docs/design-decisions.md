# Design decisions

## Libraries

Installed: `pyyaml` (reads `config/config.yaml`) and `pytest` (the tests). Everything else is the standard library (`socket`, `threading`, `statistics`, `json`, `pathlib`, `logging`). The starter `requirements.txt` listed numpy, scipy, matplotlib, seaborn and pandas; nothing here needs them (plots are not implemented), so they were removed to keep dependencies minimal.

## Fixes to the given code

| Where | Problem | Fix and reason |
| --- | --- | --- |
| `main.py` | Used ports 5001 to 5003 (README and config say 5000 to 5002), requests commented out, truncated commands (`MEASURE_GREENLEE`, `MEASURE_ENTES`, `MEASURE_CIRCUTOR`, without their `-get_...` flags or `-current`) that the emulators silently drop, `sleep(5)` instead of waiting for readiness | Rewritten: ports, commands and timeouts come from the config, it waits for the emulators' `ready` event, requests one reading per ammeter, returns an exit code. The spec asks that `main.py` returns data. |
| `Ammeters/base_ammeter.py` | Bound the name `localhost` (a name lookup) | Hardening: binds `127.0.0.1` explicitly, the same default as the client and the config, so both sides use one fixed address. |
| same | `conn.recv` raised `ConnectionResetError` when a client reset; one failure killed the emulator thread | Errors of one connection are caught and logged; the server keeps running. |
| same | A client that connected and sent nothing blocked the single-threaded server forever | A receive timeout per connection (`recv_timeout_s`). |
| same | Compared one `recv(1024)` to the command, so a command split over two TCP segments was rejected | Reads until the buffer equals the command; stops early if it can no longer match. A wrong command is still silently dropped (as before) and does not stall. |
| same | `while True` with no way to stop; the port stayed busy on restart | `stop()` method and `ready` event, `SO_REUSEADDR` (`SO_EXCLUSIVEADDRUSE` on Windows), a bind error is reported instead of hanging. |
| same | An exception in `measure_current()` ended the server | Caught around that one call only (the single broad catch in the code), logged, the reply is dropped. |
| `Ammeters/client.py` | Printed instead of returning, no timeout, no error handling, `localhost` | Returns the reading as a float; typed errors (`AmmeterConnectionError`, `AmmeterTimeoutError`, `EmptyResponseError`, `NonNumericResponseError`), each naming host and port; a timeout; half-closes after sending so the emulator knows the command is complete; rejects `nan` and `inf`. The old single `recv(1024)` could truncate a reply, so it now reads until the peer closes. |
| `Ammeters/Greenlee_Ammeter.py` | The emulator prints `"Ω"` (the ENTES and CIRCUTOR files print ASCII only), which raises `UnicodeEncodeError` on a cp1252 stdout (Windows) and killed the reply | The device file is untouched; the server survives the error (above) and `start_emulators` sets `errors="replace"` on stdout and stderr, so every entry point (`main.py`, the tests, a by-hand script) is covered. |
| `Ammeters/base_ammeter.py` (logging) | `print("... is running ...")` and `print("Connected by ...")` | Now logging calls, which keeps the output readable. |
| same (port 0) | Needed a fixed port | Port 0 is supported and the real port is read back with `getsockname`, so tests use free ports and never clash. |
| `config/config.yaml` (visualization) | Had an `analysis.visualization` block | Removed: nothing reads it, the strict loader rejects unknown keys, and visualization is not part of this version. |
| `src/utils/logger.py` | `TestLogger` created a log path but never added a handler, so nothing was written | Adds a file handler and a stderr handler, creates the folder, is named per run (run ID) so parallel runs do not close each other's handlers, can be closed to release the file and drop the logger; a folder that cannot be created raises `ResultsWriteError`. |
| `src/utils/config.py` | Returned the raw YAML without any validation and opened the file without an encoding | Replaced by a validating loader returning typed frozen objects; every error names its dotted key. |
| `src/testing/test_framework.py` | `-> Dict` annotation without importing `Dict` (`NameError` when the module is imported on Python 3.11 to 3.13; not raised on 3.14 because annotations are evaluated lazily), an empty `run_test`, a config path relative to the working directory | Implemented (`AmmeterTestFramework`). |
| `config/config.yaml` | All values empty or commented out; the commented CIRCUTOR command lacked `-current` | Filled in: sampling, three ammeters with correct ports and commands (CIRCUTOR with `-current`), expected ranges. |
| `README.md` | Said `main.py` was in `Ammeters/`, the CIRCUTOR command lacked `-current`, named `run_test.py`, described `AmmeterTester.py` as the test class | Corrected and extended with usage. |
| `src/__init__.py`, `src/testing/__init__.py`, `src/utils/__init__.py` | The starter had no `__init__.py` files, while `test_framework.py` used a relative import | Package markers added so the imports work. |
| `requirements.txt` | Unneeded heavy libraries | See above. |
| `examples/run_tests.py` | Starter example that calls `run_test()` with no argument and cannot work | Left unchanged on purpose; the README says why it fails (`python3 examples/run_tests.py` gives `ModuleNotFoundError: No module named 'src'` because the script's folder, not the project root, is on the import path; `python3 -m examples.run_tests` gives a `TypeError` because `run_test()` gets no ammeter name) and points to `AmmeterTestFramework.run_test(name)`. |

The measurement logic in the three emulator classes and `src/utils/Utils.py` is unchanged.

## Key decisions

- **Timing.** Readings are scheduled at absolute targets `t0 + i * interval` on a monotonic clock, so timing errors do not accumulate and the count is always honored. A reply that arrives later than its interval delays the following readings, which are then taken back-to-back, and a device slower than the interval makes the run longer than configured (the actual offsets are in `run.json`). Timestamps are UTC and derived from the monotonic offsets, so they never go backwards.
- **Errors as data.** A failed reading becomes an error reading (message kept, not counted in the statistics) instead of aborting the run; the report and the JSON show the error count. Config errors name the dotted key.
- **Archive.** One atomic `run.json` per run (written to a temporary file, then renamed), only JSON types, no absolute paths. Run ID: `<UTC time>_<ammeter>_<6 hex>`; the run folder is reserved atomically (`mkdir` without `exist_ok`, retried with a fresh ID on a clash) before sampling, so the ID is unique by construction and a clash cannot lose a run. IDs are validated on every load so an ID cannot point outside the results folder.
- **Config-driven.** Ports, commands, hosts, ranges, sampling and metrics all come from the YAML; a new ammeter is a config entry plus an emulator class. The tests start the emulators on port 0 (free ports) so they never clash.
- **Statistics.** Mean, median, sample standard deviation, min, max. `cv_percent` (stdev / |mean| * 100) is a bonus metric for the spec's "performance consistency evaluation". With one reading stdev and `cv_percent` are undefined (`None`, shown as `n/a`); the same holds for a metric that overflows or is not finite (a device replying `1e308`; `1e308`, `-1e308`, `1.0` give an infinite `cv_percent`), while the other metrics are still computed. A metric that overflows or is not finite is undefined, so `run.json` never contains `Infinity` or `NaN` (`save_run` writes with `allow_nan=False` and reports a violation as a write error).

## Known limitations

- A port also held by another process: an exact conflict raises `EmulatorStartError` naming the port, but some systems let a wildcard listener share the port or take the traffic. Change the port in the config if readings look wrong.
- Bytes sent after a complete command in a later segment are not detected; such a command is served.
- One TCP connection per reading.
- Results are written relative to the working directory.
- Visualization, error simulation and cross-ammeter accuracy ranking are not implemented.
