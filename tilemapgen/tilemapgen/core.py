"""tilemapgen 核心 API（初始未实现）。"""


class MapGen:
    def __init__(self, seed, density):
        """构造"""
        raise NotImplementedError

    def generate(self, w, h):
        """生成"""
        raise NotImplementedError

    def is_connected(self):
        """连通性"""
        raise NotImplementedError
