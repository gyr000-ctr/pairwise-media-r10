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


def _check_remap():
    # 3 号点与 1 号点重合被并入，索引应重映射为 1
    v, f = _w().weld(V, [(0, 3, 2)], 1e-6)
    return len(v) == 3 and f == [(0, 1, 2)]


def _check_no_dup_faces():
    # 焊接前两个面分别是 (0,1,2) 与 (0,3,2)；3 并入 1 后成为同一三角形
    v, f = _w().weld(V, F, 1e-6)
    keys = [tuple(sorted(t)) for t in f]
    return len(keys) == len(set(keys))


def _check_winding_dedup():
    # 同顶点集、不同朝向/起点算重复三角形
    v, f = _w().weld(V, [(0, 1, 2), (1, 2, 0), (2, 1, 0)], 1e-6)
    return len(f) == 1


def _check_nonmanifold_detect():
    w = _w()
    edges = w.nonmanifold([(0, 1, 2), (1, 0, 3), (0, 1, 4), (5, 6, 7)])
    return edges == [(0, 1)]


def _check_nonmanifold_clean():
    # 闭合四面体：每条边恰好两个面，非流形边为空
    return _w().nonmanifold(
        [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]
    ) == []


def _check_bbox_exact():
    pts = [(-3.5, 0.0, 0.0), (0.0, 4.25, 0.0), (0.0, 0.0, -2.75),
           (-3.5 + 1e-9, 0.0, 0.0), (0.0, 4.25 - 1e-9, 0.0)]
    v, f = _w().weld(pts, [], 1e-6)
    box = lambda ps: [(min(p[k] for p in ps), max(p[k] for p in ps)) for k in range(3)]
    return box(v) == box(pts)


def _check_tolerance_chain():
    # 相距 0.6*eps 的三点串联：传递闭包应合成一个顶点
    pts = [(0.0, 0.0, 0.0), (0.6e-6, 0.0, 0.0), (1.2e-6, 0.0, 0.0)]
    v, f = _w().weld(pts, [], 1e-6)
    return len(v) == 1


def _check_tolerance_boundary():
    # 跨格边界（0.9*eps 与 1.1*eps 分属不同格）仍应合并
    pts = [(0.0, 0.0, 0.0), (0.9e-3, 0.0, 0.0), (1.1e-3, 0.0, 0.0)]
    v, f = _w().weld(pts, [], 1e-3)
    return len(v) == 1


def _check_outside_tolerance():
    # 明确大于 eps 的点不合并
    pts = [(0.0, 0.0, 0.0), (3e-6, 0.0, 0.0)]
    v, f = _w().weld(pts, [], 1e-6)
    return len(v) == 2


def _check_degenerate_face():
    # 三点焊接后退化为线段的面应被剔除
    v, f = _w().weld([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1e-9, 0.0, 0.0)], [(0, 1, 2)], 1e-6)
    return f == []


def _check_bad_oob_index():
    return _raises(lambda: _w().weld(V, [(0, 1, 4)], 1e-6))


def _check_bad_dims():
    return _raises(lambda: _w().weld([(0.0, 0.0)], F, 1e-6))


def _check_nonfinite():
    return (_raises(lambda: _w().weld([(0.0, float("nan"), 0.0)], F, 1e-6))
            and _raises(lambda: _w().weld([(0.0, 0.0, float("inf"))], F, 1e-6))
            and _raises(lambda: _w().weld(V, F, float("nan"))))


def _check_type_errors():
    # 类型非法抛 TypeError，可与语义 ValueError 区分
    return (_raises(lambda: _w().weld(V, F, "1e-6"), TypeError)
            and _raises(lambda: _w().weld(None, F, 1e-6), TypeError)
            and _raises(lambda: _w().weld(V, F, True), TypeError))


def _check_empty_faces_ok():
    v, f = _w().weld(V, [], 1e-6)
    return len(v) == 3 and f == []


def _check_identity():
    # eps 很小且无重合点：顶点与索引原样返回
    pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    return _w().weld(pts, [(0, 1, 2)], 1e-9) == (pts, [(0, 1, 2)])


def _check_positions_exact():
    # 代表点必须来自原始输入（不得产生平均/插值坐标）
    pts = [(0.0, 0.0, 0.0), (1e-7, 0.0, 0.0)]
    v, f = _w().weld(pts, [], 1e-6)
    return len(v) == 1 and v[0] in pts


def _check_perf_10k():
    import random
    import time
    rnd = random.Random(1)
    pts = [(rnd.uniform(-50, 50), rnd.uniform(-50, 50), rnd.uniform(-50, 50))
           for _ in range(10000)]
    faces = [(i, (i + 1) % 10000, (i + 2) % 10000) for i in range(10000)]
    start = time.perf_counter()
    _w().weld(pts, faces, 1e-5)
    return (time.perf_counter() - start) <= 0.4


def _check_perf_10k_dense():
    # 1 万点全部落在容差内（最坏合并场景）也须在 400 ms 内
    import random
    import time
    rnd = random.Random(2)
    pts = [(rnd.uniform(-1, 1) * 1e-6, rnd.uniform(-1, 1) * 1e-6,
            rnd.uniform(-1, 1) * 1e-6) for _ in range(10000)]
    start = time.perf_counter()
    v, f = _w().weld(pts, [], 1e-6)
    return len(v) == 1 and (time.perf_counter() - start) <= 0.4


CASES = [("merge", "_check_merge"), ("faces", "_check_faces"), ("bounds", "_check_bounds"), ("bad_eps", "_check_bad_eps"), ("bad_input", "_check_bad_input"), ("type", "_check_type"), ("nonmanifold", "_check_nonmanifold"), ("det", "_check_det"), ("remap", "_check_remap"), ("no_dup_faces", "_check_no_dup_faces"), ("winding_dedup", "_check_winding_dedup"), ("nonmanifold_detect", "_check_nonmanifold_detect"), ("nonmanifold_clean", "_check_nonmanifold_clean"), ("bbox_exact", "_check_bbox_exact"), ("tolerance_chain", "_check_tolerance_chain"), ("tolerance_boundary", "_check_tolerance_boundary"), ("outside_tolerance", "_check_outside_tolerance"), ("degenerate_face", "_check_degenerate_face"), ("bad_oob_index", "_check_bad_oob_index"), ("bad_dims", "_check_bad_dims"), ("nonfinite", "_check_nonfinite"), ("type_errors", "_check_type_errors"), ("empty_faces_ok", "_check_empty_faces_ok"), ("identity", "_check_identity"), ("positions_exact", "_check_positions_exact"), ("perf_10k", "_check_perf_10k"), ("perf_10k_dense", "_check_perf_10k_dense")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    fn = globals().get(check)
    if fn is None:
        assert Weld() is not None
        return
    assert fn() is True
