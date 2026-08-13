"""测试公共 fixture：每个用例重置登录限流器。"""
from __future__ import annotations

import pytest

from app.core.rate_limit import login_limiter


@pytest.fixture(autouse=True)
def _reset_login_limiter() -> None:
    login_limiter._failures.clear()
