# Sample results

Output of one real run on a clean `results/` folder, with the shipped `config/config.yaml`.

- `pytest_output.txt`: `python3 -m pytest -v`, including the "Ammeter runs" section at the end, which holds one report block per recorded run. The `rootdir` line and the interpreter path were removed so that no local path appears.
- `main_output.txt`: `python3 main.py`, one reading per configured ammeter (the lines with voltages, fields and `Current:` come from the emulators themselves).
- `<run_id>/run.json`: the six archived runs shown in `pytest_output.txt`: one run with the configured plan and one short run (2 readings) per ammeter. The folder names are exactly the run IDs in the report blocks, so each file can be opened with:

```python
from pathlib import Path
from src.utils.results import list_runs, load_run

folder = Path("docs/sample_results")
print([run["run_id"] for run in list_runs(folder)])
record = load_run("<run_id>", folder)
```

The port in each `Target:` line differs from the config because the suite starts the emulators on free ports (port 0) to avoid clashes.
