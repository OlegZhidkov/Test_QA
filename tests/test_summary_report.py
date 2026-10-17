"""The "Ammeter runs" summary, checked in a sub-session."""
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def prepare(pytester, test_source: str) -> None:
    """Copy the conftest, helpers, src and config into the sub-session."""
    for name in ("src", "Ammeters", "config"):
        shutil.copytree(ROOT / name, pytester.path / name,
                        ignore=shutil.ignore_patterns("__pycache__"))
    (pytester.path / "tests").mkdir()
    shutil.copy(ROOT / "tests" / "__init__.py", pytester.path / "tests")
    shutil.copy(ROOT / "tests" / "helpers.py", pytester.path / "tests")
    (pytester.path / "conftest.py").write_text((ROOT / "tests" / "conftest.py").read_text())
    (pytester.path / "test_sub.py").write_text(test_source)


def test_ammeter_run_tests_print_the_runs_section(pytester):
    prepare(pytester, "def test_x(run_result):\n    assert run_result.run_id\n")
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-k", "greenlee")
    out = result.stdout.str()
    assert "Ammeter runs" in out
    assert re.search(r"Run ID: \S+_greenlee_\w+", out)
    result.assert_outcomes(passed=1)


def test_no_section_without_ammeter_runs(pytester):
    prepare(pytester, "def test_x():\n    assert True\n")
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    assert "Ammeter runs" not in result.stdout.str()
    result.assert_outcomes(passed=1)
