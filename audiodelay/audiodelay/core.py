"""audiodelay 核心 API：支持分数延迟的反馈式延迟线回声。

- 分数延迟：线性插值（整数延迟时退化为精确延迟，误差为 0）。
- 反馈系数 |feedback| < 1 时回声能量按 |feedback|^k 单调衰减；|feedback| >= 1 报错。
- 非法延迟与非法反馈使用不同的 ValueError 子类，可区分捕获。
- 跨缓冲连续：内部环形缓冲状态在多次 process 调用间保持。
- 并发安全：process 由实例级锁保护。
"""

from __future__ import annotations

import math
import threading

__all__ = ["Delay", "DelayError", "FeedbackError"]


class DelayError(ValueError):
    """非法延迟参数（非有限或 <= 0）。"""


class FeedbackError(ValueError):
    """非法反馈系数（非有限或 |feedback| >= 1）。"""


class Delay:
    """反馈式延迟线回声：y[n] = x[n] + feedback * y[n - delay]。"""

    def __init__(self, delay=1, feedback=0.0):
        if not isinstance(delay, (int, float)):
            raise TypeError(f"延迟必须为实数，得到 {type(delay).__name__}")
        delay = float(delay)
        if not math.isfinite(delay) or delay <= 0.0:
            raise DelayError(f"非法延迟 {delay!r}：需为正有限值")
        if not isinstance(feedback, (int, float)):
            raise TypeError(f"反馈系数必须为实数，得到 {type(feedback).__name__}")
        feedback = float(feedback)
        if not math.isfinite(feedback) or not -1.0 < feedback < 1.0:
            raise FeedbackError(f"非法反馈系数 {feedback!r}：需满足 |feedback| < 1")

        frac, d = math.modf(delay)
        self._delay = delay
        self._feedback = feedback
        self._d = int(d)
        self._frac = frac
        # 线性插值需读取 w-d 与 w-d-1，环形缓冲长度 d+2 即可。
        self._buf = [0.0] * (self._d + 2)
        self._w = 0
        self._lock = threading.Lock()

    def process(self, samples):
        """处理一段采样并返回等长 list；状态保留，可跨缓冲连续调用。"""
        with self._lock:
            xs = list(samples)
            n = len(xs)
            out = [0.0] * n
            buf = self._buf
            size = len(buf)
            w = self._w
            fb = self._feedback
            frac = self._frac
            if frac == 0.0:
                # 整数延迟：精确路径，无插值误差。
                r = w - self._d
                if r < 0:
                    r += size
                for i in range(n):
                    y = xs[i] + fb * buf[r]
                    buf[w] = y
                    out[i] = y
                    w += 1
                    if w == size:
                        w = 0
                    r += 1
                    if r == size:
                        r = 0
            else:
                # 分数延迟：线性插值。
                c0 = 1.0 - frac
                r1 = w - self._d
                if r1 < 0:
                    r1 += size
                r2 = r1 - 1
                if r2 < 0:
                    r2 += size
                for i in range(n):
                    y = xs[i] + fb * (c0 * buf[r1] + frac * buf[r2])
                    buf[w] = y
                    out[i] = y
                    w += 1
                    if w == size:
                        w = 0
                    r1 += 1
                    if r1 == size:
                        r1 = 0
                    r2 += 1
                    if r2 == size:
                        r2 = 0
            self._w = w
            return out
