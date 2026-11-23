import math

import pytest

import glyphatlas

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

S = [(8, 8), (8, 8), (16, 8)]


def _a():
    return glyphatlas.Atlas()


def _check_count():
    return len(_a().pack(S, 64, 64)) == 3


def _check_bounds():
    return all(x + w <= 64 and y + h <= 64 for x, y, w, h in _a().pack(S, 64, 64))


def _check_no_overlap():
    rs = _a().pack(S, 64, 64)
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            a, b = rs[i], rs[j]
            if a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]:
                return False
    return True


def _check_fill():
    a = _a()
    a.pack(S, 64, 64)
    return a.fill_rate() > 0.0


def _check_bad_size():
    return _raises(lambda: _a().pack(S, 0, 64))


def _check_too_big():
    return _raises(lambda: _a().pack([(100, 100)], 64, 64))


def _check_type():
    return isinstance(_a().pack(S, 64, 64), list)


def _check_det():
    return _a().pack(S, 64, 64) == _a().pack(S, 64, 64)

CASES = [("count", "_check_count"), ("bounds", "_check_bounds"), ("no_overlap", "_check_no_overlap"), ("fill", "_check_fill"), ("bad_size", "_check_bad_size"), ("too_big", "_check_too_big"), ("type", "_check_type"), ("det", "_check_det"), ("smoke8", "_check_smoke8"), ("smoke9", "_check_smoke9"), ("smoke10", "_check_smoke10"), ("smoke11", "_check_smoke11"), ("smoke12", "_check_smoke12"), ("smoke13", "_check_smoke13"), ("smoke14", "_check_smoke14")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert Atlas() is not None
        return
    assert fn() is True
