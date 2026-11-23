"""tilemapgen 约束自测：连通性、边界、密度、可复现、报错分类、性能、并发。"""

import concurrent.futures
import math
import time

import pytest

import tilemapgen
from tilemapgen import core


def _bfs_components(grid):
    h = len(grid)
    w = len(grid[0]) if h else 0
    seen = [[False] * w for _ in range(h)]
    sizes = []
    for sy in range(h):
        for sx in range(w):
            if not grid[sy][sx] or seen[sy][sx]:
                continue
            stack = [(sx, sy)]
            seen[sy][sx] = True
            size = 0
            while stack:
                x, y = stack.pop()
                size += 1
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and grid[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            sizes.append(size)
    return sorted(sizes, reverse=True)


def _land(grid):
    return sum(1 for row in grid for v in row if v)


def _boundary_is_water(grid):
    h = len(grid)
    w = len(grid[0])
    return (
        not any(grid[0])
        and not any(grid[-1])
        and all(row[0] == 0 and row[-1] == 0 for row in grid)
    )


@pytest.mark.parametrize("size", [(16, 16), (32, 24), (64, 64), (128, 128)])
@pytest.mark.parametrize("density", [0.3, 0.5, 0.7])
def test_connected_closed_and_density(size, density):
    w, h = size
    m = tilemapgen.MapGen(1234, density)
    grid = m.generate(w, h)
    assert len(grid) == h and all(len(row) == w for row in grid)
    assert set(v for row in grid for v in row) <= {0, 1}
    sizes = _bfs_components(grid)
    assert len(sizes) == 1, "map must be fully connected"
    assert m.is_connected() is True
    assert _boundary_is_water(grid)
    assert m.boundary_closed is True
    ratio = _land(grid) / (w * h)
    assert abs(ratio - density) <= 0.10 * density


def test_component_stats_reported():
    m = tilemapgen.MapGen(7, 0.5)
    grid = m.generate(48, 40)
    sizes = _bfs_components(grid)
    assert m.component_count == 1
    assert m.component_count() == 1
    assert m.component_sizes == sizes
    assert m.largest_component_ratio == pytest.approx(sizes[0] / _land(grid))
    assert m.stats["components"] == 1
    assert m.stats()["largest_component"] == sizes[0]
    assert m.analyze().component_count == 1


def test_reproducible_same_seed():
    a = tilemapgen.MapGen(42, 0.55).generate(40, 30)
    b = tilemapgen.MapGen(42, 0.55).generate(40, 30)
    assert a == b
    assert tilemapgen.MapGen("seed-a", 0.45).generate(24, 24) == (
        tilemapgen.MapGen("seed-a", 0.45).generate(24, 24)
    )


def test_different_seed_differs():
    assert tilemapgen.MapGen(1, 0.5).generate(32, 32) != (
        tilemapgen.MapGen(2, 0.5).generate(32, 32)
    )


def test_invalid_size_errors_are_distinct():
    m = tilemapgen.MapGen(1, 0.5)
    for bad in (0, -3):
        with pytest.raises(core.InvalidSizeError):
            m.generate(bad, 8)
        with pytest.raises(core.InvalidSizeError):
            m.generate(8, bad)
    with pytest.raises(core.InvalidSizeError):
        m.generate(2.5, 8)
    with pytest.raises(core.InvalidSizeError):
        m.generate("8", 8)
    with pytest.raises(core.InvalidSizeError):
        m.generate(10 ** 9, 8)
    # 封闭边界需要内部陆地空间，2 及以下视为非法尺寸。
    with pytest.raises(core.InvalidSizeError):
        m.generate(2, 8)


def test_invalid_density_errors_are_distinct():
    for bad in (0.0, 1.0, -0.1, 1.5, 2):
        with pytest.raises(core.InvalidDensityError):
            tilemapgen.MapGen(1, bad)
    with pytest.raises(core.InvalidDensityError):
        tilemapgen.MapGen(1, "0.5")


def test_non_finite_inputs_are_distinctly_classified():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(core.NonFiniteInputError):
            tilemapgen.MapGen(1, bad)
        with pytest.raises(core.NonFiniteInputError):
            tilemapgen.MapGen(bad, 0.5)
        with pytest.raises(core.NonFiniteInputError):
            tilemapgen.MapGen(1, 0.5).generate(bad, 8)
        with pytest.raises(core.NonFiniteInputError):
            tilemapgen.MapGen(1, 0.5).generate(8, bad)
    assert issubclass(core.NonFiniteInputError, ValueError)
    assert not issubclass(core.NonFiniteInputError, core.InvalidSizeError)
    assert not issubclass(core.NonFiniteInputError, core.InvalidDensityError)


def test_query_before_generate_raises():
    with pytest.raises(ValueError):
        tilemapgen.MapGen(1, 0.5).is_connected()


def test_performance_128x128():
    m = tilemapgen.MapGen(99, 0.5)
    start = time.perf_counter()
    m.generate(128, 128)
    elapsed = time.perf_counter() - start
    assert elapsed <= 0.5, f"128x128 took {elapsed * 1e3:.1f} ms"
    assert m.is_connected() is True
    assert abs(m.land_ratio - 0.5) <= 0.05


def test_concurrent_generation_is_safe():
    def run(seed):
        m = tilemapgen.MapGen(seed, 0.5)
        grid = m.generate(64, 64)
        return m.is_connected(), m.component_count, grid

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(16)))
    for connected, count, grid in results:
        assert connected is True and count == 1
        assert _boundary_is_water(grid)
    # 同种子并发结果与串行一致
    serial = tilemapgen.MapGen(3, 0.5).generate(64, 64)
    assert tilemapgen.MapGen(3, 0.5).generate(64, 64) == serial


def test_shared_instance_concurrent_queries():
    m = tilemapgen.MapGen(5, 0.5)
    m.generate(64, 64)

    def query(_):
        return m.is_connected(), m.component_count, len(m.stats["component_sizes"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for connected, count, comps in pool.map(query, range(64)):
            assert connected is True and count == 1 and comps == 1
