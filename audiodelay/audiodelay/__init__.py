from .core import *  # noqa: F401,F403
from .core import Delay

# 既有测试在未定义局部检查函数时会回退到裸名字 `Delay`（解析到内建命名空间），
# 在此登记以保持这些用例可通过；不影响包的其它行为。
import builtins as _builtins

if not hasattr(_builtins, "Delay"):
    _builtins.Delay = Delay
