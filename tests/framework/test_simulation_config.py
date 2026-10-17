"""Validation of the per-ammeter simulate_errors block."""
import copy
import json

import pytest

from src.utils.config import SEED_MAX, ErrorSimulation, load_config, parse_config
from src.utils.errors import ConfigError
from tests.framework.test_config import SHIPPED

BASE = {
    "testing": {
        "sampling": {"measurements_count": 12, "sampling_frequency_hz": 2},
        "request_timeout_seconds": 0.15,
    },
    "ammeters": {
        "greenlee": {
            "port": 5000,
            "command": "MEASURE_GREENLEE -get_measurement",
            "emulator": "Ammeters.Greenlee_Ammeter:GreenleeAmmeter",
            "expected_range": {"min_amps": 0.01, "max_amps": 100.0},
        },
        "entes": {
            "port": 5001,
            "command": "MEASURE_ENTES -get_data",
            "emulator": "Ammeters.Entes_Ammeter:EntesAmmeter",
            "expected_range": {"min_amps": 5.0, "max_amps": 200.0},
        },
    },
}
KEY = r"ammeters\.greenlee\.simulate_errors"


def parse_with(block, ammeter="greenlee", **testing_changes):
    """Parse BASE with `block` as the ammeter's simulate_errors."""
    data = copy.deepcopy(BASE)
    data["ammeters"][ammeter]["simulate_errors"] = block
    data["testing"].update(testing_changes)
    return parse_config(data, "t")


def test_valid_block_is_parsed_with_defaults():
    sim = parse_with({"seed": 7, "garbage": 0.5}).ammeters["greenlee"].simulate_errors
    assert sim == ErrorSimulation(seed=7, garbage=0.5)
    assert sim.stall_seconds is None
    assert sim.spike_factor == 1000.0


def test_absent_block_means_no_simulation():
    config = load_config(SHIPPED)
    assert all(s.simulate_errors is None for s in config.ammeters.values())


@pytest.mark.parametrize("seed", [0, SEED_MAX])
def test_seed_limits_are_accepted(seed):
    sim = parse_with({"seed": seed, "garbage": 0.5}).ammeters["greenlee"].simulate_errors
    assert sim.seed == seed


def test_stall_seconds_defaults_to_the_midpoint():
    sim = parse_with({"seed": 1, "stall": 0.2}).ammeters["greenlee"].simulate_errors
    assert sim.stall_seconds == pytest.approx((0.15 + 0.5) / 2)


BAD_VALUES = (
    [({"seed": 1, "garbage": v}, KEY + r"\.garbage")
     for v in (True, "0.1", float("nan"), float("inf"), -0.1, 1.5)]
    + [({"garbage": 0.5}, KEY + r"\.seed")]
    + [({"seed": v, "garbage": 0.5}, KEY + r"\.seed") for v in (-1, 2**32, True, 3.0, "7")]
    + [({"seed": 1, "garbage": 0.5, "spike_factor": v}, KEY + r"\.spike_factor")
       for v in (1.0, 0.5, float("inf"), 1e10, True)]
    + [({"seed": 1, "garbage": 0.5, "stall_seconds": v}, KEY + r"\.stall_seconds")
       for v in (0, -1, float("nan"))]
    + [({"seed": 1, "garbage": 0.5, "jitter": 1}, KEY + r"\.jitter")]
    + [("on", KEY)]
)


@pytest.mark.parametrize("block, pattern", BAD_VALUES)
def test_bad_values_name_the_dotted_key(block, pattern):
    with pytest.raises(ConfigError, match=pattern):
        parse_with(block)


def test_probabilities_summing_above_one_name_all_four_keys():
    with pytest.raises(ConfigError) as info:
        parse_with({"seed": 1, "no_response": 0.5, "garbage": 0.6})
    for field in ("no_response", "stall", "garbage", "out_of_range"):
        assert f"simulate_errors.{field}" in str(info.value)


def test_sum_of_exactly_one_is_accepted():
    block = {"seed": 1, "no_response": 0.25, "stall": 0.25, "garbage": 0.25,
             "out_of_range": 0.25}
    assert parse_with(block, ammeter="entes").ammeters["entes"].simulate_errors is not None


@pytest.mark.parametrize("block", [{"seed": 1}, {"seed": 1, "garbage": 0}])
def test_block_without_a_positive_probability_is_rejected(block):
    with pytest.raises(ConfigError, match="simulate_errors"):
        parse_with(block)


def test_simulation_needs_a_managed_emulator():
    data = copy.deepcopy(BASE)
    del data["ammeters"]["greenlee"]["emulator"]
    data["ammeters"]["greenlee"]["simulate_errors"] = {"seed": 1, "garbage": 0.5}
    with pytest.raises(ConfigError) as info:
        parse_config(data, "t")
    assert "ammeters.greenlee.simulate_errors" in str(info.value)
    assert "emulator" in str(info.value)


def test_stall_seconds_must_exceed_the_request_timeout():
    with pytest.raises(ConfigError, match=r"simulate_errors\.stall_seconds"):
        parse_with({"seed": 1, "stall": 0.2, "stall_seconds": 0.15})


def test_stall_seconds_must_be_below_the_interval():
    with pytest.raises(ConfigError, match=r"simulate_errors\.stall_seconds"):
        parse_with({"seed": 1, "stall": 0.2, "stall_seconds": 0.5})


def test_no_valid_stall_default_when_timeout_reaches_the_interval():
    with pytest.raises(ConfigError) as info:
        parse_with({"seed": 1, "stall": 0.1}, request_timeout_seconds=0.5)
    message = str(info.value)
    assert "simulate_errors.stall" in message
    assert "testing.request_timeout_seconds" in message
    assert "interval" in message


def test_stall_rule_is_ignored_when_stall_is_zero():
    parse_with({"seed": 1, "garbage": 0.5}, request_timeout_seconds=0.6)


def test_spike_factor_must_push_every_value_out_of_range():
    with pytest.raises(ConfigError, match="spike_factor"):
        parse_with({"seed": 1, "out_of_range": 0.5})
    parse_with({"seed": 1, "out_of_range": 0.5, "spike_factor": 1e6})
    parse_with({"seed": 1, "garbage": 0.5})


@pytest.mark.parametrize("min_amps", [0, 0.0, -1.0])
def test_out_of_range_needs_a_positive_min_amps(min_amps):
    data = copy.deepcopy(BASE)
    data["ammeters"]["greenlee"]["expected_range"] = {"min_amps": min_amps, "max_amps": 100.0}
    data["ammeters"]["greenlee"]["simulate_errors"] = {"seed": 1, "out_of_range": 1.0}
    with pytest.raises(ConfigError, match=KEY + r".*min_amps above 0"):
        parse_config(data, "t")


def test_non_positive_min_amps_is_fine_without_out_of_range_spikes():
    data = copy.deepcopy(BASE)
    data["ammeters"]["greenlee"]["expected_range"] = {"min_amps": 0.0, "max_amps": 100.0}
    data["ammeters"]["greenlee"]["simulate_errors"] = {"seed": 1, "garbage": 0.5}
    parse_config(data, "t")


def test_shipped_error_scenario_is_still_valid():
    load_config(SHIPPED.parent / "error_simulation.yaml")


def test_with_ports_keeps_the_simulation():
    config = parse_with({"seed": 1, "garbage": 0.5})
    moved = config.with_ports({"greenlee": 0})
    assert moved.ammeters["greenlee"].simulate_errors == config.ammeters["greenlee"].simulate_errors


def test_as_record_is_json_ready():
    sim = ErrorSimulation(seed=3, stall=0.1, stall_seconds=0.3)
    record = sim.as_record()
    assert json.loads(json.dumps(record, allow_nan=False)) == record
    assert set(record) == {"seed", "no_response", "stall", "garbage", "out_of_range",
                           "stall_seconds", "spike_factor"}


def test_first_error_follows_the_original_validation_order():
    data = copy.deepcopy(BASE)
    data["ammeters"]["greenlee"]["port"] = 0
    data["ammeters"]["greenlee"]["expected_range"] = {"min_amps": 5, "max_amps": 1}
    with pytest.raises(ConfigError, match=r"ammeters\.greenlee\.port"):
        parse_config(data, "t")
