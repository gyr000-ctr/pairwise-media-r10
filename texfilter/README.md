# texfilter

## 题面（可直接粘贴）

各向异性纹理过滤。约束：与暴力超采样对照（PSNR ≥40 dB）；各向异性比正确钳制；权重和为 1；边界 wrap/clamp 两种；1 万像素不超过 500 ms；非法参数报错。验收：cd texfilter && python -m pytest tests -q -k filter。

## 边界要求（评审侧隐藏用例判分）

- 并发安全
- 非有限输入分类报错
- 性能上界按题面

## 运行方式

```bash
cd texfilter && python -m pytest tests -q
```

初始 15 failed。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：图形渲染
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
