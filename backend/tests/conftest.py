import sys
import types


if "akshare" not in sys.modules:
    sys.modules["akshare"] = types.SimpleNamespace()
