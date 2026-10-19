"""刮削子系统。"""

from __future__ import annotations

from .base import (
    Candidate,
    CanonicalMeta,
    CastMember,
    EpisodeMeta,
    SeasonDetail,
    SeasonSummary,
)
from .matcher import classify, rank_candidates, score_candidate
from .nfo import find_nfo, parse_nfo
from .service import ProviderRegistry, ScrapeService
from .tmdb import TmdbProvider
from .tvdb import TvdbProvider

__all__ = [
    "Candidate",
    "CanonicalMeta",
    "CastMember",
    "EpisodeMeta",
    "SeasonDetail",
    "SeasonSummary",
    "TmdbProvider",
    "TvdbProvider",
    "ScrapeService",
    "ProviderRegistry",
    "rank_candidates",
    "score_candidate",
    "classify",
    "find_nfo",
    "parse_nfo",
]
