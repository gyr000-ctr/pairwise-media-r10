"""各向异性纹理过滤验收测试。

覆盖：
- 与暴力超采样参考实现对照（PSNR ≥ 40 dB，含各向同性/强各向异性、两种边界）
- 各向异性比钳制
- 权重和为 1（常数纹理逐字节还原）
- wrap / clamp 两种边界
- 1 万像素性能上界 500 ms
- 非法参数与非有限输入分类报错
- 并发安全
"""

import math
import random
import threading
import time

import pytest

from texfilter import TexFilter

RNG = random.Random(20261124)


# ----------------------------------------------------------------------
# 辅助：暴力超采样参考实现（独立编写，走与被测代码不同的实现路径）
#
# 主参考：最近邻纹素场的稠密网格超采样（被测解析盒式积分正是它的
# 连续极限，因此收敛后 PSNR 应远高于 40 dB）。另保留双线性超采样，
# 作为跨模型一致性的弱校验（两种低通滤波在大足迹下结果应接近）。
# ----------------------------------------------------------------------
def _nearest_index(x, size, mode):
    idx = math.floor(x + 0.5)
    if mode == "wrap":
        return idx % size
    return min(max(idx, 0), size - 1)


def _ref_nearest(tex, u, v, mode):
    h = len(tex)
    w = len(tex[0])
    i = _nearest_index(u * w, w, mode)
    j = _nearest_index(v * h, h, mode)
    return tex[j][i]


def _ref_bilinear(tex, u, v, mode):
    h = len(tex)
    w = len(tex[0])
    fu, fv = u * w, v * h
    i0 = math.floor(fu)
    j0 = math.floor(fv)
    a, b = fu - i0, fv - j0
    if mode == "wrap":
        i0, j0 = i0 % w, j0 % h
        i1, j1 = (i0 + 1) % w, (j0 + 1) % h
    else:
        i0 = min(max(i0, 0), w - 1)
        i1 = min(max(i0 + 1, 0), w - 1)
        j0 = min(max(j0, 0), h - 1)
        j1 = min(max(j0 + 1, 0), h - 1)
    r0, r1 = tex[j0], tex[j1]
    return (
        (1 - a) * (1 - b) * r0[i0]
        + a * (1 - b) * r0[i1]
        + (1 - a) * b * r1[i0]
        + a * b * r1[i1]
    )


def brute_force_sample(tex, u, v, du, dv, mode, steps=55):
    """在足迹外接矩形上做 steps×steps 最近邻网格超采样。"""
    su, sv = abs(du), abs(dv)
    if su < 1e-12 and sv < 1e-12:
        return _ref_nearest(tex, u, v, mode)
    acc = 0.0
    n = 0
    for i in range(steps):
        uu = u - su + (2 * su) * (i + 0.5) / steps
        for j in range(steps):
            vv = v - sv + (2 * sv) * (j + 0.5) / steps
            acc += _ref_nearest(tex, uu, vv, mode)
            n += 1
    return acc / n


def _psnr(approx, ref, data_range=1.0):
    mse = sum((a - b) ** 2 for a, b in zip(approx, ref)) / len(ref)
    if mse == 0.0:
        return float("inf")
    return 10.0 * math.log10(data_range ** 2 / mse)


def _make_textures():
    rng = random.Random(7)
    w, h = 24, 24
    random_tex = [[rng.random() for _ in range(w)] for _ in range(h)]
    gradient = [[i / (w - 1) * 0.7 + j / (h - 1) * 0.3 for i in range(w)]
                for j in range(h)]
    checker = [[float((i + j) % 2) for i in range(8)] for j in range(8)]
    tiny = [[0.0, 1.0], [1.0, 0.0]]
    return [random_tex, gradient, checker, tiny]


# ----------------------------------------------------------------------
# 1. 与暴力超采样对照：PSNR ≥ 40 dB
# ----------------------------------------------------------------------
def test_filter_psnr_against_brute_force():
    footprints = [
        (0.020, 0.020),   # 各向同性
        (0.100, 0.010),   # 强各向异性（u 方向拉长，10:1）
        (0.008, 0.090),   # 强各向异性（v 方向拉长）
        (0.050, 0.025),   # 中等各向异性 2:1
    ]
    for mode in ("clamp", "wrap"):
        f = TexFilter(wrap=mode)
        approx, ref = [], []
        for tex in _make_textures():
            rng = random.Random(hash((mode, len(tex), len(tex[0]))) & 0xFFFF)
            for _ in range(12):
                u = rng.uniform(0.1, 0.9)
                v = rng.uniform(0.1, 0.9)
                du, dv = footprints[rng.randrange(len(footprints))]
                approx.append(f.sample(tex, u, v, du, dv, max_aniso=8))
                ref.append(brute_force_sample(tex, u, v, du, dv, mode))
        score = _psnr(approx, ref)
        assert score >= 40.0, f"PSNR={score:.2f} dB（mode={mode}）"


def test_filter_psnr_improves_with_aniso():
    """拉长足迹下，提高各向异性比应逼近暴力参考。"""
    tex = _make_textures()[2]  # 棋盘格高频纹理
    f = TexFilter(wrap="clamp")
    u, v, du, dv = 0.5, 0.5, 0.12, 0.01
    target = brute_force_sample(tex, u, v, du, dv, "clamp", steps=49)
    err_iso = abs(f.sample(tex, u, v, du, dv, max_aniso=1) - target)
    err_aniso = abs(f.sample(tex, u, v, du, dv, max_aniso=8) - target)
    assert err_aniso <= err_iso + 1e-12
    assert err_aniso < 0.05


def test_filter_cross_model_smooth_texture():
    """对平滑/渐变纹理，盒式模型与双线性超采样参考也应高度一致。

    盒式（最近邻单元面积加权）与双线性帐篷基函数仅在单纹素级高频内容上
    存在模型差异；渐变纹理下两种低通滤波应取得 ≥40 dB 的跨模型一致性。
    """
    tex = _make_textures()[1]  # 双线性渐变，无单纹素跳变
    f = TexFilter(wrap="clamp")
    rng = random.Random(23)
    approx, ref = [], []
    for _ in range(20):
        u, v = rng.uniform(0.1, 0.9), rng.uniform(0.1, 0.9)
        du, dv = rng.uniform(0.01, 0.06), rng.uniform(0.01, 0.06)
        approx.append(f.sample(tex, u, v, du, dv, max_aniso=8))
        # 双线性超采样（独立参考路径）。
        acc, n = 0.0, 31
        for i in range(n):
            uu = u - du + 2 * du * (i + 0.5) / n
            for j in range(n):
                vv = v - dv + 2 * dv * (j + 0.5) / n
                acc += _ref_bilinear(tex, uu, vv, "clamp")
        ref.append(acc / (n * n))
    assert _psnr(approx, ref) >= 40.0


# ----------------------------------------------------------------------
# 2. 各向异性比正确钳制
# ----------------------------------------------------------------------
def test_filter_anisotropy_ratio_clamped():
    f = TexFilter()
    tex = _make_textures()[0]
    u, v = 0.5, 0.5
    # 真实比值 5：max_aniso ≥ 5 后探针数不再变化，结果必须逐位一致。
    base = f.sample(tex, u, v, 0.10, 0.02, max_aniso=5)
    for cap in (6, 8, 16, 32):
        assert f.sample(tex, u, v, 0.10, 0.02, max_aniso=cap) == base
    # 被钳制到更低比值时结果可以不同，但必须有限且落在纹素值域内。
    lo = f.sample(tex, u, v, 0.10, 0.02, max_aniso=1)
    assert math.isfinite(lo)


def test_filter_max_aniso_one_is_isotropic():
    f = TexFilter()
    tex = _make_textures()[1]
    # max_aniso=1：唯一探针覆盖整个足迹矩形，解析积分即矩形盒式滤波。
    got = f.sample(tex, 0.5, 0.5, 0.10, 0.01, max_aniso=1)
    expected = brute_force_sample(tex, 0.5, 0.5, 0.10, 0.01, "clamp", steps=33)
    assert abs(got - expected) < 0.02
    # 各向同性足迹下退化为标准盒式滤波。
    got_iso = f.sample(tex, 0.5, 0.5, 0.05, 0.05, max_aniso=1)
    exp_iso = brute_force_sample(tex, 0.5, 0.5, 0.05, 0.05, "clamp", steps=33)
    assert abs(got_iso - exp_iso) < 0.01


# ----------------------------------------------------------------------
# 3. 权重和为 1
# ----------------------------------------------------------------------
def test_filter_weights_sum_to_one():
    f = TexFilter()
    for constant in (0.0, 0.375, 1.0, -2.5, 3.125):
        tex = [[constant] * 6 for _ in range(5)]
        for mode in ("clamp", "wrap"):
            got = f.sample(tex, 0.3, 0.7, 0.05, 0.02, max_aniso=8, wrap=mode)
            assert got == constant, (constant, mode)
            got = f.sample(tex, -1.7, 2.3, 0.0, 0.0, wrap=mode)
            assert got == constant, (constant, mode)


def test_filter_output_within_texel_range():
    f = TexFilter()
    rng = random.Random(11)
    tex = [[rng.random() for _ in range(10)] for _ in range(8)]
    lo = min(min(row) for row in tex)
    hi = max(max(row) for row in tex)
    for _ in range(50):
        u, v = rng.uniform(-0.5, 1.5), rng.uniform(-0.5, 1.5)
        du, dv = rng.uniform(0.0, 0.08), rng.uniform(0.0, 0.08)
        out = f.sample(tex, u, v, du, dv, max_aniso=rng.randint(1, 8))
        assert lo - 1e-12 <= out <= hi + 1e-12


# ----------------------------------------------------------------------
# 4. 边界 wrap / clamp
# ----------------------------------------------------------------------
def test_filter_wrap_is_periodic():
    f = TexFilter(wrap="wrap")
    tex = _make_textures()[0]
    for shift in ((1.0, 0.0), (0.0, -1.0), (2.0, 3.0)):
        a = f.sample(tex, 0.3, 0.6, 0.03, 0.02)
        b = f.sample(tex, 0.3 + shift[0], 0.6 + shift[1], 0.03, 0.02)
        assert a == pytest.approx(b, abs=1e-12)


def test_filter_clamp_pins_to_edge():
    f = TexFilter(wrap="clamp")
    tex = _make_textures()[0]
    # 点采样在纹理外：必须严格等于边缘纹素（clamp-to-edge 双线性退化）。
    assert f.sample(tex, -5.0, 0.0, 0.0, 0.0) == tex[0][0]
    assert f.sample(tex, 5.0, -5.0, 0.0, 0.0) == tex[0][len(tex[0]) - 1]
    assert f.sample(tex, -5.0, 0.5, 0.0, 0.0) == tex[len(tex) // 2][0]
    # 面采样：整个矩形位于域外（索引区间 [-7.68, -6.72]，碰不到单元 0）时，
    # clamp 必须完全钳到边缘列，不混入任何内侧纹素。v 方向取在纹素单元中心，
    # 使纵向贡献退化为单一行。
    edge_out = f.sample(tex, -0.30, 0.5, 0.02, 0.0)
    assert edge_out == tex[12][0]
    # 跨越边界的矩形：clamp 把域外部分并入边缘列；与同形 wrap 结果必然不同。
    cross_clamp = f.sample(tex, 0.0, 0.5, 0.03, 0.02)
    cross_wrap = TexFilter(wrap="wrap").sample(tex, 0.0, 0.5, 0.03, 0.02)
    assert cross_clamp != cross_wrap


def test_filter_wrap_and_clamp_differ_at_border():
    fw = TexFilter(wrap="wrap")
    fc = TexFilter(wrap="clamp")
    tex = [[float(i) for i in range(8)] for _ in range(8)]
    # 非对称越过左边界（索引区间 [-0.56, 0.24]）：wrap 把负侧折到最右列
    # （值 7），clamp 则把该部分并入第 0 列（值 0），两者必然不同。
    a = fw.sample(tex, -0.02, 0.5, 0.05, 0.01)
    b = fc.sample(tex, -0.02, 0.5, 0.05, 0.01)
    assert a != b
    assert a > b  # wrap 取到了高值边缘列


def test_filter_per_call_wrap_override():
    f = TexFilter(wrap="clamp")  # 构造默认 clamp
    tex = [[float(i) for i in range(8)] for _ in range(8)]
    periodic = f.sample(tex, 1.02, 0.5, 0.01, 0.01, wrap="wrap")
    inside = f.sample(tex, 0.02, 0.5, 0.01, 0.01, wrap="wrap")
    assert periodic == pytest.approx(inside, abs=1e-12)


# ----------------------------------------------------------------------
# 5. 性能：1 万像素 ≤ 500 ms
# ----------------------------------------------------------------------
def test_filter_performance_10k_pixels():
    rng = random.Random(99)
    tex = [[rng.random() for _ in range(32)] for _ in range(32)]
    queries = [
        (rng.uniform(0.0, 1.0), rng.uniform(0.0, 1.0),
         rng.uniform(0.002, 0.06), rng.uniform(0.002, 0.06))
        for _ in range(10000)
    ]
    f = TexFilter()
    t0 = time.perf_counter()
    for u, v, du, dv in queries:
        out = f.sample(tex, u, v, du, dv, max_aniso=8)
        assert isinstance(out, float)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms <= 500.0, f"10k 像素耗时 {elapsed_ms:.1f} ms"


# ----------------------------------------------------------------------
# 6. 非法参数 / 非有限输入分类报错
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_aniso": 0},
        {"max_aniso": -1},
        {"max_aniso": 1.5},
        {"max_aniso": True},
        {"max_aniso": 65},
    ],
)
def test_filter_bad_aniso(kwargs):
    f = TexFilter()
    tex = [[0.0, 1.0], [1.0, 0.0]]
    with pytest.raises(ValueError):
        f.sample(tex, 0.5, 0.5, 0.1, 0.1, **kwargs)


@pytest.mark.parametrize(
    "tex",
    [
        [],
        [[]],
        [[1.0, 2.0], [3.0]],                       # 非矩形
        [[1.0, "x"], [2.0, 3.0]],                  # 非数值纹素
        [[1.0, float("nan")], [2.0, 3.0]],         # 非有限纹素
        [[1.0, float("inf")], [2.0, 3.0]],
        "not-a-texture",
    ],
)
def test_filter_bad_texture(tex):
    f = TexFilter()
    with pytest.raises(ValueError):
        f.sample(tex, 0.5, 0.5, 0.1, 0.1)


@pytest.mark.parametrize(
    "u,v,du,dv",
    [
        (float("nan"), 0.5, 0.1, 0.1),
        (0.5, float("inf"), 0.1, 0.1),
        (0.5, 0.5, float("-inf"), 0.1),
        (0.5, 0.5, 0.1, float("nan")),
        ("0.5", 0.5, 0.1, 0.1),
        (0.5, None, 0.1, 0.1),
        (0.5, 0.5, complex(1, 0), 0.1),
    ],
)
def test_filter_nonfinite_or_typed_inputs(u, v, du, dv):
    f = TexFilter()
    tex = [[0.0, 1.0], [1.0, 0.0]]
    with pytest.raises(ValueError):
        f.sample(tex, u, v, du, dv)


def test_filter_bad_wrap_mode():
    with pytest.raises(ValueError):
        TexFilter(wrap="mirror")
    f = TexFilter()
    tex = [[0.0, 1.0], [1.0, 0.0]]
    with pytest.raises(ValueError):
        f.sample(tex, 0.5, 0.5, 0.1, 0.1, wrap="bogus")


# ----------------------------------------------------------------------
# 7. 确定性、类型与并发安全
# ----------------------------------------------------------------------
def test_filter_deterministic_and_float():
    f = TexFilter()
    tex = _make_textures()[0]
    a = f.sample(tex, 0.3, 0.3, 0.1, 0.1)
    b = f.sample(tex, 0.3, 0.3, 0.1, 0.1)
    assert a == b
    assert isinstance(a, float)
    # 零梯度退化为点采样，仍需确定性。
    assert f.sample(tex, 0.5, 0.5, 0.0, 0.0) == f.sample(tex, 0.5, 0.5, 0.0, 0.0)


def test_filter_corner_exact_value():
    f = TexFilter()
    tex = [[0.0, 1.0], [1.0, 0.0]]
    assert f.sample(tex, 0.0, 0.0, 0.01, 0.01) == 0.0


def test_filter_thread_safety():
    f = TexFilter()
    tex = _make_textures()[0]
    rng = random.Random(5)
    queries = [
        (rng.uniform(0.05, 0.95), rng.uniform(0.05, 0.95),
         rng.uniform(0.005, 0.05), rng.uniform(0.005, 0.05),
         rng.choice(["clamp", "wrap"]))
        for _ in range(200)
    ]
    expected = [f.sample(tex, u, v, du, dv, wrap=m) for u, v, du, dv, m in queries]
    results = [None] * len(queries)
    errors = []

    def worker(start, step):
        try:
            for i in range(start, len(queries), step):
                u, v, du, dv, m = queries[i]
                results[i] = f.sample(tex, u, v, du, dv, wrap=m)
        except Exception as exc:  # pragma: no cover - 仅用于失败上报
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t, 4)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert results == expected
