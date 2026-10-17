"""The timing check shared by the end-to-end suites."""
from src.testing.models import Reading
from tests.helpers import MAX_LATENESS_S, TYPICAL_LATENESS_S, off_schedule


def readings(lateness):
    """Readings 0.2 s apart, reading i taken lateness[i] seconds after its slot."""
    return [Reading(i, "t", i * 0.2, i * 0.2 + late, 1.0, None) for i, late in enumerate(lateness)]


def test_a_single_pause_within_the_limit_is_tolerated():
    assert off_schedule(readings([0, 0, 0.12, 0, 0, 0, 0, 0])) == []


def test_a_single_pause_beyond_the_limit_is_reported():
    problems = off_schedule(readings([0, 0, MAX_LATENESS_S + 0.05, 0, 0]))
    assert len(problems) == 1 and problems[0].startswith("reading 2")


def test_a_schedule_shifted_for_most_readings_is_reported():
    shifted = [0, 0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
    assert TYPICAL_LATENESS_S < 0.1 < MAX_LATENESS_S
    assert off_schedule(readings(shifted)) == ["median lateness +0.100 s"]


def test_readings_taken_back_to_back_are_reported():
    assert off_schedule(readings([0, -0.2, -0.4, -0.6, -0.8]))
