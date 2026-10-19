"""跨源补空（附录 D.5.1）：只补空字段，季集结构永不混用。"""

from __future__ import annotations

from .base import CanonicalMeta

FILL_FIELDS = (
    "overview",
    "tagline",
    "poster_url",
    "backdrop_url",
    "logo_url",
    "certification",
    "runtime_min",
    "rating",
    "trailer_key",
    "collection",
    "status",
    "year",
    "original_title",
)


def fill_missing(primary: CanonicalMeta, other: CanonicalMeta) -> list[str]:
    filled: list[str] = []
    for field in FILL_FIELDS:
        current = getattr(primary, field, None)
        replacement = getattr(other, field, None)
        if not current and replacement:
            setattr(primary, field, replacement)
            filled.append(field)
    if not primary.genres and other.genres:
        primary.genres = list(other.genres)
        filled.append("genres")
    if not primary.cast and other.cast:
        primary.cast = list(other.cast)
        filled.append("cast")
    if other.aliases:
        existing = {a for a in primary.aliases if a}
        for alias in other.aliases:
            if alias and alias not in existing:
                primary.aliases.append(alias)
                existing.add(alias)
        if "aliases" not in filled:
            filled.append("aliases")
    for key, value in other.external_ids.items():
        if value:
            primary.external_ids.setdefault(key, value)
    # 季集结构绝不从另一源取
    return filled
