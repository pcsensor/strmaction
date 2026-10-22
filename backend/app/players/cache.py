"""播放缓存上限的共享约束。

服务端只负责下发上限，真正的缓存由客户端播放器执行：

- 伴侣 App：Media3 DefaultLoadControl 的目标缓冲字节数；
- StrmAction 桌面端：Qt Multimedia 的本地预读缓冲。
"""

from __future__ import annotations

from typing import Any

DEFAULT_CACHE_LIMIT_MB = 128
MAX_CACHE_LIMIT_MB = 2048
MIN_CACHE_LIMIT_MB = 0
MIN_ACTIVE_CACHE_LIMIT_MB = 16


def normalize_cache_limit(value: Any) -> int:
    """把配置/请求里的缓存上限归一为 0 或 16–2048 的整数（MB）。"""
    if isinstance(value, bool):
        value = DEFAULT_CACHE_LIMIT_MB
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_CACHE_LIMIT_MB
    if limit <= MIN_CACHE_LIMIT_MB:
        return MIN_CACHE_LIMIT_MB
    return min(max(limit, MIN_ACTIVE_CACHE_LIMIT_MB), MAX_CACHE_LIMIT_MB)
