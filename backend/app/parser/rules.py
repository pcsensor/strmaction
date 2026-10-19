"""文件名 / 目录名解析规则（中文优先，guessit 为兜底）。

设计目标：覆盖开发文档 §18.1 的全部样本，且对 SmartStrm 常见输出足够宽容。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from ..text import cn_num_to_int, normalize_title
from .types import Parsed

# 解析规则版本：升级后扫描器会对所有文件强制重解析一次，
# 避免「增量跳过」让老库永远停留在旧结构（例如整季被识别成一部电影）。
PARSER_VERSION = 5

_VIDEO_EXT_RE = re.compile(
    r"\.(?:strm|mp4|mkv|avi|mov|m2ts|ts|webm|flv|wmv|iso|rmvb)$", re.I
)
_EXPLICIT_ID_RE = re.compile(
    r"[\[\{\(（【]?\s*(tmdb|tvdb|imdb)\s*[-=:_ ]\s*(tt\d+|\d+)\s*[\]\}\)）】]?",
    re.I,
)
_YEAR_BRACKET_RE = re.compile(r"[\(（\[【]\s*((?:19|20)\d{2})\s*[\)）\]】]")
_YEAR_DELIM_RE = re.compile(r"(?:^|[\s._\-])((?:19|20)\d{2})(?=$|[\s._\-])")
_BRACKET_RE = re.compile(r"[\[【][^\]】]*[\]】]")

_QUALITY_TOKEN_RE = re.compile(
    r"""(?ix)
    \b(?:
      2160p|1080p|720p|480p|576p|4k|8k|uhd
      |hdr(?:10)?|hdr10\+|dv|dolby[ ._-]?vision|dovi
      |web[ ._-]?dl|webrip|web|bluray|blu[ ._-]?ray|bdrip|brrip|dvdrip|remux
      |x\.?264|x\.?265|h\.?264|h\.?265|hevc|avc|av1|10bit|8bit|10[ ._-]?bit
      |aac(?:[ ._-]?\d(?:\.\d)?)?|ac3|eac3|ddp?(?:[ ._-]?\d(?:\.\d)?)?|dts(?:[ ._-]?hd)?|truehd|atmos|flac|opus
      |proper|repack|internal|extended|unrated|imax|remastered|complete
      |multi[ ._-]?subs?|chs|cht|chinese|中字|中英字幕|国语|粤语|双语
    )\b
    """
)
_PART_RE = re.compile(
    r"(?i)(?:^|[\s._\-])(?:cd|disc|disk|part|pt)[\s._\-]*([0-9]{1,2}|i{1,3})(?=$|[\s._\-])"
)
_ROMAN = {"i": 1, "ii": 2, "iii": 3}

_CN_EP_RE = re.compile(r"第\s*([零〇一二三四五六七八九十百两\d]+)\s*[集话話期]")
_CN_SEASON_RE = re.compile(r"第\s*([零〇一二三四五六七八九十百两\d]+)\s*季")
_SEASON_DIR_RE = re.compile(r"(?i)^season[\s._\-]*(\d{1,2})(?:$|[\s._\-].*)")
_S_SEASON_DIR_RE = re.compile(r"(?i)^s(\d{1,2})(?:$|[\s._\-].*)")
# 合集目录：S01E01-S01E40 / S01E01-E40 / E01-E40 / S01E01-40
# 这种目录在 SmartStrm 输出里很常见，它既是季信息，又不是「剧名」。
_EP_RANGE_DIR_RE = re.compile(
    r"(?i)^(?:s(\d{1,2}))?[\s._\-]*e(\d{1,4})"
    r"(?:[\s._\-]*(?:-|~|—|–|－|至|to)[\s._\-]*(?:s(\d{1,2}))?[\s._\-]*e?(\d{1,4}))?$"
)
_EPISODE_DIR_RE = re.compile(r"(?i)^s?\d{1,2}[\s._\-]*e[\s._\-]*\d{1,4}$")
# 剧名目录里常见但不应被当成剧集的分类名
_JUNK_DIRS = {"season", "specials", "extras", "featurettes", "samples", "sample"}
_SXXEXX_RE = re.compile(
    r"(?i)(?:^|[^a-z0-9])s(\d{1,2})[\s._\-]*e(\d{1,4})(?=[^0-9]|$)"
)
_XRE_RE = re.compile(r"(?i)(?:^|[^a-z0-9])(\d{1,2})x(\d{1,4})(?=[^0-9]|$)")
_EP_PREFIX_RE = re.compile(
    r"(?i)(?:^|[\s._\-])(?:ep|e|episode|第)[\s._\-]*(\d{1,4})(?=$|[\s._\-])"
)
_LEADING_NUM_RE = re.compile(r"^\s*(\d{1,4})(?:[\s._\-]+|$)")
_TRAILING_NUM_RE = re.compile(r"(?:^|[\s._\-])(\d{1,4})$")


@dataclass
class NameInfo:
    title: str
    year: int | None
    version: str | None
    labels: list[str]
    part: int | None
    explicit_ids: dict[str, str]
    raw: str


def _nfkc(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "")


def strip_extension(name: str) -> str:
    # 允许 "VID_20240601.mp4.strm" 这类双重扩展名
    text = name or ""
    for _ in range(4):
        stripped = _VIDEO_EXT_RE.sub("", text)
        if stripped == text:
            break
        text = stripped
    return text.strip()


def extract_explicit_ids(text: str) -> dict[str, str]:
    ids: dict[str, str] = {}
    for match in _EXPLICIT_ID_RE.finditer(_nfkc(text)):
        provider = match.group(1).lower()
        value = match.group(2)
        if provider == "imdb" and not value.lower().startswith("tt"):
            value = f"tt{value}"
        ids.setdefault(provider, value)
    return ids


def extract_year(text: str) -> tuple[int | None, tuple[int, int] | None]:
    text = _nfkc(text)
    match = _YEAR_BRACKET_RE.search(text)
    if match:
        return int(match.group(1)), match.span()
    match = _YEAR_DELIM_RE.search(text)
    if match:
        return int(match.group(1)), match.span(1)
    # 末尾裸年份，例如 "Some.Show.2020" 已由分隔符命中
    match = re.search(r"(?:^|[^\d])((?:19|20)\d{2})$", text)
    if match:
        return int(match.group(1)), match.span(1)
    return None, None


def detect_version(text: str) -> tuple[str | None, list[str]]:
    lowered = _nfkc(text).lower()
    labels: list[str] = []
    version = None
    if re.search(r"2160p|\b4k\b|uhd", lowered):
        version = "2160p"
        labels.append("4K")
    elif "1080p" in lowered:
        version = "1080p"
    elif "720p" in lowered:
        version = "720p"
    elif "480p" in lowered:
        version = "480p"
    if re.search(r"\bhdr(?:10)?\b|hdr10\+", lowered):
        labels.append("HDR")
    if re.search(r"\bdv\b|dolby[ ._-]?vision|dovi", lowered):
        labels.append("DV")
    if "remux" in lowered:
        labels.append("REMUX")
    if re.search(r"10[ ._-]?bit", lowered):
        labels.append("10BIT")
    if re.search(r"atmos|truehd", lowered):
        labels.append("ATMOS")
    # 去重且保序
    seen: set[str] = set()
    unique = [x for x in labels if not (x in seen or seen.add(x))]
    return version, unique


def detect_part(text: str) -> int | None:
    match = _PART_RE.search(_nfkc(text))
    if not match:
        return None
    raw = match.group(1).lower()
    if raw in _ROMAN:
        return _ROMAN[raw]
    try:
        return int(raw)
    except ValueError:
        return None


def parse_name(name: str) -> NameInfo:
    """从文件名或目录名提取标题/年份/版本/分段。"""
    stem = strip_extension(_nfkc(name))
    explicit_ids = extract_explicit_ids(stem)
    version, labels = detect_version(stem)
    part = detect_part(stem)
    year, span = extract_year(stem)

    text = stem
    if span:
        text = text[: span[0]] + " " + text[span[1] :]
    text = _EXPLICIT_ID_RE.sub(" ", text)
    text = _BRACKET_RE.sub(" ", text)
    text = _CN_EP_RE.sub(" ", text)
    text = _SXXEXX_RE.sub(" ", text)
    text = _XRE_RE.sub(" ", text)
    text = _QUALITY_TOKEN_RE.sub(" ", text)
    text = _PART_RE.sub(" ", text)
    text = text.replace("_", " ").replace(".", " ")
    text = re.sub(r"\s*-\s*[A-Z0-9]{2,12}$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—·:：,，")
    if not text:
        text = strip_extension(_nfkc(name)).strip()
    return NameInfo(
        title=text.strip(),
        year=year,
        version=version,
        labels=labels,
        part=part,
        explicit_ids=explicit_ids,
        raw=name,
    )


def _split(rel_path: str) -> list[str]:
    return [p for p in _nfkc(rel_path).replace("\\", "/").split("/") if p]


def season_from_dir(name: str) -> int | None:
    text = _nfkc(name).strip()
    match = _EP_RANGE_DIR_RE.match(text)
    if match:
        if match.group(1):
            return int(match.group(1))
        if match.group(3):
            return int(match.group(3))
    match = _CN_SEASON_RE.search(text)
    if match:
        return cn_num_to_int(match.group(1))
    match = _SEASON_DIR_RE.match(text)
    if match:
        return int(match.group(1))
    match = _S_SEASON_DIR_RE.match(text)
    if match:
        return int(match.group(1))
    if re.fullmatch(r"(?i)(?:season|s)[\s._\-]*\d{1,2}", text):
        digits = re.findall(r"\d{1,2}", text)
        if digits:
            return int(digits[-1])
    return None


def is_season_dir(name: str) -> bool:
    text = _nfkc(name).strip()
    if not text:
        return False
    return season_from_dir(text) is not None or bool(_EP_RANGE_DIR_RE.match(text))


def is_range_dir(name: str) -> bool:
    """S01E01-S01E40 这类合集目录（不是单集目录）。"""
    match = _EP_RANGE_DIR_RE.match(_nfkc(name).strip())
    if not match:
        return False
    return bool(match.group(4) or (match.group(1) and match.group(2)))


def is_episode_dir(name: str) -> bool:
    return bool(_EPISODE_DIR_RE.match(_nfkc(name).strip()))


def looks_like_episode_path(rel_path: str) -> bool:
    """判断路径是否明显是剧集（用于电影库里混入电视剧时的自动识别）。

    只看强信号：季目录、SxxExx / xXy / 第 N 集 / EPxx、合集目录。
    普通电影目录（片名 + 年份 + 版本）不会被误判。
    """
    parts = _split(rel_path)
    if len(parts) < 2:
        return False
    filename = parts[-1]
    dirs = parts[:-1]
    if any(is_season_dir(d) or is_range_dir(d) for d in dirs):
        return True
    stem = strip_extension(_nfkc(filename))
    return bool(
        _SXXEXX_RE.search(stem)
        or _XRE_RE.search(stem)
        or _CN_EP_RE.search(stem)
        or _EP_PREFIX_RE.search(stem)
    )


def _episode_from_name(name: str) -> tuple[int | None, int | None, float]:
    """返回 (episode, season_from_name, confidence)。"""
    stem = strip_extension(_nfkc(name))
    match = _SXXEXX_RE.search(stem)
    if match:
        return int(match.group(2)), int(match.group(1)), 0.96
    match = _XRE_RE.search(stem)
    if match:
        return int(match.group(2)), int(match.group(1)), 0.94
    match = _CN_EP_RE.search(stem)
    if match:
        ep = cn_num_to_int(match.group(1))
        if ep:
            return ep, None, 0.92
    match = _EP_PREFIX_RE.search(stem)
    if match:
        return int(match.group(1)), None, 0.9
    match = re.fullmatch(r"(?:ep|e)?[\s._\-]*(\d{1,4})", stem, re.I)
    if match:
        return int(match.group(1)), None, 0.87
    match = _LEADING_NUM_RE.match(stem)
    if match:
        return int(match.group(1)), None, 0.85
    match = _TRAILING_NUM_RE.search(stem)
    if match:
        return int(match.group(1)), None, 0.84
    return None, None, 0.0


def _strip_episode_tokens(name: str) -> str:
    stem = strip_extension(_nfkc(name))
    stem = _SXXEXX_RE.sub(" ", stem)
    stem = _XRE_RE.sub(" ", stem)
    stem = _CN_EP_RE.sub(" ", stem)
    stem = _LEADING_NUM_RE.sub(" ", stem)
    stem = _TRAILING_NUM_RE.sub(" ", stem)
    return parse_name(stem).title


def _movie_parent_name(parts: list[str], root_name: str | None) -> str | None:
    """电影条目的父目录；跳过 Season/Extras/S01E01-S01E40 这类剧集目录。"""
    for idx in range(len(parts) - 2, -1, -1):
        name = parts[idx]
        if (
            not name
            or name.lower() in _JUNK_DIRS
            or is_season_dir(name)
            or is_range_dir(name)
            or is_episode_dir(name)
        ):
            continue
        return name
    # 媒体库根目录本身可能就是剧名（用户把根目录指向了剧集文件夹）
    if root_name and not is_season_dir(root_name) and not is_range_dir(root_name):
        return root_name
    return None


def parse_movie(
    rel_path: str, template: str | None = None, root_name: str | None = None
) -> Parsed:
    parts = _split(rel_path)
    filename = parts[-1] if parts else ""
    file_info = parse_name(filename)
    parent_name = _movie_parent_name(parts, root_name)
    parent_info = parse_name(parent_name) if parent_name else None

    title = file_info.title
    year = file_info.year
    confidence = 0.78

    if parent_info and parent_info.title:
        same_title = normalize_title(parent_info.title) == normalize_title(file_info.title)
        if same_title:
            title = parent_info.title or file_info.title
            year = parent_info.year or file_info.year
            confidence = 0.92
        elif parent_info.year:
            # 目录带年份，优先目录（如 "片名 (2023)/片名.2023.1080p.strm"）
            title = parent_info.title
            year = parent_info.year
            confidence = 0.9
        elif file_info.year:
            # 目录是分类名、文件名带年份
            title = file_info.title
            year = file_info.year
            confidence = 0.87
        else:
            title = parent_info.title or file_info.title
            year = parent_info.year or file_info.year
            confidence = 0.8
    elif len(parts) <= 1:
        confidence = 0.75
    if not title:
        title = strip_extension(filename).strip()
        confidence = min(confidence, 0.5)

    version = file_info.version or (parent_info.version if parent_info else None)
    labels = list(file_info.labels or [])
    if parent_info:
        labels += [x for x in parent_info.labels if x not in labels]
    part = file_info.part or (parent_info.part if parent_info else None)
    explicit: dict[str, str] = {}
    for info in (file_info, parent_info):
        if info:
            for key, value in info.explicit_ids.items():
                explicit.setdefault(key, value)

    return Parsed(
        kind="movie",
        title=title,
        year=year,
        confidence=confidence,
        raw_name=filename,
        version=version,
        labels=labels,
        part=part,
        explicit_ids=explicit,
        parser="rules",
    )


def _tv_series_dir(
    dirs: list[str], season_idx: int | None, root_name: str | None
) -> str | None:
    """找剧名目录：Season 目录的上一级；没有 Season 时取最深的有效目录。"""
    if season_idx is not None:
        # 可能有多层季/合集目录（如 Show/Season 01/S01E01-S01E40），
        # 一路向前找到第一个真正的剧名目录。
        for idx in range(season_idx - 1, -1, -1):
            candidate = dirs[idx]
            if (
                candidate
                and candidate.lower() not in _JUNK_DIRS
                and not is_season_dir(candidate)
                and not is_range_dir(candidate)
                and not is_episode_dir(candidate)
            ):
                return candidate
    else:
        for idx in range(len(dirs) - 1, -1, -1):
            candidate = dirs[idx]
            if (
                candidate
                and candidate.lower() not in _JUNK_DIRS
                and not is_season_dir(candidate)
                and not is_range_dir(candidate)
                and not is_episode_dir(candidate)
            ):
                return candidate
    # 媒体库根目录就是剧名目录（例如 root 指向 "卿卿日常 2022"）
    if root_name and root_name.lower() not in _JUNK_DIRS:
        if not (is_season_dir(root_name) or is_range_dir(root_name)):
            return root_name
    return None


def parse_tv(
    rel_path: str, template: str | None = None, root_name: str | None = None
) -> Parsed:
    parts = _split(rel_path)
    filename = parts[-1] if parts else ""
    dirs = parts[:-1]

    season_no: int | None = None
    season_idx: int | None = None
    for idx in range(len(dirs) - 1, -1, -1):
        value = season_from_dir(dirs[idx])
        if value is not None:
            season_no, season_idx = value, idx
            break
    if season_idx is None:
        # S01E01-S01E40 目录没有 group(1) 时 season_from_dir 会返回 None，
        # 但合集目录本身说明这是第一季/某季，交给剧名目录和文件名判断。
        for idx in range(len(dirs) - 1, -1, -1):
            if is_range_dir(dirs[idx]):
                season_idx = idx
                break

    episode_no, season_in_name, ep_confidence = _episode_from_name(filename)
    if season_in_name is not None:
        # 文件名里的 SxxExx 比目录名更具体
        season_no = season_in_name
    elif season_no is None:
        # 合集目录 S01E01-S01E40：从目录名补季号
        for name in reversed(dirs):
            match = _EP_RANGE_DIR_RE.match(_nfkc(name).strip())
            if match and match.group(1):
                season_no = int(match.group(1))
                break

    series_dir = _tv_series_dir(dirs, season_idx, root_name)
    if series_dir:
        series_info = parse_name(series_dir)
        series_title = series_info.title
        year = series_info.year
        confidence = 0.9
    else:
        series_info = parse_name(filename)
        series_title = _strip_episode_tokens(filename)
        year = series_info.year
        confidence = 0.8

    explicit = extract_explicit_ids(" ".join(parts))
    version, labels = detect_version(filename)

    if not episode_no:
        title = parse_name(filename).title
        return Parsed(
            kind="video",
            title=title or filename,
            year=year,
            confidence=0.55 if not title else 0.65,
            raw_name=filename,
            version=version,
            labels=labels,
            explicit_ids=explicit,
            group_title=series_title or None,
            parser="rules",
            warning="tv 库中的孤立文件",
        )

    season = season_no if season_no is not None else 1
    if not series_title:
        series_title = f"第 {season} 季"
    confidence = max(confidence, ep_confidence) if ep_confidence else confidence
    if season_no is None:
        confidence = min(confidence, 0.86)

    return Parsed(
        kind="episode",
        title=f"第{episode_no}集",
        year=year,
        season=season,
        episode=episode_no,
        confidence=confidence,
        raw_name=filename,
        version=version,
        labels=labels,
        explicit_ids=explicit,
        group_title=series_title,
        parser="rules",
    )


def _clean_tree_filename(filename: str) -> str:
    """课程与家庭视频专用：直接保留原文件名（去除 .strm 及冗余扩展名标记如 .(mp4)），不识别集数。"""
    stem = strip_extension(_nfkc(filename)).strip()
    stem = re.sub(r"[\._]?\([a-zA-Z0-9]+\)$", "", stem).strip()
    stem = strip_extension(stem).strip()
    return stem or strip_extension(filename)


def parse_home(rel_path: str) -> Parsed:
    parts = _split(rel_path)
    filename = parts[-1] if parts else ""
    folder_parts = parts[:-1]
    group = folder_parts[0] if folder_parts else None
    title = _clean_tree_filename(filename)
    info = parse_name(filename)
    return Parsed(
        kind="video",
        title=title,
        year=info.year,
        episode=None,
        confidence=0.9,
        raw_name=filename,
        version=info.version,
        part=info.part,
        labels=info.labels,
        group_title=group,
        chapter_title=folder_parts[-1] if folder_parts else None,
        folder_parts=folder_parts,
        parser="rules",
    )


def _clean_chapter_title(name: str) -> tuple[str, int | None]:
    stem = strip_extension(_nfkc(name)).strip()
    match = _LEADING_NUM_RE.match(stem)
    number = int(match.group(1)) if match else None
    if match:
        stem = stem[match.end() :].strip()
    return stem or _nfkc(name), number


def parse_course(rel_path: str) -> Parsed:
    parts = _split(rel_path)
    filename = parts[-1] if parts else ""
    folder_parts = parts[:-1]
    course = folder_parts[0] if folder_parts else None
    chapter = (
        folder_parts[1]
        if len(folder_parts) >= 2
        else (folder_parts[0] if folder_parts else None)
    )

    course_title = _clean_chapter_title(course)[0] if course else None
    chapter_title, chapter_no = (
        _clean_chapter_title(chapter) if chapter else (None, None)
    )

    title = _clean_tree_filename(filename)

    return Parsed(
        kind="video",
        title=title,
        year=None,
        season=chapter_no,
        episode=None,
        confidence=0.9,
        raw_name=filename,
        version=None,
        part=None,
        labels=[],
        group_title=course_title,
        chapter_title=chapter_title or "默认章节",
        folder_parts=folder_parts,
        parser="rules",
    )


# ---------------------------------------------------------------------------
# 目录模板
# ---------------------------------------------------------------------------

_TEMPLATE_TOKEN_RE = re.compile(r"\{(\w+)(?::0?(\d+)d)?\}")


_TOKEN_RX = {
    "title": r"[^/]+?",
    "year": r"(?:19|20)\d{2}",
    "season": r"\d{1,2}",
    "episode": r"\d{1,4}",
}


@lru_cache(maxsize=128)
def compile_template(template: str) -> re.Pattern[str] | None:
    """把 `{title} ({year})/...` 编译为命名组正则。

    同一字段重复出现时使用独立命名组（如 season__1），
    避免 `{season}` 与 `{season:02d}` 因补零写法不同而无法匹配；
    数值一致性在 parse_with_template 里校验。
    """
    if not template or "{" not in template:
        return None
    template = _nfkc(template).replace("\\", "/")
    pattern = ""
    seen: set[str] = set()
    duplicate_counter = 0
    position = 0
    try:
        for match in _TEMPLATE_TOKEN_RE.finditer(template):
            literal = template[position : match.start()]
            escaped = re.escape(literal)
            escaped = escaped.replace(r"\ ", r"[ ._]+")
            pattern += escaped
            name = match.group(1)
            rx = _TOKEN_RX.get(name)
            if not rx:
                return None
            if name in seen:
                duplicate_counter += 1
                pattern += f"(?P<{name}__{duplicate_counter}>{rx})"
            else:
                pattern += f"(?P<{name}>{rx})"
                seen.add(name)
            position = match.end()
        pattern += re.escape(template[position:])
        return re.compile(pattern + r"$", re.I)
    except re.error:
        return None


_BUILTIN_TEMPLATES: dict[str, list[str]] = {
    "movie": [
        "{title} ({year})/{title} ({year}).strm",
        "{title} ({year})/{title}.strm",
        "{title}/{title}.strm",
        "{title} ({year}).strm",
        "{title}.strm",
    ],
    "tv": [
        "{title} ({year})/Season {season:02d}/{title} - S{season:02d}E{episode:02d}.strm",
        "{title}/Season {season:02d}/{title} - S{season:02d}E{episode:02d}.strm",
        "{title} ({year})/Season {season:02d}/{title}.{episode:02d}.strm",
        "{title}/S{season:02d}/{title}.{episode:02d}.strm",
        "{title}/Season {season:02d}/{episode:02d}.strm",
    ],
}


def parse_with_template(
    rel_path: str, library_type: str, template: str | None
) -> Parsed | None:
    templates = [template] if template else _BUILTIN_TEMPLATES.get(library_type, [])
    if not templates:
        return None
    path = _nfkc(rel_path).replace("\\", "/")
    for candidate in templates:
        regex = compile_template(candidate)
        if not regex:
            continue
        match = regex.match(path)
        if not match:
            continue
        groups = match.groupdict()
        title = (groups.get("title") or "").strip()
        if not title:
            continue
        # 模板未显式声明 year 时，标题里可能带着年份/版本/ID，需要清洗
        title_info = parse_name(title)
        if extract_year(title)[0] or _QUALITY_TOKEN_RE.search(_nfkc(title)) or title_info.explicit_ids:
            title = title_info.title or title
            if not groups.get("year"):
                groups = dict(groups)
                if title_info.year:
                    groups["year"] = str(title_info.year)
        # 重复数值组必须一致（例如 第1季 与 S01 的补零差异不参与比较）
        conflict = False
        for key, value in list(groups.items()):
            if "__" not in key or value is None:
                continue
            base = key.split("__", 1)[0]
            other = groups.get(base)
            if other is None:
                continue
            if base in {"year", "season", "episode"}:
                if int(value) != int(other):
                    conflict = True
                    break
        if conflict:
            continue
        year = int(groups["year"]) if groups.get("year") else None
        season = int(groups["season"]) if groups.get("season") else None
        episode = int(groups["episode"]) if groups.get("episode") else None
        filename = path.split("/")[-1]
        version, labels = detect_version(filename)
        part = detect_part(filename)
        explicit = extract_explicit_ids(path)

        if library_type == "movie":
            kind = "movie"
        elif library_type == "tv":
            kind = "episode" if episode is not None else "series"
        else:
            kind = "video"

        if kind == "episode":
            if season is None:
                season = 1
            episode_title = f"第{episode}集"
        else:
            episode_title = title

        return Parsed(
            kind=kind,  # type: ignore[arg-type]
            title=episode_title,
            year=year,
            season=season,
            episode=episode,
            confidence=0.97,
            raw_name=filename,
            version=version,
            part=part,
            labels=labels,
            explicit_ids=explicit,
            group_title=title if kind == "episode" else None,
            parser="template",
        )
    return None


def parse_path(
    library_type: str,
    rel_path: str,
    template: str | None = None,
    season_type: str = "default",
    root_name: str | None = None,
) -> Parsed:
    """按库类型解析相对路径；模板优先，规则兜底。

    电影库如果出现明显的剧集结构（Season 目录 / SxxExx / 第 N 集 / 合集目录），
    也会自动按剧集解析：SmartStrm 用户经常把电视剧放进「电影」库，
    只按库类型硬切会把整季拆成一部「Season 01」电影的多个版本。
    """
    if library_type in {"movie", "tv"}:
        tv_like = looks_like_episode_path(rel_path)
        # 电影模板里的 {title}/{title}.strm 会误吃 "剧名/S01E01.strm"，
        # 因此电影库遇到明显剧集路径时跳过模板，直接走剧集规则。
        if library_type == "tv" or not tv_like:
            parsed = parse_with_template(rel_path, library_type, template)
            if parsed:
                return parsed
    if library_type == "movie":
        if looks_like_episode_path(rel_path):
            parsed = parse_tv(rel_path, template, root_name=root_name)
        else:
            parsed = parse_movie(rel_path, template, root_name=root_name)
    elif library_type == "tv":
        parsed = parse_tv(rel_path, template, root_name=root_name)
    elif library_type == "course":
        parsed = parse_course(rel_path)
    else:
        parsed = parse_home(rel_path)

    parsed.explicit_ids = parsed.explicit_ids or extract_explicit_ids(rel_path)
    if parsed.confidence < 0.5 or not parsed.title:
        # guessit 兜底：只在规则链低置信度时启用
        from .guess import guess

        guessed = guess(rel_path.replace("/", " ")) or {}
        guessed_title = guessed.get("title")
        if isinstance(guessed_title, str) and guessed_title.strip():
            parsed.title = guessed_title.strip()
            parsed.parser = "guessit"
        guessed_year = guessed.get("year")
        if parsed.year is None and isinstance(guessed_year, int):
            parsed.year = guessed_year
        guessed_season = guessed.get("season")
        guessed_episode = guessed.get("episode")
        if parsed.kind in {"episode", "video"} and isinstance(guessed_episode, int):
            parsed.episode = parsed.episode or guessed_episode
            if isinstance(guessed_season, int):
                parsed.season = parsed.season or guessed_season
            if parsed.kind == "video" and library_type == "tv":
                parsed.kind = "episode"
                parsed.season = parsed.season or 1
                parsed.title = f"第{parsed.episode}集"
                parsed.group_title = (
                    parsed.group_title
                    or strip_extension(rel_path.split("/")[-1])
                )
        parsed.confidence = max(parsed.confidence, 0.55)
    if parsed.confidence < 0.5 and parsed.title:
        parsed.warning = parsed.warning or "低置信度解析"
    return parsed
