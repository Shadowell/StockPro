"""
BitPro 自动化测试 - 公共配置
"""
import os
import sys
from pathlib import Path
# 禁用系统代理（ClashX/V2Ray等），避免 httpx 走代理返回 502
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"

BACKEND_PATH = str(Path(__file__).resolve().parents[1] / "backend")
if BACKEND_PATH not in sys.path:
    sys.path.insert(0, BACKEND_PATH)

import pytest
import httpx

# 后端API基础地址（使用 127.0.0.1 避免 IPv6 连接拒绝）
BASE_URL = "http://127.0.0.1:8889/api/v2"

# 支持的交易所（当前只配置了 OKX）
EXCHANGES = ["okx"]

# 测试用交易对
TEST_SYMBOL = "BTC/USDT"


@pytest.fixture(scope="session")
def client():
    """HTTP客户端（整个测试会话共享，禁用代理避免走ClashX等代理软件）"""
    transport = httpx.HTTPTransport(proxy=None)
    with httpx.Client(base_url=BASE_URL, timeout=30.0, transport=transport) as c:
        yield c


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL
