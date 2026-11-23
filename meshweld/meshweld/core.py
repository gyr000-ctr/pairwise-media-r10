"""meshweld 核心 API（初始未实现）。"""


class Weld:
    def weld(self, verts, faces, eps):
        """焊接"""
        raise NotImplementedError

    def nonmanifold(self, faces):
        """非流形边"""
        raise NotImplementedError
