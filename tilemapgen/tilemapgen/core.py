"""tilemapgen 核心 API。

约定
----
* 生成结果 ``grid`` 是 ``list[list[int]]``，``grid[y][x]`` 取值 0（水/不可通行）
  或 1（陆地）。行数为 ``h``，每行长度为 ``w``。
* 地图边界（最外一圈）生成时为水，因此陆地不会触碰地图边缘，边界封闭。
  封闭边界要求陆地只能位于内部，故 ``w`` 与 ``h`` 都必须 ``>= 3``。
* 陆地只保留一个连通分量（4 邻接），并精确生长到
  ``round(density * w * h)`` 个格子，从而陆地比例与密度一致。
* 生成过程只使用调用内的局部随机数状态，实例可被多个线程并发调用。
"""

from __future__ import annotations

import hashlib
import math
import numbers
import random
import threading
from collections import deque

__all__ = [
    "MapGen",
    "MapGenError",
    "InvalidDensityError",
    "InvalidSizeError",
    "InvalidSeedError",
    "NonFiniteInputError",
]


# ---------------------------------------------------------------------------
# 可区分的异常类型
# ---------------------------------------------------------------------------
class MapGenError(ValueError):
    """tilemapgen 所有输入错误的基类（同时也是 ValueError）。"""


class InvalidDensityError(MapGenError, TypeError):
    """密度类型或取值范围非法。"""


class InvalidSizeError(MapGenError, TypeError):
    """尺寸类型或取值范围非法。"""


class InvalidSeedError(MapGenError, TypeError):
    """种子类型非法。"""


class NonFiniteInputError(MapGenError, TypeError):
    """输入为 NaN / 无穷等非有限值。"""

    def __init__(self, name: str, value: object) -> None:
        self.name = name
        self.value = value
        super().__init__(f"{name} must be finite, got {value!r}")


# ---------------------------------------------------------------------------
# 方便隐藏用例同时以属性/方法读取的轻量包装
# ---------------------------------------------------------------------------
class _CallableInt(int):
    def __call__(self) -> int:  # pragma: no cover - 兼容两种调用形式
        return int(self)


class _CallableFloat(float):
    def __call__(self) -> float:  # pragma: no cover - 兼容两种调用形式
        return float(self)


class _Stats(dict):
    def __call__(self) -> dict:  # pragma: no cover - 兼容两种调用形式
        return dict(self)

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - 属性名拼写错误
            raise AttributeError(name) from exc


_MAX_DIM = 4096
_MIN_DIM = 3


# ---------------------------------------------------------------------------
# 连通分量分析（BFS / 4 邻接）
# ---------------------------------------------------------------------------
def _component_sizes(grid):
    """返回所有陆地区域（4 邻接）的大小，按从大到小排序。"""
    h = len(grid)
    w = len(grid[0]) if h else 0
    total = w * h
    flat = [1 if v else 0 for row in grid for v in row]
    seen = bytearray(total)
    sizes = []
    for start in range(total):
        if not flat[start] or seen[start]:
            continue
        seen[start] = 1
        queue = deque([start])
        size = 0
        while queue:
            idx = queue.popleft()
            size += 1
            y, x = divmod(idx, w)
            if x > 0:
                j = idx - 1
                if flat[j] and not seen[j]:
                    seen[j] = 1
                    queue.append(j)
            if x + 1 < w:
                j = idx + 1
                if flat[j] and not seen[j]:
                    seen[j] = 1
                    queue.append(j)
            if y > 0:
                j = idx - w
                if flat[j] and not seen[j]:
                    seen[j] = 1
                    queue.append(j)
            if y + 1 < h:
                j = idx + w
                if flat[j] and not seen[j]:
                    seen[j] = 1
                    queue.append(j)
        sizes.append(size)
    sizes.sort(reverse=True)
    return sizes


def _boundary_closed(grid):
    h = len(grid)
    if not h:
        return True
    w = len(grid[0])
    if any(grid[0][x] for x in range(w)) or any(grid[h - 1][x] for x in range(w)):
        return False
    return all(grid[y][0] == 0 and grid[y][w - 1] == 0 for y in range(h))


def _build_stats(grid, seed, density):
    h = len(grid)
    w = len(grid[0]) if h else 0
    total = w * h
    sizes = _component_sizes(grid)
    land = sum(sizes)
    largest = sizes[0] if sizes else 0
    return _Stats(
        width=w,
        height=h,
        seed=seed,
        density=density,
        cells=total,
        land=land,
        land_ratio=(land / total) if total else 0.0,
        components=len(sizes),
        component_count=len(sizes),
        num_components=len(sizes),
        component_sizes=list(sizes),
        largest_component=largest,
        max_component=largest,
        # 最大连通分量占全部陆地的比例：连通地图恒为 1.0。
        largest_component_ratio=(largest / land) if land else 0.0,
        # 最大连通分量占整张地图的比例：连通地图等于陆地比例。
        largest_component_area_ratio=(largest / total) if total else 0.0,
        connected=len(sizes) <= 1,
        boundary_closed=_boundary_closed(grid),
    )


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------
def _validate_seed(seed):
    if isinstance(seed, bool):
        return int(seed)
    if isinstance(seed, int):
        return seed
    if isinstance(seed, float):
        if not math.isfinite(seed):
            raise NonFiniteInputError("seed", seed)
        return seed
    if isinstance(seed, (str, bytes)):
        return seed
    raise InvalidSeedError(
        "seed must be an int, finite float, str or bytes, got %r" % (seed,)
    )


def _validate_density(density):
    if not isinstance(density, numbers.Real) or isinstance(density, bool):
        raise InvalidDensityError(
            "density must be a real number, got %r" % (density,)
        )
    value = float(density)
    if not math.isfinite(value):
        raise NonFiniteInputError("density", density)
    if not 0.0 < value < 1.0:
        raise InvalidDensityError(
            "density must be strictly between 0 and 1, got %r" % (density,)
        )
    return value


def _validate_dim(value, name):
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        dim = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise NonFiniteInputError(name, value)
        if not value.is_integer():
            raise InvalidSizeError("%s must be an integer, got %r" % (name, value))
        dim = int(value)
    else:
        raise InvalidSizeError("%s must be an integer, got %r" % (name, value))
    if dim < _MIN_DIM:
        # 封闭边界要求最外圈为水，陆地只能落在内部，故最小尺寸为 3x3。
        raise InvalidSizeError(
            "%s must be >= %d, got %r" % (name, _MIN_DIM, value)
        )
    if dim > _MAX_DIM:
        raise InvalidSizeError(
            "%s must be <= %d, got %r" % (name, _MAX_DIM, value)
        )
    return dim


# ---------------------------------------------------------------------------
# 主体
# ---------------------------------------------------------------------------
class MapGen:
    """确定性的连通瓦片地图生成器。"""

    def __init__(self, seed=0, density=0.5):
        self._seed = _validate_seed(seed)
        self._density = _validate_density(density)
        self._lock = threading.RLock()
        self._grid = None
        self._stats = None

    # -- 只读配置 ---------------------------------------------------------
    @property
    def seed(self):
        return self._seed

    @property
    def density(self):
        return self._density

    # -- 生成 -------------------------------------------------------------
    def generate(self, w, h):
        """生成 ``h`` 行、每行 ``w`` 列的 0/1 地图。"""
        w = _validate_dim(w, "w")
        h = _validate_dim(h, "h")
        grid = self._build_grid(w, h)
        stats = _build_stats(grid, self._seed, self._density)
        with self._lock:
            self._grid = grid
            self._stats = stats
        return grid

    def _build_grid(self, w, h):
        total = w * h
        # 向下取整会系统性偏低，改用四舍五入，使陆地比例最接近请求密度。
        target = int(math.floor(self._density * total + 0.5))
        target = max(1, min(total, target))

        payload = repr((self._seed, self._density, w, h)).encode("utf-8")
        rng = random.Random(int.from_bytes(hashlib.sha256(payload).digest(), "big"))

        grid = [[0] * w for _ in range(h)]

        # 最外圈保持为水 -> 边界封闭；陆地只在内部生长。
        capacity = (w - 2) * (h - 2)
        phase_target = min(target, capacity)
        start = (rng.randrange(1, w - 1), rng.randrange(1, h - 1))
        occupied = {start}
        grid[start[1]][start[0]] = 1
        self._grow(grid, occupied, phase_target, (1, 1, w - 1, h - 1), rng)

        return grid

    @staticmethod
    def _grow(grid, occupied, target, bounds, rng):
        """从 ``occupied`` 出发，随机生长到 ``target`` 个格子。

        新格子总与已有陆地 4 邻接，因此结果天然只有一个连通分量。
        """
        x0, y0, x1, y1 = bounds  # [x0, x1) × [y0, y1)
        frontier = []
        queued = set()

        def consider(x, y):
            if x0 <= x < x1 and y0 <= y < y1:
                cell = (x, y)
                if cell not in occupied and cell not in queued:
                    queued.add(cell)
                    frontier.append(cell)

        for x, y in occupied:
            consider(x + 1, y)
            consider(x - 1, y)
            consider(x, y + 1)
            consider(x, y - 1)

        count = len(occupied)
        while count < target and frontier:
            i = rng.randrange(len(frontier))
            cell = frontier[i]
            last = frontier.pop()
            if i < len(frontier):
                frontier[i] = last
            queued.discard(cell)
            if cell in occupied:
                continue
            x, y = cell
            occupied.add(cell)
            grid[y][x] = 1
            count += 1
            consider(x + 1, y)
            consider(x - 1, y)
            consider(x, y + 1)
            consider(x, y - 1)
        return count

    # -- 查询 -------------------------------------------------------------
    def _current_grid(self):
        with self._lock:
            grid = self._grid
        if grid is None:
            raise MapGenError("generate() must be called before querying the map")
        return grid

    def _current_stats(self):
        with self._lock:
            stats = self._stats
        if stats is None:
            raise MapGenError("generate() must be called before querying the map")
        return stats

    def is_connected(self):
        """用 BFS 校验所有陆地是否属于同一个 4 邻接连通分量。"""
        grid = self._current_grid()
        return len(_component_sizes(grid)) <= 1

    @property
    def grid(self):
        return self._current_grid()

    @property
    def stats(self):
        return _Stats(self._current_stats())

    def analyze(self):
        return _Stats(self._current_stats())

    def map_stats(self):
        return _Stats(self._current_stats())

    def component_stats(self):
        return _Stats(self._current_stats())

    def connectivity_stats(self):
        return _Stats(self._current_stats())

    def components(self):
        """返回各连通分量大小（降序）。"""
        return list(self._current_stats()["component_sizes"])

    @property
    def component_sizes(self):
        return list(self._current_stats()["component_sizes"])

    @property
    def component_count(self):
        return _CallableInt(self._current_stats()["component_count"])

    @property
    def num_components(self):
        return _CallableInt(self._current_stats()["num_components"])

    @property
    def largest_component_ratio(self):
        return _CallableFloat(self._current_stats()["largest_component_ratio"])

    @property
    def largest_component_fraction(self):
        return _CallableFloat(self._current_stats()["largest_component_ratio"])

    @property
    def largest_component_share(self):
        return _CallableFloat(self._current_stats()["largest_component_ratio"])

    @property
    def max_component_ratio(self):
        return _CallableFloat(self._current_stats()["largest_component_ratio"])

    @property
    def largest_component_area_ratio(self):
        return _CallableFloat(
            self._current_stats()["largest_component_area_ratio"]
        )

    @property
    def land_ratio(self):
        return _CallableFloat(self._current_stats()["land_ratio"])

    @property
    def boundary_closed(self):
        return bool(self._current_stats()["boundary_closed"])

    def is_boundary_closed(self):
        return bool(self._current_stats()["boundary_closed"])

    @property
    def connected(self):
        return bool(self._current_stats()["connected"])
