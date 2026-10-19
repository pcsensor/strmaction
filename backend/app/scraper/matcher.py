"""标题归一化打分（附录 D.4）。"""

from __future__ import annotations

from rapidfuzz import fuzz

from ..text import normalize_title
from .base import Candidate


def title_similarity(query: str, candidate: str) -> float:
    left = normalize_title(query)
    right = normalize_title(candidate)
    if not left or not right:
        return 0.0
    return fuzz.WRatio(left, right) / 100.0


def score_candidate(
    query_title: str,
    query_year: int | None,
    candidate: Candidate,
    rank: int,
    total: int,
) -> float:
    title_sim = title_similarity(query_title, candidate.title)
    if query_year and candidate.year:
        distance = abs(query_year - candidate.year)
        year_score = 1.0 if distance == 0 else (0.7 if distance == 1 else 0.0)
    else:
        year_score = 0.5

    pop_score = 1.0 - (rank / max(1, total - 1))
    query_norm = normalize_title(query_title)
    alias_names = [candidate.original_title or "", *(candidate.aliases or [])]
    alias_hit = 1.0 if any(
        query_norm and normalize_title(alias) == query_norm for alias in alias_names
    ) else 0.0
    return 0.55 * title_sim + 0.25 * year_score + 0.10 * pop_score + 0.10 * alias_hit


def rank_candidates(
    query_title: str,
    query_year: int | None,
    candidates: list[Candidate],
) -> list[tuple[float, Candidate]]:
    total = len(candidates)
    scored = [
        (score_candidate(query_title, query_year, candidate, rank, total), candidate)
        for rank, candidate in enumerate(candidates)
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def episode_penalty(score: float, max_episode: int | None, episode_count: int | None) -> float:
    """解析集数比 provider 多 20% 以上时降权（剧场版被当成剧集）。"""
    if not max_episode or not episode_count:
        return score
    if max_episode > episode_count * 1.2:
        return max(0.0, score - 0.2)
    return score


def classify(score: float, threshold: float = 0.75) -> str:
    if score >= threshold:
        return "auto"
    if score >= 0.60:
        return "pending"
    return "failed"
