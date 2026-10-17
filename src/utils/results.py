"""Archive runs as results/<run_id>/run.json: save, load, list and compare."""
import json
import logging
import os
import re
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.errors import (
    ResultsCorruptError,
    ResultsError,
    ResultsNotFoundError,
    ResultsWriteError,
)

logger = logging.getLogger(__name__)

RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z_[a-z0-9_]+_[0-9a-f]{6}$")
RUN_FILE = "run.json"
RESERVE_ATTEMPTS = 5
RECORD_KEYS = ("run_id", "ammeter", "started_at_utc", "finished_at_utc", "elapsed_s",
               "parameters", "expected_range", "statistics", "out_of_range_count", "readings")
CONTAINER_KEYS = {"statistics": dict, "parameters": dict, "readings": list}


def new_run_id(ammeter: str, now: datetime | None = None) -> str:
    """A unique run ID: UTC time, the ammeter name and 6 random hex digits."""
    now = now or datetime.now(UTC)
    return f"{now:%Y%m%dT%H%M%SZ}_{ammeter}_{secrets.token_hex(3)}"


def reserve_run(ammeter: str, results_dir: Path, attempts: int = RESERVE_ATTEMPTS) -> str:
    """Create the folder of a fresh run ID, retrying on a clash, and return the ID.

    Creating the folder is atomic, so a reserved ID can never be taken by another run.
    """
    last_error: OSError | None = None
    for _ in range(attempts):
        run_id = new_run_id(ammeter)
        try:
            (Path(results_dir) / run_id).mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            last_error = exc
            continue
        except OSError as exc:
            raise ResultsWriteError(f"cannot create run folder in {results_dir}: {exc}") from exc
        return run_id
    raise ResultsWriteError(
        f"no free run id for {ammeter!r} after {attempts} attempts: {last_error}")


def release_run(run_id: str, results_dir: Path) -> None:
    """Remove a reserved run folder that was never filled; a folder with content stays."""
    try:
        (Path(results_dir) / _check_run_id(run_id)).rmdir()
    except OSError as exc:
        logger.warning("could not release run folder %s: %s", run_id, exc)


def save_run(record: Mapping[str, Any], results_dir: Path) -> Path:
    """Write the record atomically to <results_dir>/<run_id>/run.json and return that path.

    The folder may be reserved with `reserve_run`; a run that already has a run.json
    is never overwritten.
    """
    run_id = _check_run_id(record.get("run_id"))
    folder = Path(results_dir) / run_id
    path = folder / RUN_FILE
    tmp = folder / f"{RUN_FILE}.tmp"
    created = not folder.exists()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ResultsWriteError(f"run {run_id} already exists at {path}; not overwriting")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except (OSError, TypeError, ValueError) as exc:
        _discard(folder, tmp, remove_folder=created)
        raise ResultsWriteError(f"cannot write run {run_id} to {path}: {exc}") from exc
    return path


def load_run(run_id: str, results_dir: Path) -> dict:
    """Read one archived run."""
    path = Path(results_dir) / _check_run_id(run_id) / RUN_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ResultsNotFoundError(f"no run {run_id} in {results_dir}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ResultsCorruptError(f"cannot read {path}: {exc}") from exc
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResultsCorruptError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(record, dict):
        raise ResultsCorruptError(f"{path}: expected a JSON object, got {type(record).__name__}")
    missing = [k for k in RECORD_KEYS if k not in record]
    if missing:
        raise ResultsCorruptError(f"{path}: missing keys {missing}")
    for key, kind in CONTAINER_KEYS.items():
        if not isinstance(record[key], kind):
            raise ResultsCorruptError(f"{path}: {key} must be a {kind.__name__}")
    if record["run_id"] != run_id:
        raise ResultsCorruptError(f"{path}: run_id {record['run_id']!r} does not match {run_id}")
    return record


def list_runs(results_dir: Path) -> list[dict]:
    """Summaries of the readable runs, sorted by run ID; unreadable ones are skipped."""
    root = Path(results_dir)
    if not root.is_dir():
        return []
    try:
        folders = sorted(root.iterdir())
    except OSError as exc:
        raise ResultsError(f"cannot list {root}: {exc}") from exc
    runs = []
    for folder in folders:
        if not (folder / RUN_FILE).is_file():
            continue
        try:
            record = load_run(folder.name, root)
        except ResultsError as exc:
            logger.warning("skipping %s: %s", folder, exc)
            continue
        runs.append({"run_id": record["run_id"], "ammeter": record["ammeter"],
                     "started_at_utc": record["started_at_utc"],
                     "path": str(folder / RUN_FILE)})
    return runs


def compare_runs(run_id_a: str, run_id_b: str, results_dir: Path) -> dict:
    """Per statistic: value in a, value in b and delta = b - a (None if either is None)."""
    a = load_run(run_id_a, results_dir)
    b = load_run(run_id_b, results_dir)
    stats = {}
    for key in a["statistics"]:
        va, vb = a["statistics"][key], b["statistics"].get(key)
        stats[key] = {"a": va, "b": vb,
                      "delta": _delta(va, vb)}
    return {"run_a": run_id_a, "run_b": run_id_b,
            "same_ammeter": a["ammeter"] == b["ammeter"], "statistics": stats}


def _delta(a: object, b: object) -> float | None:
    """b - a for two real numbers, else None."""
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (a, b)):
        return b - a
    return None


def _discard(folder: Path, tmp: Path, remove_folder: bool) -> None:
    """Best-effort removal of the temp file, and of the folder if this call created it."""
    try:
        tmp.unlink(missing_ok=True)
        if remove_folder:
            folder.rmdir()
    except OSError as exc:
        logger.warning("could not clean up %s: %s", folder, exc)


def _check_run_id(run_id: object) -> str:
    """Reject anything that is not a well-formed run ID before it reaches a path."""
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ResultsError(f"invalid run id {run_id!r}; expected {RUN_ID_PATTERN.pattern}")
    return run_id
