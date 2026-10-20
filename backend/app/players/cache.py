"""播放缓存上限的共享约束与 mpv 参数。

服务端只负责下发上限，真正的缓存由客户端播放器执行：

- 伴侣 App：Media3 DefaultLoadControl 的目标缓冲字节数；
- 桌面 mpv / 服务端桌面 mpv：mpv 的 demuxer cache 参数。
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


def mpv_cache_args(limit_mb: Any) -> list[str]:
    """生成 mpv 缓存参数；0 表示关闭 demuxer cache。"""
    limit = normalize_cache_limit(limit_mb)
    if limit <= 0:
        return ["--cache=no", "--cache-on-disk=no"]
    # 回看缓存最多占前向缓存的 1/4，最低 8MiB，避免总内存翻倍。
    back = max(8, limit // 4)
    return [
        "--cache=yes",
        f"--demuxer-max-bytes={limit}MiB",
        f"--demuxer-max-back-bytes={back}MiB",
        "--cache-on-disk=no",
    ]
