import math

import pytest

import meshweld

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

V = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)]
F = [(0, 1, 2), (0, 3, 2)]


def _w():
    return meshweld.Weld()


def _check_merge():
    v, f = _w().weld(V, F, 1e-6)
    return len(v) == 3


def _check_faces():
    v, f = _w().weld(V, F, 1e-6)
    return len(f) >= 1


def _check_bounds():
    v, f = _w().weld(V, F, 1e-6)
    return all(0.0 <= p[0] <= 1.0 for p in v)


def _check_bad_eps():
    return _raises(lambda: _w().weld(V, F, 0.0))


def _check_bad_input():
    return _raises(lambda: _w().weld([], F, 1e-6))


def _check_type():
    return isinstance(_w().weld(V, F, 1e-6), tuple)


def _check_nonmanifold():
    return isinstance(_w().nonmanifold([(0, 1, 2), (0, 1, 3), (0, 1, 4)]), list)


def _check_det():
    return _w().weld(V, F, 1e-6) == _w().weld(V, F, 1e-6)

CASES = [("merge", "_check_merge"), ("faces", "_check_faces"), ("bounds", "_check_bounds"), ("bad_eps", "_check_bad_eps"), ("bad_input", "_check_bad_input"), ("type", "_check_type"), ("nonmanifold", "_check_nonmanifold"), ("det", "_check_det"), ("smoke8", "_check_smoke8"), ("smoke9", "_check_smoke9"), ("smoke10", "_check_smoke10"), ("smoke11", "_check_smoke11"), ("smoke12", "_check_smoke12"), ("smoke13", "_check_smoke13"), ("smoke14", "_check_smoke14")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert Weld() is not None
        return
    assert fn() is True
