# Design decisions

## Libraries

Installed: `pyyaml` (reads `config/config.yaml`) and `pytest` (the tests). Everything else is the standard library (`socket`, `threading`, `statistics`, `json`, `pathlib`, `logging`). The starter `requirements.txt` listed numpy, scipy, matplotlib, seaborn and pandas; nothing here needs them (plots are not implemented), so they were removed to keep dependencies minimal.

## Fixes to the given code

| Where | Problem | Fix and reason |
| --- | --- | --- |
| `main.py` | Used ports 5001 to 5003 (README and config say 5000 to 5002), commands without `-current`, requests commented out, `sleep(5)` instead of waiting for readiness | Rewritten: ports, commands and timeouts come from the config, it waits for the emulators' `ready` event, requests one reading per ammeter, returns an exit code. The spec asks that `main.py` returns data. |
| `Ammeters/base_ammeter.py` | Bound `localhost` (may resolve to IPv6 or another address than the client) | Binds `127.0.0.1` explicitly, and the client defaults to it, so both sides always meet. |
| same | `conn.recv` raised `ConnectionResetError` when a client reset; one failure killed the emulator thread | Errors of one connection are caught and logged; the server keeps running. |
| same | A client that connected and sent nothing blocked the single-threaded server forever | A receive timeout per connection (`recv_timeout_s`). |
| same | Compared one `recv(1024)` to the command, so a command split over two TCP segments was rejected | Reads until the buffer equals the command; stops early if it can no longer match. A wrong command is still silently dropped (as before) and does not stall. |
| same | `while True` with no way to stop; the port stayed busy on restart | `stop()` method and `ready` event, `SO_REUSEADDR` (`SO_EXCLUSIVEADDRUSE` on Windows), a bind error is reported instead of hanging. |
| same | An exception in `measure_current()` ended the server | Caught around that one call only (the single broad catch in the code), logged, the reply is dropped. |
| `Ammeters/client.py` | Printed instead of returning, no timeout, no error handling, `localhost` | Returns the reading as a float; typed errors (`AmmeterConnectionError`, `AmmeterTimeoutError`, `EmptyResponseError`, `NonNumericResponseError`), each naming host and port; a timeout; half-closes after sending so the emulator knows the command is complete; rejects `nan` and `inf`. |
| `Ammeters/Greenlee_Ammeter.py` and the other two | The emulator prints `"Ω"`, which raises `UnicodeEncodeError` on a cp1252 stdout (Windows) and killed the reply | The device files are untouched; the server survives the error (above) and `main.py` sets `errors="replace"` on stdout. |
| `src/utils/logger.py` | `TestLogger` created a log path but never added a handler, so nothing was written | Adds a file handler and a stderr handler, creates the folder, can be closed to release the file; a folder that cannot be created raises `ResultsWriteError`. |
| `src/utils/config.py` | Returned the raw YAML; `Dict` was never imported (`NameError` on Python 3.11 to 3.13, hidden by lazy annotations on 3.14) | Replaced by a validating loader returning typed frozen objects. |
| `src/testing/test_framework.py` | Same `Dict` import bug, an empty `run_test` | Implemented (`AmmeterTestFramework`). |
| `config/config.yaml` | All values empty or commented out | Filled in: sampling, three ammeters with correct ports and commands, expected ranges. |
| `README.md` | Said `main.py` was in `Ammeters/`, the CIRCUTOR command lacked `-current`, named `run_test.py`, described `AmmeterTester.py` as the test class | Corrected and extended with usage. |
| `requirements.txt` | Unneeded heavy libraries | See above. |
| `examples/run_tests.py` | Starter example that calls `run_test()` with no argument and cannot work | Left unchanged on purpose and marked "don't use it" in the README. |

The measurement logic in the three emulator classes and `src/utils/Utils.py` is unchanged.

## Key decisions

- **Timing.** Readings are scheduled at absolute targets `t0 + i * interval` on a monotonic clock, so a slow reply does not shift later readings, and the count is always honored. Timestamps are UTC and derived from the monotonic offsets, so they never go backwards.
- **Errors as data.** A failed reading becomes an error reading (message kept, not counted in the statistics) instead of aborting the run; the report and the JSON show the error count. Config errors name the dotted key.
- **Archive.** One atomic `run.json` per run (written to a temporary file, then renamed), only JSON types, no absolute paths. Run ID: `<UTC time>_<ammeter>_<6 hex>`, validated on every load so an ID cannot point outside the results folder.
- **Config-driven.** Ports, commands, hosts, ranges, sampling and metrics all come from the YAML; a new ammeter is a config entry plus an emulator class. The tests start the emulators on port 0 (free ports) so they never clash.
- **Statistics.** Mean, median, sample standard deviation, min, max. `cv_percent` (stdev / |mean| * 100) is a bonus metric for the spec's "performance consistency evaluation". With one reading stdev and `cv_percent` are undefined (`None`, shown as `n/a`).

## Known limitations

- A port also held by another process: an exact conflict raises `EmulatorStartError` naming the port, but some systems let a wildcard listener share the port or take the traffic. Change the port in the config if readings look wrong.
- Bytes sent after a complete command in a later segment are not detected; such a command is served.
- One TCP connection per reading.
- Results are written relative to the working directory.
- Visualization, error simulation and cross-ammeter accuracy ranking are not implemented.
