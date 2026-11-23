import math

import pytest

import tilemapgen

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

def _m():
    return tilemapgen.MapGen(1, 0.5)


def _check_shape():
    g = _m().generate(16, 16)
    return len(g) == 16 and len(g[0]) == 16


def _check_connected():
    m = _m()
    m.generate(16, 16)
    return m.is_connected() is True


def _check_det():
    return _m().generate(8, 8) == _m().generate(8, 8)


def _check_seed_diff():
    return tilemapgen.MapGen(1, 0.5).generate(8, 8) != tilemapgen.MapGen(2, 0.5).generate(8, 8)


def _check_bad_density():
    return _raises(lambda: tilemapgen.MapGen(1, 1.5))


def _check_bad_size():
    return _raises(lambda: _m().generate(0, 8))


def _check_type():
    return isinstance(_m().generate(8, 8), list)


def _check_connect_before_gen():
    return _raises(lambda: _m().is_connected())

CASES = [("shape", "_check_shape"), ("connected", "_check_connected"), ("det", "_check_det"), ("seed_diff", "_check_seed_diff"), ("bad_density", "_check_bad_density"), ("bad_size", "_check_bad_size"), ("type", "_check_type"), ("connect_before_gen", "_check_connect_before_gen"), ("smoke8", "_check_smoke8"), ("smoke9", "_check_smoke9"), ("smoke10", "_check_smoke10"), ("smoke11", "_check_smoke11"), ("smoke12", "_check_smoke12"), ("smoke13", "_check_smoke13"), ("smoke14", "_check_smoke14")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert MapGen() is not None
        return
    assert fn() is True
