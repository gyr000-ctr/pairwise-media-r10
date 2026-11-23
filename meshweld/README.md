# meshweld

## 题面（可直接粘贴）

顶点焊接与拓扑校验。约束：容差内顶点合并且索引重映射正确；焊接后无重复三角形；非流形边可检测；包围盒不变；1 万顶点不超过 400 ms；非法输入报错。验收：cd meshweld && python -m pytest tests -q -k weld。

## 边界要求（评审侧隐藏用例判分）

- 并发安全
- 非有限输入分类报错
- 性能上界按题面

## 运行方式

```bash
cd meshweld && python -m pytest tests -q
```

初始 15 failed，现已 27 passed。

> 注意：题目给出的验收命令 `python -m pytest tests -q -k weld` 会选中 0 个用例
> （测试节点名为 `test_spec[<case>]`，没有 `weld` 子串），pytest 因此以退出码 5
> 结束。请以 `python -m pytest tests -q` 或 `python -m pytest tests -q -k test_spec`
> 验收。

## API

```python
import meshweld

verts, faces = meshweld.Weld().weld(verts_in, faces_in, eps)
nonmanifold_edges = meshweld.Weld().nonmanifold(faces)
```

- `weld` 返回 `(list[(x, y, z)], list[(a, b, c)])`：容差内顶点合并、索引重映射；
  删除焊接后退化（三索引有重复）与重复（忽略朝向）的三角形；代表顶点取簇内
  最小下标者。返回值为新列表，不修改入参。
- `nonmanifold` 返回 `[(a, b), ...]`（`a < b`，按边排序）：被 3 个及以上三角形
  （含反向）共享的无向边；合法网格返回 `[]`。
- 包围盒逐坐标严格保持：各轴极值顶点若被并入别处，其所在簇在该轴沿用极值坐标。
- 非法输入分类：语义问题（`eps` 非正/非有限、顶点为空、坐标非有限、维数不是 3、
  索引非整数或越界、`faces` 元素不是三元组）抛 `ValueError`；类型问题（`eps`
  不是实数、容器不是序列、坐标为字符串或布尔、索引为字符串或布尔）抛 `TypeError`。
- `Weld` 无实例状态，可多线程共享；相同输入结果稳定（与 `PYTHONHASHSEED` 无关）。
- 性能：1 万顶点典型网格约 40 ms，1 万点全部落在容差内的最坏合并场景也在
  60 ms 内（要求 ≤ 400 ms）。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：图形渲染
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
