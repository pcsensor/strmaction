"""guessit 兜底解析。

未安装 guessit 或 guessit 失败时，返回 None，由调用方使用规则结果。
"""

from __future__ import annotations

import re
from typing import Any

try:  # pragma: no cover - 依赖可选
    import guessit as _guessit
except Exception:  # pragma: no cover
    _guessit = None


def available() -> bool:
    return _guessit is not None


def guess(filename: str) -> dict[str, Any] | None:
    if _guessit is None:
        return None
    try:
        result = _guessit.guessit(filename, {"expected_title": [], "type": "episode"})
        return dict(result)
    except Exception:  # pragma: no cover
        return None


_CN_EP = re.compile(r"第\s*(\d+)\s*[集话]")


def guess_fallback(filename: str) -> dict[str, Any]:
    """无 guessit 时的最小兜底：只处理 SxxExx 与第 N 集。"""
    text = filename or ""
    match = re.search(r"(?i)s(\d{1,2})e(\d{1,4})", text)
    if match:
        return {
            "title": re.split(r"(?i)s\d{1,2}e\d{1,4}", text)[0].strip(" ._-"),
            "season": int(match.group(1)),
            "episode": int(match.group(2)),
        }
    match = _CN_EP.search(text)
    if match:
        return {
            "title": text[: match.start()].strip(" ._-"),
            "episode": int(match.group(1)),
        }
    return {"title": text}
