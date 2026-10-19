"""文本归一化与中文数字工具。"""

from __future__ import annotations

import re
import unicodedata

try:  # 可选：繁简转换，缺失时降级为原文
    import zhconv as _zhconv
except Exception:  # pragma: no cover
    _zhconv = None

_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def to_simplified(text: str) -> str:
    if _zhconv is None:
        return text
    try:
        return _zhconv.convert(text, "zh-cn")
    except Exception:  # pragma: no cover
        return text


def cn_num_to_int(text: str) -> int | None:
    """支持 12 / 一二 / 二十三 / 一百 等写法。"""
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        try:
            return int(text)
        except ValueError:
            return None
    if text in _CN_DIGITS:
        return _CN_DIGITS[text]
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char == "十":
            section += (number or 1) * 10
            number = 0
        elif char == "百":
            section += (number or 1) * 100
            number = 0
        elif char == "千":
            section += (number or 1) * 1000
            number = 0
        else:
            return None
    total = section + number
    return total or None


_SEASON_WORD_RE = re.compile(r"(?i)\b(?:season|s)\s*\d+\b")
_CN_SEASON_RE = re.compile(r"第[一二三四五六七八九十百零〇两\d]+[季部]")
_BRACKET_RE = re.compile(r"[\[\(（【].*?[\]\)）】]")
_NON_WORD_RE = re.compile(r"[^\w\u4e00-\u9fff]+")


def normalize_title(value: str) -> str:
    """标题归一化：全角→半角、繁→简、去括号/季标记、去标点。"""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = to_simplified(text)
    text = _BRACKET_RE.sub(" ", text)
    text = _SEASON_WORD_RE.sub(" ", text)
    text = _CN_SEASON_RE.sub(" ", text)
    text = text.replace("劇場版", " ").replace("剧场版", " ").replace("篇", " ")
    text = _NON_WORD_RE.sub("", text)
    return text.lower()


def is_filler(value: str) -> bool:
    return normalize_title(value) in {"", "其他", "other", "未知", "unknown"}
