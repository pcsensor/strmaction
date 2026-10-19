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
from .registry import ProviderRegistry, register_provider
from .service import ScrapeService
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
    "register_provider",
    "rank_candidates",
    "score_candidate",
    "classify",
    "find_nfo",
    "parse_nfo",
]
