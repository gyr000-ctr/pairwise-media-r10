"""meshweld 核心 API：顶点焊接与拓扑校验。

约定
----
* ``Weld.weld(verts, faces, eps)`` 返回 ``(verts, faces)``：

  - ``verts`` 为合并后的顶点列表 ``list[tuple[float, float, float]]``。
    每簇以一个原始顶点为代表（最小下标者），结果只取决于输入内容，与调用
    历史无关；若某坐标轴上的全局极值顶点被并入别处，代表点在该轴取极值
    坐标。因此焊接前后包围盒逐坐标严格不变。
  - ``faces`` 为索引重映射后的三角形列表 ``list[tuple[int, int, int]]``，
    保持输入朝向；焊接后退化（三索引有重复）或重复（忽略顶点顺序与朝向）
    的三角形被剔除，其余顺序与输入一致。
* ``Weld.nonmanifold(faces)`` 返回被 3 个及以上三角形共享的无向边列表
  ``[(a, b), ...]``，``a < b``，按边排序。

错误分类
--------
* ``ValueError``：语义非法——``eps`` 非正或非有限、顶点为空、坐标非有限、
  坐标维数不是 3、索引非整数/越界。
* ``TypeError``：类型非法——容器不是可迭代序列、坐标为字符串、索引为布尔值等。

实现
----
容差合并等价于“距离 ≤ eps 的顶点对连通，取传递闭包”，分三层完成：

1. 精确格键：以 ``as_integer_ratio`` 计算 ``floor(x / eps)``，无浮点舍入；
   坐标完全相同的顶点直接合并（高频路径）。
2. 格内与 13 个正向邻格（每个无序格对只处理一次）内做候选比较。候选组内
   点数多时按最长轴中位数二分，递归到小批量后两两比较；跨分区的点对只在
   分割面 ±eps 的窄带内存在，因此不会退化为全量两两比较。稠密簇（组包围
   盒对角线 ≤ eps）整组合并。
3. 跨分区合并按“连通组件”进行：一对组件只需找到一个近邻点对即可整体
   连通，找到后立即重排组件表，避免逐点比较。

类本身无可变状态，实例可跨线程共享并并发调用；代表点取簇内最小原始下标，
因此结果只取决于输入内容，与调用历史无关。
"""

from collections.abc import Mapping
from math import hypot, isfinite
from numbers import Real

__all__ = ["Weld"]

_FORWARD_NEIGHBORS = tuple(
    (dx, dy, dz)
    for dx in (-1, 0, 1)
    for dy in (-1, 0, 1)
    for dz in (-1, 0, 1)
    if (dx, dy, dz) > (0, 0, 0)
)


class Weld:
    """顶点焊接器；无可变状态，可并发使用。"""

    # ------------------------------------------------------------------ 校验
    @staticmethod
    def _check_eps(eps):
        if isinstance(eps, (bool, str, bytes, bytearray)) or not isinstance(eps, Real):
            raise TypeError("eps 必须是实数，得到 %r" % (eps,))
        value = float(eps)
        if not isfinite(value):
            raise ValueError("eps 必须是有限值，得到 %r" % (value,))
        if value <= 0.0:
            raise ValueError("eps 必须为正数，得到 %r" % (value,))
        return value

    @staticmethod
    def _as_list(obj, what):
        if isinstance(obj, (str, bytes, bytearray)):
            raise TypeError("%s 必须是序列，不能是字符串" % what)
        if isinstance(obj, Mapping):
            raise TypeError("%s 必须是序列，不能是映射" % what)
        try:
            return list(obj)
        except TypeError:
            raise TypeError("%s 必须是可迭代序列" % what) from None

    @classmethod
    def _check_verts(cls, verts):
        items = cls._as_list(verts, "verts")
        if not items:
            raise ValueError("verts 不能为空")
        pts = []
        for i, p in enumerate(items):
            q = cls._as_list(p, "第 %d 个顶点" % i)
            if len(q) != 3:
                raise ValueError(
                    "第 %d 个顶点坐标维数为 %d，应为 3" % (i, len(q))
                )
            xyz = []
            for c in q:
                if isinstance(c, (bool, str, bytes, bytearray)) or not isinstance(c, Real):
                    raise TypeError("第 %d 个顶点含非数值坐标 %r" % (i, c))
                try:
                    f = float(c)
                except OverflowError:
                    raise ValueError("第 %d 个顶点坐标超出浮点范围 %r" % (i, c)) from None
                if not isfinite(f):
                    raise ValueError("第 %d 个顶点含非有限坐标 %r" % (i, c))
                xyz.append(f)
            pts.append((xyz[0], xyz[1], xyz[2]))
        return pts

    @classmethod
    def _check_faces(cls, faces, nverts):
        items = cls._as_list(faces, "faces")
        tris = []
        for i, t in enumerate(items):
            idx = cls._as_list(t, "第 %d 个面" % i)
            if len(idx) != 3:
                raise ValueError("第 %d 个面索引数为 %d，应为 3" % (i, len(idx)))
            tri = []
            for v in idx:
                if isinstance(v, (bool, str, bytes, bytearray)) or not isinstance(v, Real):
                    raise TypeError("第 %d 个面含非整数索引 %r" % (i, v))
                try:
                    fv = float(v)
                except OverflowError:
                    raise ValueError("第 %d 个面索引超出范围 %r" % (i, v)) from None
                if not isfinite(fv):
                    raise ValueError("第 %d 个面含非有限索引 %r" % (i, v))
                k = int(fv)  # 已确认 fv 为有限值，int() 不会溢出
                if k != fv:
                    raise ValueError("第 %d 个面含非整数索引 %r" % (i, v))
                if k < 0 or k >= nverts:
                    raise ValueError(
                        "第 %d 个面索引 %d 越界（顶点数 %d）" % (i, k, nverts)
                    )
                tri.append(k)
            tris.append((tri[0], tri[1], tri[2]))
        return tris

    # ------------------------------------------------------------------ 焊接
    def weld(self, verts, faces, eps):
        """在容差 ``eps`` 内合并顶点并重映射索引，返回 ``(verts, faces)``。

        不修改入参、不保留跨调用状态，可并发调用。
        """
        eps = self._check_eps(eps)
        pts = self._check_verts(verts)
        tris = self._check_faces(faces, len(pts))

        rep = self._weld_vertices(pts, eps)

        # 代表点按原始下标升序紧凑编号，因此每个簇代表其最小下标顶点。
        remap = {}
        out_verts = []
        for i, p in enumerate(pts):
            r = rep[i]
            if r not in remap:
                remap[r] = len(out_verts)
                out_verts.append(p)
        compact = [remap[r] for r in rep]

        # 每根轴上的极值点若被并入了别的顶点，输出包围盒会收缩；让该簇在
        # 该轴沿用极值坐标，从而逐坐标严格保持焊接前的包围盒。
        for axis in range(3):
            lo = hi = 0
            for i in range(1, len(pts)):
                if pts[i][axis] < pts[lo][axis]:
                    lo = i
                if pts[i][axis] > pts[hi][axis]:
                    hi = i
            for i in (lo, hi):
                c = compact[i]
                p = pts[i]
                cur = out_verts[c]
                if axis == 0:
                    out_verts[c] = (p[0], cur[1], cur[2])
                elif axis == 1:
                    out_verts[c] = (cur[0], p[1], cur[2])
                else:
                    out_verts[c] = (cur[0], cur[1], p[2])

        seen = set()
        out_faces = []
        for a, b, c in tris:
            ia, ib, ic = compact[a], compact[b], compact[c]
            if ia == ib or ib == ic or ia == ic:
                continue  # 焊接后退化为线段或点
            key = tuple(sorted((ia, ib, ic)))  # 与朝向、起点无关
            if key in seen:
                continue  # 焊接后重复（忽略朝向）
            seen.add(key)
            out_faces.append((ia, ib, ic))

        return out_verts, out_faces

    @staticmethod
    def _weld_vertices(pts, eps):
        n = len(pts)
        eps_num, eps_den = eps.as_integer_ratio()
        eps2 = eps * eps

        parent = list(range(n))

        def find(i):
            root = i
            while parent[root] != root:
                root = parent[root]
            while parent[i] != root:
                parent[i], i = root, parent[i]
            return root

        def union(i, j):
            """合并两簇；根始终取簇内最小原始下标，保证结果确定性。"""
            ri, rj = find(i), find(j)
            if ri == rj:
                return False
            if ri < rj:
                parent[rj] = ri
            else:
                parent[ri] = rj
            return True

        def cell(x):
            # floor(x / eps) 的精确有理实现；避免 x / eps 的浮点舍入把相邻
            # 点分到不相邻的格，从而漏合并。
            num, den = x.as_integer_ratio()
            return (num * eps_den) // (den * eps_num)

        # 1) 坐标完全相同：直接合并（高频路径，无需距离计算）。
        first_at = {}
        for i, p in enumerate(pts):
            j = first_at.setdefault(p, i)
            if j != i:
                union(j, i)

        # 2) 容差网格：格边长 eps，因此距离 ≤ eps 的点对必然位于同格或相邻格。
        buckets = {}
        for i, p in enumerate(pts):
            buckets.setdefault((cell(p[0]), cell(p[1]), cell(p[2])), []).append(i)

        def bounds(ids):
            x0 = y0 = z0 = x1 = y1 = z1 = None
            for i in ids:
                x, y, z = pts[i]
                if x0 is None:
                    x0 = x1 = x
                    y0 = y1 = y
                    z0 = z1 = z
                    continue
                if x < x0:
                    x0 = x
                elif x > x1:
                    x1 = x
                if y < y0:
                    y0 = y
                elif y > y1:
                    y1 = y
                if z < z0:
                    z0 = z
                elif z > z1:
                    z1 = z
            return x0, y0, z0, x1, y1, z1

        def diag_le_eps(b):
            """包围盒对角线长度是否不超过 eps（>eps 时任意两点必在容差内）。"""
            return hypot(b[3] - b[0], b[4] - b[1], b[5] - b[2]) <= eps

        def bbox_far(b, c):
            """两包围盒最小距离 > eps？（下界，用于剪枝）"""
            gaps = []
            for axis in (0, 1, 2):
                if b[axis + 3] < c[axis]:
                    gaps.append(c[axis] - b[axis + 3])
                elif c[axis + 3] < b[axis]:
                    gaps.append(b[axis] - c[axis + 3])
            return hypot(*gaps) > eps

        def bbox_near(b, c):
            """两包围盒最大距离 ≤ eps？（上界，成立则任意跨盒点对都合并）"""
            return hypot(
                max(abs(b[0] - c[3]), abs(b[3] - c[0])),
                max(abs(b[1] - c[4]), abs(b[4] - c[1])),
                max(abs(b[2] - c[5]), abs(b[5] - c[2])),
            ) <= eps

        def merge_all(*groups):
            first = None
            for ids in groups:
                for i in ids:
                    if first is None:
                        first = i
                    else:
                        union(first, i)

        # 组内点数不超过该阈值时直接两两比较。
        _BRUTE = 24

        # 平方和比较是快路径；但它可能在极大坐标下上溢为 inf、在极小 eps 下
        # 下溢为 0，此时回退到 hypot，避免错误的“全部合并/全部不合并”。
        _INF = float("inf")

        def closer(dx, dy, dz):
            s = dx * dx + dy * dy + dz * dz
            if 0.0 < s < _INF:
                return s <= eps2
            return hypot(dx, dy, dz) <= eps

        def compare(ids):
            for a in range(len(ids)):
                i = ids[a]
                ri = find(i)
                xi, yi, zi = pts[i]
                for b in range(a + 1, len(ids)):
                    j = ids[b]
                    if find(j) == ri:
                        continue
                    xj, yj, zj = pts[j]
                    if closer(xi - xj, yi - yj, zi - zj):
                        union(i, j)
                        ri = find(i)

        def has_close(left, right):
            """两组点之间是否存在距离 ≤ eps 的点对（找到即返回）。"""
            bl = bounds(left)
            br = bounds(right)
            if bbox_far(bl, br):
                return False
            if bbox_near(bl, br):
                return True
            for i in left:
                xi, yi, zi = pts[i]
                for j in right:
                    xj, yj, zj = pts[j]
                    if closer(xi - xj, yi - yj, zi - zj):
                        return True
            return False

        def split(ids, b):
            """按包围盒最长轴的中位数二分；返回 (左, 右, 分割坐标, 轴)。"""
            ext = (b[3] - b[0], b[4] - b[1], b[5] - b[2])
            axis = 0
            if ext[1] > ext[axis]:
                axis = 1
            if ext[2] > ext[axis]:
                axis = 2
            order = sorted(ids, key=lambda i: pts[i][axis])
            mid = len(order) // 2
            return order[:mid], order[mid:], pts[order[mid]][axis], axis

        def cross(left, right):
            """合并左、右两组之间距离 ≤ eps 的点对。"""
            if not left or not right:
                return
            bl = bounds(left)
            br = bounds(right)
            if bbox_far(bl, br):
                return  # 两组整体相距超过容差
            if bbox_near(bl, br):
                merge_all(left, right)  # 任意跨组点对都在容差内
                return
            if len(left) + len(right) <= 2 * _BRUTE:
                compare(left + right)
                return

            # 组件级处理：跨组的连通性只取决于“某组件对之间是否存在近邻
            # 点对”，找到一对即刻把两个组件整体连通，其余点对无需再查。
            groups_l = {}
            for i in left:
                groups_l.setdefault(find(i), []).append(i)
            groups_r = {}
            for i in right:
                groups_r.setdefault(find(i), []).append(i)
            # 组件太多（两组点相互穿插）时改用轴向二分，避免组件对数量爆炸。
            if len(groups_l) * len(groups_r) > 4096:
                a, b = (left, right) if len(left) >= len(right) else (right, left)
                a1, a2, _, _ = split(a, bounds(a))
                cross(a1, b)
                cross(a2, b)
                return

            changed = True
            while changed:
                changed = False
                for rl, lids in groups_l.items():
                    for rr, rids in groups_r.items():
                        if find(rl) == find(rr):
                            continue
                        if not has_close(lids, rids):
                            continue
                        union(rl, rr)
                        changed = True
                        break
                    if changed:
                        break
                if changed:
                    # 重新按当前簇归属归并组件列表
                    merged_l = {}
                    for ids in groups_l.values():
                        for i in ids:
                            merged_l.setdefault(find(i), []).append(i)
                    merged_r = {}
                    for ids in groups_r.values():
                        for i in ids:
                            merged_r.setdefault(find(i), []).append(i)
                    groups_l, groups_r = merged_l, merged_r

        def resolve(ids):
            """在组内按“距离 ≤ eps”合并（分治 + 包围盒剪枝）。"""
            m = len(ids)
            if m < 2:
                return
            if m <= _BRUTE:
                compare(ids)
                return
            if diag_le_eps(bounds(ids)):
                merge_all(ids)
                return
            left, right, mid, axis = split(ids, bounds(ids))
            resolve(left)
            resolve(right)
            # 只有分割面附近宽度 eps 内的点可能跨组近邻。
            low = mid - eps
            high = mid + eps
            near_left = [i for i in left if pts[i][axis] >= low]
            near_right = [i for i in right if pts[i][axis] <= high]
            cross(near_left, near_right)

        # 格内：按容差合并（格内任意两点距离 < sqrt(3)*eps，仍需精确判定）。
        for ids in buckets.values():
            resolve(ids)

        # 格间：只枚举 13 个正向邻格，每个无序格对恰好处理一次，覆盖全部
        # 距离 ≤ eps 的跨格点对。
        get = buckets.get
        for (cx, cy, cz), ids in buckets.items():
            for dx, dy, dz in _FORWARD_NEIGHBORS:
                other = get((cx + dx, cy + dy, cz + dz))
                if not other:
                    continue
                cross(ids, other)

        return [find(i) for i in range(n)]

    # ------------------------------------------------------------- 拓扑校验
    def nonmanifold(self, faces):
        """返回非流形边 ``[(a, b), ...]``，``a < b``，按边排序。

        无向边被 3 个及以上三角形共享（含反向）即判为非流形；合法网格返回
        空列表。非法输入按 :meth:`weld` 相同的规则抛 ``TypeError`` /
        ``ValueError``。
        """
        tris = self._check_faces(faces, 1 << 62)
        count = {}
        for a, b, c in tris:
            for u, v in ((a, b), (b, c), (c, a)):
                key = (u, v) if u < v else (v, u)
                count[key] = count.get(key, 0) + 1
        return [edge for edge, k in sorted(count.items()) if k >= 3]
