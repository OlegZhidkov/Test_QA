"""main() exit codes."""
import socket
from pathlib import Path

from main import main
from tests.helpers import HOST, unused_port, write_config

NAMES = ("greenlee", "entes", "circutor")


def test_invalid_config_returns_2_and_names_the_key(tmp_path, capsys):
    ports = {name: unused_port() for name in NAMES}
    ports["greenlee"] = 0
    path = write_config(tmp_path / "c.yaml", ports)
    assert main(path) == 2
    assert "ammeters.greenlee.port" in capsys.readouterr().err


def test_missing_config_returns_2(tmp_path, capsys):
    assert main(tmp_path / "missing.yaml") == 2
    assert "missing.yaml" in capsys.readouterr().err


def test_emulator_that_cannot_start_returns_1(tmp_path, capsys):
    ports = {name: unused_port() for name in NAMES}
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind((HOST, 0))
        holder.listen()
        ports["entes"] = holder.getsockname()[1]
        path = write_config(tmp_path / "c.yaml", ports)
        assert main(path) == 1
    assert str(ports["entes"]) in capsys.readouterr().err
