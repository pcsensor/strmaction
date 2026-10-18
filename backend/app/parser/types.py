"""解析结果数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["movie", "series", "episode", "video"]


@dataclass
class Parsed:
    kind: Kind
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    confidence: float = 0.0
    raw_name: str = ""
    version: str | None = None
    part: int | None = None
    labels: list[str] = field(default_factory=list)
    explicit_ids: dict[str, str] = field(default_factory=dict)
    # 分组信息（home / course / tv 兜底）
    group_title: str | None = None
    chapter_title: str | None = None
    warning: str | None = None
    parser: str = "rules"  # template | rules | guessit | fallback

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "year": self.year,
            "season": self.season,
            "episode": self.episode,
            "confidence": self.confidence,
            "raw_name": self.raw_name,
            "version": self.version,
            "part": self.part,
            "labels": self.labels,
            "explicit_ids": self.explicit_ids,
            "group_title": self.group_title,
            "chapter_title": self.chapter_title,
            "warning": self.warning,
            "parser": self.parser,
        }
