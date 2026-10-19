"""解析器入口。"""

from __future__ import annotations

from .rules import (
    PARSER_VERSION,
    compile_template,
    extract_explicit_ids,
    parse_movie,
    parse_path,
    parse_tv,
    parse_with_template,
    season_from_dir,
)
from .types import Parsed

__all__ = [
    "Parsed",
    "PARSER_VERSION",
    "parse_path",
    "parse_movie",
    "parse_tv",
    "parse_with_template",
    "compile_template",
    "season_from_dir",
    "extract_explicit_ids",
]
