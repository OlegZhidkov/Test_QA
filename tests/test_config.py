"""Config loading, defaults and validation."""
import copy
from pathlib import Path

import pytest
import yaml

from src.utils.config import (
    ExpectedRange,
    SamplingPlan,
    load_config,
    parse_config,
    resolve_sampling,
)
from src.utils.errors import ConfigError

SHIPPED = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
KEYS = ("measurements_count", "total_duration_seconds", "sampling_frequency_hz")

BASE = {
    "testing": {"sampling": {"measurements_count": 10, "total_duration_seconds": 2.0}},
    "ammeters": {
        "greenlee": {
            "port": 5000,
            "command": "MEASURE_GREENLEE -get_measurement",
            "expected_range": {"min_amps": 0.01, "max_amps": 100.0},
        },
        "entes": {
            "port": 5001,
            "command": "MEASURE_ENTES -get_data",
            "expected_range": {"min_amps": 5.0, "max_amps": 200.0},
        },
    },
}


def data(**changes):
    """Return a deep copy of BASE with dotted-path changes ('a.b.c': value; DEL removes)."""
    d = copy.deepcopy(BASE)
    for path, value in changes.items():
        parts = path.split("__")
        node = d
        for part in parts[:-1]:
            node = node[part]
        if value is DEL:
            del node[parts[-1]]
        else:
            node[parts[-1]] = value
    return d


DEL = object()


def test_shipped_config_loads_with_exact_commands_and_loopback_hosts():
    config = load_config(SHIPPED)
    assert set(config.ammeters) == {"greenlee", "entes", "circutor"}
    assert config.ammeters["greenlee"].command == b"MEASURE_GREENLEE -get_measurement"
    assert config.ammeters["entes"].command == b"MEASURE_ENTES -get_data"
    assert config.ammeters["circutor"].command == b"MEASURE_CIRCUTOR -get_measurement -current"
    assert {a.host for a in config.ammeters.values()} == {"127.0.0.1"}
    assert config.sampling == SamplingPlan(count=10, duration_s=2.0, frequency_hz=5.0)


def test_missing_file_names_the_path(tmp_path):
    path = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError, match="nope.yaml"):
        load_config(path)


def test_yaml_syntax_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("a: [1, 2\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_empty_file_mentions_top_level(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="top level"):
        load_config(path)


def test_missing_ammeters():
    with pytest.raises(ConfigError, match="ammeters"):
        parse_config(data(ammeters=DEL), "t")


def test_unknown_key_names_the_dotted_key():
    with pytest.raises(ConfigError, match=r"ammeters\.greenlee\.prot"):
        parse_config(data(ammeters__greenlee__prot=1), "t")
    with pytest.raises(ConfigError, match=r"testing\.sampling\.speed"):
        parse_config(data(testing__sampling__speed=1), "t")


@pytest.mark.parametrize("port", [0, 70000, "5000", True])
def test_bad_port(port):
    with pytest.raises(ConfigError, match=r"ammeters\.greenlee\.port"):
        parse_config(data(ammeters__greenlee__port=port), "t")


def test_duplicate_port_names_both_keys():
    with pytest.raises(ConfigError) as info:
        parse_config(data(ammeters__entes__port=5000), "t")
    assert "ammeters.entes.port" in str(info.value)
    assert "ammeters.greenlee.port" in str(info.value)


@pytest.mark.parametrize("name", ["Green-lee", "a/b", "UP"])
def test_bad_ammeter_name(name):
    d = data()
    d["ammeters"][name] = d["ammeters"].pop("entes")
    with pytest.raises(ConfigError, match="ammeters"):
        parse_config(d, "t")


def test_empty_command():
    with pytest.raises(ConfigError, match=r"ammeters\.greenlee\.command"):
        parse_config(data(ammeters__greenlee__command=""), "t")


def test_range_min_not_below_max():
    bad = {"min_amps": 5.0, "max_amps": 5.0}
    with pytest.raises(ConfigError, match="expected_range"):
        parse_config(data(ammeters__greenlee__expected_range=bad), "t")


def test_unknown_metric():
    with pytest.raises(ConfigError, match="statistical_metrics"):
        parse_config(data(analysis={"statistical_metrics": ["mean", "mode"]}), "t")


def test_defaults_are_applied():
    config = parse_config(data(), "t")
    assert config.request_timeout_s == 2.0
    assert config.emulator_start_timeout_s == 5.0
    assert config.ammeters["greenlee"].host == "127.0.0.1"
    assert config.ammeters["greenlee"].emulator is None
    assert config.metrics == ("mean", "median", "stdev", "min", "max", "cv_percent")
    assert config.results_dir == Path("results")
    assert config.source == "t"


def test_with_ports_replaces_only_ports():
    config = parse_config(data(), "t").with_ports({"greenlee": 0})
    assert config.ammeters["greenlee"].port == 0
    assert config.ammeters["entes"].port == 5001


def test_expected_range_contains_is_inclusive_with_tolerance():
    r = ExpectedRange(1.0, 2.0)
    assert r.contains(1.0) and r.contains(2.0) and r.contains(1.5)
    assert r.contains(2.0 * (1 + 1e-12))
    assert not r.contains(2.1) and not r.contains(0.9) and not r.contains(float("nan"))


def test_count_and_duration_give_frequency():
    assert resolve_sampling(10, 2.0, None, "s") == SamplingPlan(10, 2.0, 5.0)


def test_count_and_frequency_give_duration():
    assert resolve_sampling(10, None, 5.0, "s") == SamplingPlan(10, 2.0, 5.0)


def test_duration_and_frequency_give_count():
    assert resolve_sampling(None, 2.0, 5.0, "s") == SamplingPlan(10, 2.0, 5.0)


def test_three_consistent_values_pass():
    assert resolve_sampling(10, 2.0, 5.0, "s") == SamplingPlan(10, 2.0, 5.0)


def test_interval_is_the_inverse_of_the_frequency():
    assert resolve_sampling(10, 2.0, None, "s").interval_s == pytest.approx(0.2)


def test_three_inconsistent_values_name_all_keys():
    with pytest.raises(ConfigError) as info:
        resolve_sampling(10, 2.0, 4.0, "testing.sampling")
    for key in KEYS:
        assert f"testing.sampling.{key}" in str(info.value)


@pytest.mark.parametrize("args", [(10, None, None), (None, 2.0, None), (None, None, 5.0),
                                  (None, None, None)])
def test_fewer_than_two_values_name_all_keys(args):
    with pytest.raises(ConfigError) as info:
        resolve_sampling(*args, "testing.sampling")
    for key in KEYS:
        assert f"testing.sampling.{key}" in str(info.value)


def test_non_integer_count_from_duration_and_frequency():
    with pytest.raises(ConfigError):
        resolve_sampling(None, 1.0, 2.5, "s")


@pytest.mark.parametrize("args", [(True, 2.0, None), (0, 2.0, None), (-3, 2.0, None),
                                  (10, 0, None), (10, -1.0, None), (10, None, 0.0),
                                  (10, True, None), (10, "2", None), (10.0, 2.0, None)])
def test_bad_sampling_values(args):
    with pytest.raises(ConfigError):
        resolve_sampling(*args, "s")


def test_sampling_in_config_is_resolved():
    d = data(testing__sampling={"measurements_count": 5, "sampling_frequency_hz": 10})
    assert parse_config(d, "t").sampling == SamplingPlan(5, 0.5, 10.0)


def test_loading_yaml_text_matches_parse(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(data()), encoding="utf-8")
    assert load_config(path).source == str(path)


HUGE = 10 ** 400


@pytest.mark.parametrize("key, change", [
    ("expected_range.min_amps", {"ammeters__greenlee__expected_range": {"min_amps": HUGE,
                                                                       "max_amps": 1.0}}),
    ("expected_range.max_amps", {"ammeters__greenlee__expected_range": {"min_amps": 0.1,
                                                                        "max_amps": HUGE}}),
    ("testing.request_timeout_seconds", {"testing__request_timeout_seconds": HUGE}),
    ("testing.sampling.total_duration_seconds",
     {"testing__sampling": {"measurements_count": 3, "total_duration_seconds": HUGE}}),
])
def test_huge_integer_is_a_config_error_naming_the_key(key, change):
    with pytest.raises(ConfigError, match=key.replace(".", r"\.")):
        parse_config(data(**change), "t")


def test_default_config_path_is_anchored_at_the_repo_root(monkeypatch, tmp_path):
    from src.utils.config import DEFAULT_CONFIG_PATH
    monkeypatch.chdir(tmp_path)
    assert DEFAULT_CONFIG_PATH.is_absolute() and DEFAULT_CONFIG_PATH == SHIPPED
    assert load_config().ammeters
