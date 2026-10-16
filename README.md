# Ammeter Emulators

This project provides emulators for different types of ammeters: Greenlee, ENTES, and CIRCUTOR. Each ammeter emulator runs on a separate thread and can respond to current measurement requests.

## Project Structure

- `main.py`: Main script: starts the emulators from `config/config.yaml`, reads each ammeter once and prints the readings.
- `Ammeters/`
  - `Circutor_Ammeter.py`: Emulator for the CIRCUTOR ammeter.
  - `Entes_Ammeter.py`: Emulator for the ENTES ammeter.
  - `Greenlee_Ammeter.py`: Emulator for the Greenlee ammeter.
  - `base_ammeter.py`: Base class for all ammeter emulators.
  - `client.py`: Client to request current measurements from the ammeter emulators (typed errors, explicit timeout).
- `config/`
  - `config.yaml`: Configuration file: sampling, ammeters (port, command, expected range), metrics and results folder.
- `examples/`
  - `run_tests.py`: starter example, unfinished and not working (it calls `run_test()` without an ammeter name). **Don't use it**; it is kept unchanged.
- `src/`
  - `testing/`
    - `AmmeterTester.py`: Unified API for one ammeter: `measure()` for one reading, `sample()` for a timed series.
    - `analysis.py`: Statistics and the expected-range check.
    - `test_framework.py`: `AmmeterTestFramework`: sample, analyze, archive and report one run.
    - `report.py`: Text report of a run.
    - `models.py`: Readings, samples, statistics and run results.
    - `emulators.py`: Starts and stops the configured emulators in threads.
  - `utils/`
    - `config.py`: Loads and validates `config/config.yaml`.
    - `errors.py`: The framework's exception types.
    - `results.py`: Result archive: save, load, list and compare runs.
    - `logger.py`: Logging setup (one log file per run).
    - `Utils.py`: Utility functions, including `generate_random_float`.
- `tests/`: The pytest suite for the ammeters, the client and the emulators.
- `docs/`: `design-decisions.md` (fixes to the given code and design choices) and `sample_results/` (output of a real run).

## Usage

Requires Python 3.11 or newer.

### Install

```sh
python3 -m pip install -r requirements.txt
```

Libraries installed: `pyyaml` (reads the config) and `pytest` (runs the tests). Nothing else is needed.

### Run `main.py`

```sh
python3 main.py
```

It starts the three emulators on the ports from `config/config.yaml`, requests one reading from each and stops them. Sample output (the voltage, field and `Current:` lines are printed by the emulators themselves):

```
Greenlee Ammeter - Voltage: 7.023134765386599V, Resistance: 45.78724696508945Ω, Current: 0.15338626431812766A
greenlee: 0.15338626431812766 A
ENTES Ammeter - Magnetic Field: 0.012370550600195186T, Calibration Factor: 1606.5640118915646, Current: 19.87408140155718A
entes: 19.87408140155718 A
CIRCUTOR Ammeter - Voltages: [0.5441, 0.5108, ...], Time Step: 0.004749544544392841s
Current: 0.025116296823162285A
circutor: 0.025116296823162285 A
```

Exit codes: `0` all readings printed; `1` a reading failed or an emulator could not start (for example the port is in use); `2` the config is invalid (the message names the key). The full output of a run is in `docs/sample_results/main_output.txt`.

### Run the tests

```sh
python3 -m pytest
```

The suite uses `config/config.yaml`. It starts the emulators itself on free ports, so it does not clash with `main.py` or with anything on ports 5000 to 5002. Every ammeter in the config gets the same checks: it answers its command with a number, ignores a wrong or truncated command, stays in its expected range, takes the configured number of readings at the configured frequency over the configured duration, produces correct statistics, and is archived and reported. A run takes about 10 seconds. The output ends with an "Ammeter runs" section that prints the report block of every run (ammeter, run ID, parameters, statistics). A real output is in `docs/sample_results/pytest_output.txt`.

### Where results go

Each test run is saved as `results/<run_id>/run.json` (the folder comes from `result_management.results_dir`; it is relative to the folder you start from, and is not tracked by git). A run ID looks like `20261016T183722Z_greenlee_5cd0c2`: UTC start time, ammeter name and 6 random hex digits, so it is unique. The JSON holds the run ID, ammeter, start and end time, parameters (count, duration, frequency, interval, timeout, host, port, command), the expected range, the statistics, the number of out-of-range readings and every reading with its timestamp and value (or error). A log file per run goes to `results/logs/`. Real examples are in `docs/sample_results/`.

List, load and compare runs from Python:

```python
from pathlib import Path
from src.utils.results import compare_runs, list_runs, load_run

results = Path("results")
for run in list_runs(results):          # summaries, sorted by run ID (so by time)
    print(run["run_id"], run["ammeter"])
record = load_run("<run_id>", results)  # the full record as a dict
print(compare_runs("<run_id_a>", "<run_id_b>", results))  # statistics side by side with deltas
```

To run the framework by hand:

```python
from src.testing.test_framework import AmmeterTestFramework

framework = AmmeterTestFramework()          # reads config/config.yaml
result = framework.run_test("greenlee")     # sample, analyze, archive; needs the emulator running
```

### Config keys (`config/config.yaml`)

Unknown keys, wrong types and inconsistent values are rejected with a message that names the key.

| Key | Meaning | Default |
| --- | --- | --- |
| `testing.sampling.measurements_count` | Number of readings (integer, at least 1) | none |
| `testing.sampling.total_duration_seconds` | Total duration of a run in seconds | none |
| `testing.sampling.sampling_frequency_hz` | Readings per second | none |
| `testing.request_timeout_seconds` | Timeout of one request | `2.0` |
| `testing.emulator_start_timeout_seconds` | How long to wait for an emulator to start | `5.0` |
| `ammeters.<name>` | One entry per ammeter; the name is lower case letters, digits or `_` | required, at least one |
| `ammeters.<name>.port` | TCP port (1 to 65535, unique per host) | required |
| `ammeters.<name>.command` | Command the ammeter understands | required |
| `ammeters.<name>.host` | Address of the ammeter | `127.0.0.1` |
| `ammeters.<name>.emulator` | `module:Class` of the emulator to start; leave out for a real device | none |
| `ammeters.<name>.expected_range.min_amps` / `max_amps` | Inclusive range a valid reading must be inside | required |
| `analysis.statistical_metrics` | Metrics in the report: `mean`, `median`, `stdev`, `min`, `max`, `cv_percent` | all six |
| `result_management.results_dir` | Folder for the archived runs | `results` |

Give at least two of the three sampling keys; the third is computed (`count = duration * frequency`). If all three are given they must agree. The shipped config asks for 10 readings over 2 seconds, which is 5 readings per second.

### Add an ammeter

1. Write the emulator class (a subclass of `AmmeterEmulatorBase` with `get_current_command` and `measure_current()`), as the files in `Ammeters/` do.
2. Add an entry under `ammeters:` in `config/config.yaml` with its port, command, `emulator: "module:Class"` and `expected_range`.

No other code changes are needed: the tests and the runs pick up the new entry. For a real device, leave out `emulator` and set `host` and `port`.

# Ammeter Emulators

## Greenlee Ammeter

- **Port**: 5000
- **Command**: `MEASURE_GREENLEE -get_measurement`
- **Measurement Logic**: Calculates current using voltage (1V - 10V) and (0.1Ω - 100Ω).
- **Measurement method** : Ohm's Law: I = V / R

## ENTES Ammeter

- **Port**: 5001
- **Command**: `MEASURE_ENTES -get_data`
- **Measurement Logic**: Calculates current using magnetic field strength (0.01T - 0.1T) and calibration factor (500 - 2000).
- **Measurement method** : Hall Effect: I = B * K

## CIRCUTOR Ammeter

- **Port**: 5002
- **Command**: `MEASURE_CIRCUTOR -get_measurement -current`
- **Measurement Logic**: Calculates current using voltage values (0.1V - 1.0V) over a number of samples and a random time step (0.001s - 0.01s).
- **Measurement method** : Rogowski Coil Integration: I = ∫V dt

To start the ammeter emulators and request current measurements, run the `main.py` script from the project folder:
```sh
python3 main.py
```
