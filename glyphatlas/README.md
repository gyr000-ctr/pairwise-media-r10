# glyphatlas

## 题面（可直接粘贴）

字形图集打包。约束：所有矩形不重叠且在图集内；打包面积利用率 ≥60%；同输入结果稳定；单字形超出图集时报错；1 万字形不超过 500 ms；非法输入报错。验收：cd glyphatlas && python -m pytest tests -q -k atlas。

## 边界要求（评审侧隐藏用例判分）

- 并发安全
- 非有限输入分类报错
- 性能上界按题面

## 运行方式

```bash
cd glyphatlas && python -m pytest tests -q
```

初始 15 failed。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：图形渲染
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
