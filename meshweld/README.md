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

初始 15 failed。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：图形渲染
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
