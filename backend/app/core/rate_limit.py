"""进程内登录限流：按客户端 IP 统计失败次数，成功则清零。

不引入 Redis；单 worker 部署下足够。nginx 层另有 limit_req 兜底。
"""
from __future__ import annotations

import time
from collections import defaultdict, deque


class LoginRateLimiter:
    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, window: int) -> deque[float]:
        now = time.monotonic()
        q = self._failures[key]
        cutoff = now - window
        while q and q[0] < cutoff:
            q.popleft()
        if not q:
            self._failures.pop(key, None)
            return deque()
        return q

    def is_blocked(self, key: str, max_attempts: int, window: int) -> bool:
        q = self._prune(key, window)
        return len(q) >= max_attempts

    def record_failure(self, key: str, window: int) -> None:
        self._prune(key, window)
        self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


login_limiter = LoginRateLimiter()
