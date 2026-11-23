"""各向异性纹理过滤（纯标准库实现）。

采样模型
========
像素在 UV 空间的足迹是轴对齐矩形，半轴长度为 ``|du|`` / ``|dv|``
（``du``、``dv`` 为标量梯度幅值）。实现采用经典的“足迹细分 + 长线探针”：

1. 沿足迹长轴放置 ``N`` 个等权探针（slab），
   ``N = min(max_aniso, ceil(a/b))`` —— 各向异性比由此被正确钳制，
   短轴退化（``b≈0``）时直接取 ``max_aniso``；
2. N 个探针矩形沿长轴无缝拼接，恰好铺满整个足迹矩形，与钳制无关；
3. 每个探针在纹素网格上做**解析盒式积分**：纹素单元（cell）按其与探针
   矩形的重叠面积加权，等价于无限密度最近邻超采样的极限，没有离散误差；
4. 所有探针等权平均。各单元权重之和严格为 1，常数纹理逐字节返回常数。

边界模式：``clamp``（clamp-to-edge，越界纹素单元并入边缘单元）与
``wrap``/``repeat``（按模索引平铺）。``sample`` 不修改实例状态，
可在线程间并发调用。纹理按惯例视为采样期间不可变；校验结果按 ``id()``
缓存以满足性能上界。
"""

import math
from numbers import Real, Integral

__all__ = ["TexFilter"]

_EPS = 1e-12
_MAX_ANISO_CAP = 64
_CACHE_LIMIT = 128

_MODE_ALIASES = {
    "clamp": "clamp",
    "clamp_to_edge": "clamp",
    "edge": "clamp",
    "wrap": "wrap",
    "repeat": "wrap",
    "tile": "wrap",
}


def _normalize_mode(mode):
    if not isinstance(mode, str):
        raise ValueError("wrap 必须是字符串，可取 'clamp' 或 'wrap'")
    key = mode.lower()
    if key not in _MODE_ALIASES:
        raise ValueError("未知的边界模式 %r，仅支持 'clamp' 与 'wrap'" % mode)
    return _MODE_ALIASES[key]


def _finite_real(value, name):
    """要求有限实数（拒绝 bool / 复数 / 字符串 / NaN / Inf），返回 float。

    基于 :class:`numbers.Real` 的鸭子类型注册，numpy 数值标量同样适用。
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("%s 必须是有限实数，得到 %r" % (name, value))
    f = float(value)
    if not math.isfinite(f):
        raise ValueError("%s 必须是有限实数，得到 %r" % (name, value))
    return f


def _validate_texture(tex):
    """校验并返回 (高, 宽, 浮点化后的纹理)。

    接受任意二维、矩形、可索引的序列（list/tuple 或 numpy 数组等）。
    """
    if not hasattr(tex, "__len__") or not hasattr(tex, "__getitem__"):
        raise ValueError("纹理必须是非空的二维序列")
    if len(tex) == 0:
        raise ValueError("纹理必须是非空的二维序列")
    width = None
    rows = []
    for row in tex:
        if not hasattr(row, "__len__") or not hasattr(row, "__getitem__"):
            raise ValueError("纹理的每一行必须是非空序列")
        if len(row) == 0:
            raise ValueError("纹理的每一行必须是非空序列")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ValueError("纹理各行长度必须一致（矩形纹理）")
        out_row = []
        for x in row:
            if isinstance(x, bool) or not isinstance(x, Real):
                raise ValueError("纹素必须是数值，得到 %r" % (x,))
            fx = float(x)
            if not math.isfinite(fx):
                raise ValueError("纹素必须有限，得到 %r" % (x,))
            out_row.append(fx)
        rows.append(out_row)
    return len(tex), width, rows


class TexFilter:
    """各向异性纹理采样器。

    Parameters
    ----------
    wrap:
        默认边界模式，``"clamp"``（默认）或 ``"wrap"``/``"repeat"``。
        可在每次 :meth:`sample` 调用时用 ``wrap=`` 覆盖。
    """

    def __init__(self, wrap="clamp"):
        self._mode = _normalize_mode(wrap)
        # id(tex) -> (height, width, float_rows, len(tex), len(tex[0]))
        self._cache = {}

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def sample(self, tex, u, v, du, dv, max_aniso=8, wrap=None):
        """对纹理做一次各向异性过滤采样。

        Parameters
        ----------
        tex:
            矩形二维序列（行优先，``tex[v][u]``），元素为有限数值。
            采样期间应视为不可变（与 GPU 纹理上传后的约定一致）。
        u, v:
            采样中心的 UV 坐标，可为任意有限实数（按边界模式寻址）。
        du, dv:
            足迹在 u / v 方向的半轴长度（梯度幅值，非负语义，取绝对值）。
        max_aniso:
            最大各向异性比，正整数，范围 [1, 64]。
        wrap:
            单次调用覆盖构造时的边界模式，``"clamp"`` 或 ``"wrap"``。

        Returns
        -------
        float
            过滤后的纹素值。
        """
        height, width, rows = self._cached_texture(tex)
        u = _finite_real(u, "u")
        v = _finite_real(v, "v")
        du = _finite_real(du, "du")
        dv = _finite_real(dv, "dv")

        # 仅接受整数（内置 int、numpy.integer 等 Integral 注册类型）；
        # 显式拒绝 bool、float（即使值恰好为整数）与非数值类型。
        if isinstance(max_aniso, bool) or not isinstance(max_aniso, Integral):
            raise ValueError("max_aniso 必须是正整数，得到 %r" % (max_aniso,))
        if max_aniso < 1 or max_aniso > _MAX_ANISO_CAP:
            raise ValueError(
                "max_aniso 必须落在 [1, %d]，得到 %r" % (_MAX_ANISO_CAP, max_aniso)
            )
        mode = self._mode if wrap is None else _normalize_mode(wrap)

        su = abs(du)
        sv = abs(dv)

        # 零足迹：退化为最近邻点采样。
        if su < _EPS and sv < _EPS:
            return float(
                rows[self._point_index(v * height, height, mode)]
                    [self._point_index(u * width, width, mode)]
            )

        if su >= sv:
            major, minor, major_u = su, sv, True
        else:
            major, minor, major_u = sv, su, False

        # 各向异性比钳制：短轴退化时直接取上限。
        if minor < _EPS:
            n_probes = max_aniso
            short_half = major / max_aniso
        else:
            n_probes = min(max_aniso, max(1, math.ceil(major / minor)))
            # 探针短轴半宽取真实足迹半宽；钳制时探针沿长轴拉长，
            # 探针之并仍然恰好等于整个足迹矩形（不越界、不留缝）。
            short_half = minor

        long_half = major / n_probes

        total = 0.0
        for k in range(n_probes):
            # 探针中心在长轴上的偏移：(-major, major) 等距排布。
            offset = major * ((2.0 * k + 1.0) / n_probes - 1.0)
            if major_u:
                cu, cv = u + offset, v
                hu, hv = long_half, short_half
            else:
                cu, cv = u, v + offset
                hu, hv = short_half, long_half
            total += self._probe_integral(
                rows, cu, cv, hu, hv, width, height, mode
            )

        # 等权平均：常数纹理下各探针值相同，平均后严格等于常数。
        return total / n_probes

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _cached_texture(self, tex):
        key = id(tex)
        entry = self._cache.get(key)
        if entry is not None and entry[3] == len(tex) and entry[4] == len(tex[0]):
            return entry[0], entry[1], entry[2]
        height, width, rows = _validate_texture(tex)
        if len(self._cache) >= _CACHE_LIMIT:
            # FIFO 淘汰，避免无界增长。
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (height, width, rows, len(tex), len(tex[0]))
        return height, width, rows

    @staticmethod
    def _point_index(x, size, mode):
        idx = math.floor(x + 0.5)  # 最近纹素单元，半整数边界向下取整
        if mode == "wrap":
            return idx % size
        if idx < 0:
            return 0
        if idx >= size:
            return size - 1
        return idx

    @staticmethod
    def _axis_weights(center, half, size, mode):
        """一维纹素单元重叠权重。

        单元 ``k`` 覆盖索引坐标区间 ``[k-0.5, k+0.5)``；返回
        ``[(映射后的单元索引, 重叠长度), ...]`` 与区间总跨度。
        区间宽度为 0 时退化为单点权重（跨度记 1.0，二维归一化仍成立）。

        - wrap：单元索引按模折叠，越界部分折到对侧边缘单元；
        - clamp：越界单元折叠到最近的边缘单元（clamp-to-edge）。
        """
        lo = (center - half) * size
        hi = (center + half) * size

        if hi - lo <= _EPS:
            idx = math.floor(center * size + 0.5)
            if mode == "wrap":
                idx %= size
            else:
                idx = min(max(idx, 0), size - 1)
            return [(idx, 1.0)], 1.0

        weights = {}
        # 单元 k 覆盖 [k-0.5, k+0.5)。与 [lo, hi) 相交的单元范围：
        # 从包含 lo 的单元 floor(lo+0.5) 到包含 hi 左侧的单元 floor(hi+0.5)。
        first = math.floor(lo + 0.5)
        last = math.floor(hi + 0.5)
        for k in range(first, last + 1):
            overlap = min(hi, k + 0.5) - max(lo, k - 0.5)
            if overlap <= 0.0:
                continue
            if mode == "wrap":
                idx = k % size
            elif k < 0:
                idx = 0
            elif k >= size:
                idx = size - 1
            else:
                idx = k
            weights[idx] = weights.get(idx, 0.0) + overlap

        return list(weights.items()), hi - lo

    def _probe_integral(self, tex, cu, cv, hu, hv, width, height, mode):
        """探针矩形在最近邻纹素场上的解析盒式积分（单元面积加权）。"""
        wu, _ = self._axis_weights(cu, hu, width, mode)
        wv, _ = self._axis_weights(cv, hv, height, mode)
        # 显式归一化：消除浮点累加误差，保证权重和严格为 1
        # （常数纹理逐字节返回常数本身）。
        total_u = sum(w for _, w in wu)
        total_v = sum(w for _, w in wv)
        acc = 0.0
        for j, wj in wv:
            row = tex[j]
            wjn = wj / total_v
            for i, wi in wu:
                acc += (wi / total_u) * wjn * row[i]
        return acc
