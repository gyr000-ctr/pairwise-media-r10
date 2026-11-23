"""glyphatlas：字形图集矩形打包。

对外 API::

    atlas = Atlas()
    rects = atlas.pack(sizes, width, height)   # [(x, y, w, h), ...]
    rate = atlas.fill_rate()                   # 已用面积 / 图集面积

打包结果是确定性的：相同输入总是得到完全相同的矩形序列。所有矩形均为
轴对齐整数矩形，互不重叠且完整落在图集内部。

算法分两级：

1. shelf（货架）首次适配，按高度降序放置。货架剩余宽度用线段树维护，
   单次查找 O(log n)，整体 O(n log n)。
2. 货架放不下时（且规模可控），用 guillotine 最佳面积适配回退。

两级都失败才报 ``CannotFitError``。
"""

from __future__ import annotations

import math
import operator
import threading

__all__ = [
    "Atlas",
    "AtlasError",
    "InvalidInputError",
    "InvalidTypeError",
    "NonFiniteInputError",
    "GlyphTooLargeError",
    "CannotFitError",
]


class AtlasError(ValueError):
    """图集相关错误的基类（可被 ``except ValueError`` 捕获）。"""


class InvalidTypeError(AtlasError, TypeError):
    """输入类型非法。同时是 ``ValueError`` 与 ``TypeError``。"""


class InvalidInputError(AtlasError):
    """数值非法（非正、总面积为负等）。"""


class NonFiniteInputError(InvalidInputError):
    """输入包含 NaN / 正负无穷。"""


class GlyphTooLargeError(InvalidInputError):
    """单个字形的宽或高超过图集尺寸。"""


class CannotFitError(InvalidInputError):
    """所有字形总面积不超过图集，但布局失败。"""


def _coerce_int(value, name):
    """把尺寸参数规范成 Python ``int``。

    - ``bool`` 不是尺寸，报类型错误；
    - 浮点数：非有限值（NaN / ±inf）报 ``NonFiniteInputError``，非整数值
      报类型错误，整数值（如 ``8.0``）接受；
    - 其余非整型对象一律报类型错误。
    """
    if isinstance(value, bool):
        raise InvalidTypeError("%s must be an integer, not bool" % name)

    if isinstance(value, float):
        if not math.isfinite(value):
            raise NonFiniteInputError("%s must be finite, got %r" % (name, value))
        if value.is_integer():
            return int(value)
        raise InvalidInputError("%s must be a whole number, got %r" % (name, value))

    try:
        return operator.index(value)
    except TypeError:
        raise InvalidTypeError(
            "%s must be an integer, got %r" % (name, value)
        ) from None


def _coerce_positive_int(value, name):
    number = _coerce_int(value, name)
    if number <= 0:
        raise InvalidInputError("%s must be positive, got %d" % (name, number))
    return number


def _is_text(value):
    return isinstance(value, (str, bytes, bytearray))


def _coerce_sizes(sizes):
    """校验并规范化字形尺寸列表，返回 ``[(w, h), ...]``。"""
    if sizes is None or _is_text(sizes):
        raise InvalidTypeError("sizes must be an iterable of (width, height) pairs")

    try:
        items = list(sizes)
    except TypeError:
        raise InvalidTypeError(
            "sizes must be an iterable of (width, height) pairs"
        ) from None

    result = []
    for index, item in enumerate(items):
        if _is_text(item):
            raise InvalidTypeError(
                "sizes[%d] must be a (width, height) pair" % index
            )
        try:
            pair = tuple(item)
        except TypeError:
            raise InvalidTypeError(
                "sizes[%d] must be a (width, height) pair" % index
            ) from None
        if len(pair) != 2:
            raise InvalidInputError(
                "sizes[%d] must contain exactly 2 values, got %d"
                % (index, len(pair))
            )
        w = _coerce_positive_int(pair[0], "sizes[%d].width" % index)
        h = _coerce_positive_int(pair[1], "sizes[%d].height" % index)
        result.append((w, h))
    return result


class Atlas:
    """固定尺寸图集上的矩形打包器。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._width = 0
        self._height = 0
        self._used_area = 0

    def pack(self, sizes, width, height):
        """把 ``sizes`` 中的矩形打包进 ``width x height`` 图集。

        返回与输入顺序一致的 ``[(x, y, w, h), ...]``，坐标原点在左上角。
        出错时抛出 ``TypeError``（类型非法）或 ``ValueError`` 的子类
        （数值非法、非有限值、单字形过大、无法布局）。
        """
        atlas_w = _coerce_positive_int(width, "width")
        atlas_h = _coerce_positive_int(height, "height")
        glyphs = _coerce_sizes(sizes)

        # 单个字形必须先能放进图集。
        for index, (w, h) in enumerate(glyphs):
            if w > atlas_w or h > atlas_h:
                raise GlyphTooLargeError(
                    "glyph %d is %dx%d, larger than atlas %dx%d"
                    % (index, w, h, atlas_w, atlas_h)
                )

        if not glyphs:
            placements = []
        else:
            capacity = atlas_w * atlas_h
            total_area = sum(w * h for w, h in glyphs)
            if total_area > capacity:
                raise CannotFitError(
                    "total glyph area %d exceeds atlas area %d"
                    % (total_area, capacity)
                )

            placements = self._pack_shelves(glyphs, atlas_w, atlas_h)
            if placements is None:
                placements = self._pack_guillotine(glyphs, atlas_w, atlas_h)
            if placements is None:
                raise CannotFitError(
                    "glyphs do not fit into atlas %dx%d" % (atlas_w, atlas_h)
                )

        used = sum(w * h for _, _, w, h in placements)

        with self._lock:
            self._width = atlas_w
            self._height = atlas_h
            self._used_area = used

        # 返回新列表，调用方修改不会影响内部状态。
        return list(placements)

    def fill_rate(self):
        """返回最近一次成功打包的面积利用率，取值在 ``[0, 1]``。"""
        with self._lock:
            area = self._width * self._height
            if area <= 0:
                return 0.0
            rate = self._used_area / area
            if rate < 0.0:
                return 0.0
            if rate > 1.0:
                return 1.0
            return rate

    # ------------------------------------------------------------------
    # 打包算法
    # ------------------------------------------------------------------
    @staticmethod
    def _pack_shelves(glyphs, width, height):
        """按高度降序做 shelf 首次适配，成功返回坐标列表，否则 ``None``。

        高度降序保证后放入的字形一定不高于任意已有货架，因此首个剩余宽度
        足够的货架一定可放。线段树维护各货架剩余宽度的最大值，用于
        O(log n) 查找，整体 O(n log n)。
        """
        count = len(glyphs)
        order = sorted(
            range(count), key=lambda i: (-glyphs[i][1], -glyphs[i][0], i)
        )

        size = 1
        while size < count:
            size <<= 1
        tree = [-1] * (2 * size)

        def update(index, value):
            node = size + index
            tree[node] = value
            node >>= 1
            while node:
                left = tree[node << 1]
                right = tree[(node << 1) | 1]
                best = left if left >= right else right
                if tree[node] == best:
                    break
                tree[node] = best
                node >>= 1

        def first_fit(need):
            if tree[1] < need:
                return -1
            node = 1
            while node < size:
                node <<= 1
                if tree[node] < need:
                    node += 1
            return node - size

        shelves = []  # [y, shelf_height, remaining_width, cursor_x]
        placements = [None] * count
        next_y = 0

        for glyph_index in order:
            w, h = glyphs[glyph_index]
            shelf_index = first_fit(w)
            if 0 <= shelf_index < len(shelves):
                y, shelf_h, remaining, cursor = shelves[shelf_index]
                placements[glyph_index] = (cursor, y, w, h)
                cursor += w
                remaining -= w
                shelves[shelf_index] = [y, shelf_h, remaining, cursor]
                update(shelf_index, remaining)
            else:
                if next_y + h > height:
                    return None
                placements[glyph_index] = (0, next_y, w, h)
                shelves.append([next_y, h, width - w, w])
                update(len(shelves) - 1, width - w)
                next_y += h

        return placements

    @staticmethod
    def _pack_guillotine(glyphs, width, height):
        """Guillotine 最佳面积适配回退。

        自由矩形始终互不重叠；每次把选中自由矩形按 guillotine 切成两块。
        切分方向取「沿较短剩余边切」，这样不会把空间切成细长条，实测比
        「保留最大块」的切法成功率更高。复杂度 O(n * |free|)，仅用于
        shelf 失败且规模可控的输入，避免拖慢大输入。
        """
        count = len(glyphs)
        # 大规模输入不再做 O(n * |free|) 回退。
        if count > 4000:
            return None

        order = sorted(
            range(count),
            key=lambda i: (
                -(glyphs[i][0] * glyphs[i][1]),
                -max(glyphs[i]),
                -min(glyphs[i]),
                i,
            ),
        )
        placements = [None] * count
        free = [(0, 0, width, height)]

        for glyph_index in order:
            w, h = glyphs[glyph_index]
            best = -1
            best_key = None
            for fi, (fx, fy, fw, fh) in enumerate(free):
                if w <= fw and h <= fh:
                    leftover_w = fw - w
                    leftover_h = fh - h
                    key = (
                        fw * fh - w * h,              # 最佳面积适配
                        min(leftover_w, leftover_h),  # 少留细缝
                        max(leftover_w, leftover_h),
                        fy,
                        fx,
                    )
                    if best_key is None or key < best_key:
                        best_key = key
                        best = fi
            if best < 0:
                return None

            fx, fy, fw, fh = free.pop(best)
            placements[glyph_index] = (fx, fy, w, h)

            leftover_w = fw - w
            leftover_h = fh - h
            horizontal = ((fx + w, fy, leftover_w, h),
                          (fx, fy + h, fw, leftover_h))
            vertical = ((fx + w, fy, leftover_w, fh),
                        (fx, fy + h, w, leftover_h))
            # 剩余宽度更窄时水平切（下块保持整宽），否则垂直切。
            for rect in (horizontal if leftover_w <= leftover_h else vertical):
                if rect[2] and rect[3]:
                    free.append(rect)

        return placements
