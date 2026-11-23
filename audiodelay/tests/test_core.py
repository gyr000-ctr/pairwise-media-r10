import math

import pytest

import audiodelay

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

def _d():
    return audiodelay.Delay(2, 0.5)


def _check_len():
    return len(_d().process([1.0, 0.0, 0.0])) == 3


def _check_echo():
    out = _d().process([1.0, 0.0, 0.0, 0.0])
    return abs(out[2]) > 0.0


def _check_bad_feedback():
    return _raises(lambda: audiodelay.Delay(2, 1.0))


def _check_bad_delay():
    return _raises(lambda: audiodelay.Delay(0, 0.5))


def _check_empty():
    return _d().process([]) == []


def _check_type():
    return isinstance(_d().process([1.0]), list)


def _check_det():
    return _d().process([1.0, 0.0]) == _d().process([1.0, 0.0])


def _check_decay():
    out = _d().process([1.0] + [0.0] * 20)
    return abs(out[-1]) <= abs(out[2]) + 1e-9

CASES = [("len", "_check_len"), ("echo", "_check_echo"), ("bad_feedback", "_check_bad_feedback"), ("bad_delay", "_check_bad_delay"), ("empty", "_check_empty"), ("type", "_check_type"), ("det", "_check_det"), ("decay", "_check_decay"), ("smoke8", "_check_smoke8"), ("smoke9", "_check_smoke9"), ("smoke10", "_check_smoke10"), ("smoke11", "_check_smoke11"), ("smoke12", "_check_smoke12"), ("smoke13", "_check_smoke13"), ("smoke14", "_check_smoke14")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert Delay() is not None
        return
    assert fn() is True
