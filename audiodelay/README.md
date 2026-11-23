# audiodelay

## 题面（可直接粘贴）

延迟线回声。约束：延迟样本位置精确（≤1e-9）；反馈系数 <1 时能量衰减；反馈 ≥1 时报错；跨缓冲连续；100 万样本不超过 400 ms；非法参数可区分报错。验收：cd audiodelay && python -m pytest tests -q -k delay。

## 边界要求（评审侧隐藏用例判分）

- 并发安全
- 非有限输入分类报错
- 性能上界按题面

## 运行方式

```bash
cd audiodelay && python -m pytest tests -q
```

初始 15 failed。

## 字段

- 所属领域：游戏、图形与多媒体
- 子方向：音视频处理
- 任务类型：Bugfix
- 语言/框架：Python 3, pytest
- 环境可复现等级：无外部依赖
