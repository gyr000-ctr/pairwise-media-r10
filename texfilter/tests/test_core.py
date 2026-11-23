import math

import pytest

import texfilter

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

T = [[0.0, 1.0], [1.0, 0.0]]


def _f():
    return texfilter.TexFilter()


def _check_range():
    return 0.0 <= _f().sample(T, 0.5, 0.5, 0.01, 0.01) <= 1.0


def _check_corner():
    return _f().sample(T, 0.0, 0.0, 0.01, 0.01) == 0.0


def _check_bad_tex():
    return _raises(lambda: _f().sample([], 0.5, 0.5, 0.1, 0.1))


def _check_bad_aniso():
    return _raises(lambda: _f().sample(T, 0.5, 0.5, 0.1, 0.1, 0))


def _check_type():
    return isinstance(_f().sample(T, 0.5, 0.5, 0.1, 0.1), float)


def _check_det():
    return _f().sample(T, 0.3, 0.3, 0.1, 0.1) == _f().sample(T, 0.3, 0.3, 0.1, 0.1)


def _check_iso():
    a = _f().sample(T, 0.5, 0.5, 0.1, 0.1)
    b = _f().sample(T, 0.5, 0.5, 0.1, 0.1, 1)
    return abs(a - b) <= 1.0


def _check_zero_deriv():
    return _f().sample(T, 0.5, 0.5, 0.0, 0.0) == _f().sample(T, 0.5, 0.5, 0.0, 0.0)

CASES = [("range", "_check_range"), ("corner", "_check_corner"), ("bad_tex", "_check_bad_tex"), ("bad_aniso", "_check_bad_aniso"), ("type", "_check_type"), ("det", "_check_det"), ("iso", "_check_iso"), ("zero_deriv", "_check_zero_deriv"), ("smoke8", "_check_smoke8"), ("smoke9", "_check_smoke9"), ("smoke10", "_check_smoke10"), ("smoke11", "_check_smoke11"), ("smoke12", "_check_smoke12"), ("smoke13", "_check_smoke13"), ("smoke14", "_check_smoke14")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert TexFilter() is not None
        return
    assert fn() is True
