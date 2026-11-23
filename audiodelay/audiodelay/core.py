"""audiodelay 核心 API（初始未实现）。"""


class Delay:
    def __init__(self, delay, feedback):
        """构造"""
        raise NotImplementedError

    def process(self, samples):
        """处理"""
        raise NotImplementedError
