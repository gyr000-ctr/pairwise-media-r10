# tilemapgen

## 题面（可直接粘贴）

程序化瓦片地图。约束：同种子可复现；生成地图必须连通（BFS 校验）；边界封闭；密度参数影响陆地比例（误差 ≤10%）；128x128 不超过 500 ms；非法参数报错。验收：cd tilemapgen && python -m pytest tests -q -k map。

## 边界要求（评审侧隐藏用例判分）

- 并发安全
- 非有限输入分类报错
- 性能上界按题面

## 运行方式

```bash
cd tilemapgen && python -m pytest tests -q
```

初始 15 failed。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：游戏开发
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
