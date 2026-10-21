"""Hybrid retrieval: FTS5 keyword + vector search fused by reciprocal rank (design.md §3)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from omnirecall.embeddings.base import Embedder
from omnirecall.errors import EngineError, LimitExceededError, ModelMissingError
from omnirecall.ids import parse_utc
from omnirecall.settings import Settings
from omnirecall.storage.repository import ChunkRow, Item, Repository
from omnirecall.storage.states import ItemStatus
from omnirecall.storage.vectors import VectorStore

_TOKEN = re.compile(r"\w+", re.UNICODE)
MAX_QUERY_TERMS = 32
SNIPPET_CHARS = 280
# Cosine similarity bands for the relevance label. Calibrated on the Phase 2
# evaluation corpus (docs/measurements.md); labels describe evidence strength,
# never certainty (rules.md §5.7).
STRONG_SIMILARITY = 0.45
MODERATE_SIMILARITY = 0.30


@dataclass
class SearchFilters:
    source_types: list[str] = field(default_factory=list)
    captured_after: str | None = None
    captured_before: str | None = None
    app: str | None = None
    path_prefix: str | None = None

    def active(self) -> bool:
        return bool(
            self.source_types
            or self.captured_after
            or self.captured_before
            or self.app
            or self.path_prefix
        )

    def accepts(self, item: Item) -> bool:
        if self.source_types and item.source_type not in self.source_types:
            return False
        captured = parse_utc(item.captured_at)
        if self.captured_after and captured < parse_utc(self.captured_after):
            return False
        if self.captured_before and captured > parse_utc(self.captured_before):
            return False
        if self.app and item.metadata.get("app") != self.app:
            return False
        return not (self.path_prefix and not (item.source_uri or "").startswith(self.path_prefix))


# Function words match nearly every chunk and drown the keyword ranking.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "after",
        "before",
        "should",
        "could",
    ]
)


def fts_query(query: str) -> str | None:
    """Escape user text into an FTS5 query: each term quoted, OR-combined.

    Quoting makes every token a literal phrase, so FTS5 operators in user
    input (AND, NEAR, *, column filters) have no effect.
    """
    terms = [t for t in _TOKEN.findall(query.lower()) if t][:MAX_QUERY_TERMS]
    content = [t for t in terms if t not in STOPWORDS]
    terms = content or terms
    if not terms:
        return None
    unique = list(dict.fromkeys(terms))
    return " OR ".join(f'"{t}"' for t in unique)


def make_snippet(text: str, query: str) -> tuple[str, list[list[int]]]:
    """A window of the chunk around the first query term, with highlight ranges."""
    words = {t for t in _TOKEN.findall(query.lower()) if len(t) > 1}
    terms = {t for t in words if t not in STOPWORDS} or words
    # Match at the start of a word only, so "do" never lights up inside "undo".
    patterns = [re.compile(rf"(?<!\w){re.escape(t)}") for t in terms]
    lowered = text.lower()
    first = min((m.start() for pat in patterns if (m := pat.search(lowered))), default=0)
    start = max(0, first - SNIPPET_CHARS // 3)
    if start > 0:
        space = text.rfind(" ", 0, start)
        start = space + 1 if space >= 0 and start - space < 30 else start
    end = min(len(text), start + SNIPPET_CHARS)
    snippet = text[start:end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    shown = prefix + snippet + suffix
    highlights: list[list[int]] = []
    lowered_snippet = shown.lower()
    for pat in patterns:
        for match in pat.finditer(lowered_snippet):
            highlights.append([match.start(), match.end()])
    highlights.sort()
    merged: list[list[int]] = []
    for span in highlights:
        if merged and span[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], span[1])
        else:
            merged.append(span)
    return shown, merged


@dataclass
class Candidate:
    chunk_id: str
    item_id: str
    score: float = 0.0
    keyword_rank: int | None = None
    vector_rank: int | None = None
    similarity: float | None = None


class SearchService:
    def __init__(self, repo: Repository, vectors: VectorStore, embedder: Embedder) -> None:
        self.repo = repo
        self.vectors = vectors
        self.embedder = embedder

    def validate(self, query: str, settings: Settings) -> str:
        cleaned = " ".join(query.split())
        if not cleaned:
            raise EngineError("empty_query", "Type something to search for")
        if len(cleaned) > settings.max_query_chars:
            raise LimitExceededError("query_length", settings.max_query_chars)
        return cleaned

    def search(
        self,
        query: str,
        settings: Settings,
        filters: SearchFilters | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        filters = filters or SearchFilters()
        cleaned = self.validate(query, settings)
        limit = min(limit or settings.results_shown, 200)
        widen = 4 if filters.active() else 1
        candidates: dict[str, Candidate] = {}
        semantic_available = self.embedder.available()

        lexical = fts_query(cleaned)
        if lexical:
            for rank, (cid, item_id, _score) in enumerate(
                self.repo.keyword_search(lexical, settings.keyword_top_k * widen), start=1
            ):
                cand = candidates.setdefault(cid, Candidate(cid, item_id))
                cand.keyword_rank = rank
                cand.score += 1.0 / (settings.rrf_k + rank)

        if semantic_available:
            try:
                vector = self.embedder.embed([cleaned])[0]
            except ModelMissingError:
                semantic_available = False
            else:
                for rank, hit in enumerate(
                    self.vectors.search(vector, settings.vector_top_k * widen), start=1
                ):
                    cand = candidates.setdefault(hit.chunk_id, Candidate(hit.chunk_id, hit.item_id))
                    cand.vector_rank = rank
                    cand.similarity = 1.0 - hit.distance
                    cand.score += 1.0 / (settings.rrf_k + rank)

        ranked = sorted(candidates.values(), key=lambda c: (-c.score, c.chunk_id))
        items = self.repo.get_items(list({c.item_id for c in ranked}))
        chunks = self.repo.get_chunks([c.chunk_id for c in ranked])

        results: list[dict[str, Any]] = []
        seen_items: dict[str, dict[str, Any]] = {}
        for cand in ranked:
            item = items.get(cand.item_id)
            chunk = chunks.get(cand.chunk_id)
            # Discard deleted/excluded/unindexed and stale vectors (design.md §10).
            if item is None or chunk is None or item.status != ItemStatus.INDEXED:
                continue
            if not filters.accepts(item):
                continue
            if item.id in seen_items:
                seen_items[item.id]["more_matches"] += 1
                continue
            result = self._result(cand, item, chunk, cleaned)
            seen_items[item.id] = result
            results.append(result)
            if len(results) >= limit:
                break

        strong = any(r["relevance"] == "strong" for r in results)
        return {
            "results": results,
            "count": len(results),
            "semantic_available": semantic_available,
            "no_strong_match": not strong,
            "took_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def _result(self, cand: Candidate, item: Item, chunk: ChunkRow, query: str) -> dict[str, Any]:
        snippet, highlights = make_snippet(chunk.text, query)
        matched_by = (
            "both"
            if cand.keyword_rank and cand.vector_rank
            else "keyword"
            if cand.keyword_rank
            else "semantic"
        )
        similarity = cand.similarity
        semantic = similarity or 0.0
        if semantic >= STRONG_SIMILARITY or (cand.keyword_rank and semantic >= MODERATE_SIMILARITY):
            relevance = "strong"
        elif semantic >= MODERATE_SIMILARITY or cand.keyword_rank:
            relevance = "moderate"
        else:
            relevance = "weak"
        return {
            "item_id": item.id,
            "chunk_id": chunk.id,
            "source_type": item.source_type,
            "source_label": item.source_label,
            "source_uri": item.source_uri,
            "captured_at": item.captured_at,
            "app": item.metadata.get("app"),
            "snippet": snippet,
            "highlights": highlights,
            "score": round(cand.score, 6),
            "similarity": None if similarity is None else round(similarity, 4),
            "matched_by": matched_by,
            "relevance": relevance,
            "more_matches": 0,
        }
