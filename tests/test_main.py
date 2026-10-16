"""main.py reads every configured ammeter."""
import re
from pathlib import Path

from main import main
from tests.helpers import unused_port, write_config


def test_main_prints_one_reading_per_configured_ammeter(tmp_path: Path, capsys) -> None:
    """main() prints one reading line per ammeter and returns 0."""
    ports = {name: unused_port() for name in ("greenlee", "entes", "circutor")}
    path = write_config(tmp_path / "config.yaml", ports)

    assert main(path) == 0

    out = capsys.readouterr().out
    for name in ports:
        assert re.search(rf"^{name}: -?\d+(\.\d+)?(e[+-]?\d+)? A$", out, re.MULTILINE), out
