"""Evidence acquisition, hybrid search, temporal filter, and authority check (``H5``).

Implements FR-VER-03, DVSS-K05 (idempotent acquisition & binding authority
verification), DVSS-K06 (Axis 13 half-open temporal filtering via ``dle.temporal``),
and IR-06/US-12 source document registration. Never logs passage text.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from dle.errors import ContractValidationError
from dle.models.embeddings import EmbeddingService
from dle.observability import get_logger, sha256_text
from dle.store.repositories import EvidenceRepository
from dle.temporal import Interval, overlaps

AUTHORITY_PRIOR: dict[str, float] = {
    "primary_text": 1.00,
    "binding_instrument": 0.95,
    "peer_reviewed": 0.90,
    "industry_practice": 0.80,
    "app_tool": 0.75,
    "google_builtin_tool": 0.70,
    "unhydrated_synthesis": 0.35,
}

QUALIFYING_BINDING_CLASSES: frozenset[str] = frozenset(
    {"binding_instrument", "primary_text", "peer_reviewed"}
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "under",
        "was",
        "were",
        "with",
    }
)


@dataclass(frozen=True)
class RetrievedPassage:
    """Hydrated passage record carrying provenance, interval, and retrieval score."""

    passage_id: str
    source_id: str
    title: str
    authority_class: str
    revision: str
    locator: str
    content_sha256: str
    text: str
    valid_from: str | None
    valid_to: str | None
    jurisdiction: str | None
    is_retainable: bool
    retrieved_utc: str
    score: float
    active_in_scope: bool


@dataclass(frozen=True)
class RetrievalResult:
    """Result envelope for a ``DVSS-K05`` / ``DVSS-K06`` retrieval operation."""

    idempotency_key: str
    attempted: bool
    succeeded: bool
    from_cache: bool
    passages: tuple[RetrievedPassage, ...]
    excluded_temporal: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class AuthorityCheckResult:
    """Binding-claim authority check status per ``DVSS-K05``."""

    claim_id: str
    status: Literal["verified", "not_found", "unavailable", "not_applicable"]
    supporting_passage_ids: tuple[str, ...]
    reason: str


def chunk_document_text(text: str, *, max_chars: int = 800) -> tuple[str, ...]:
    """Split text deterministically on paragraphs and boundaries into non-empty chunks."""
    if max_chars < 64:
        raise ValueError("max_chars must be >= 64")
    cleaned = text.strip()
    if not cleaned:
        raise ContractValidationError(
            "document content must not be empty",
            file_path="source",
            pointer="/content",
        )
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    chunks: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            chunks.append(para)
            continue
        start = 0
        while start < len(para):
            end = min(len(para), start + max_chars)
            if end < len(para):
                split_at = para.rfind(" ", start, end)
                if split_at > start + max_chars // 3:
                    end = split_at
            piece = para[start:end].strip()
            if piece:
                chunks.append(piece)
            start = end
    return tuple(chunks)


def _validate_interval_dates(
    valid_from: str | None,
    valid_to: str | None,
) -> tuple[str, str | None]:
    eff_from = valid_from or datetime.now(UTC).date().isoformat()
    try:
        start_d = date.fromisoformat(eff_from)
    except ValueError as exc:
        raise ContractValidationError(
            f"invalid validFrom date {eff_from!r}",
            file_path="source",
            pointer="/validFrom",
        ) from exc

    end_d: date | None = None
    if valid_to is not None:
        try:
            end_d = date.fromisoformat(valid_to)
        except ValueError as exc:
            raise ContractValidationError(
                f"invalid validTo date {valid_to!r}",
                file_path="source",
                pointer="/validTo",
            ) from exc
    try:
        iv = Interval(start_d, end_d, "date")
    except ValueError as exc:
        raise ContractValidationError(
            f"invalid half-open interval [{eff_from}, {valid_to}): {exc}",
            file_path="source",
            pointer="/validTo",
        ) from exc
    return iv.start.isoformat(), (iv.end.isoformat() if iv.end is not None else None)


def _passage_overlaps_scope(row: dict[str, object], scope: Interval | None) -> bool:
    if scope is None:
        return True
    raw_from = row.get("valid_from")
    raw_to = row.get("valid_to")
    if not isinstance(raw_from, str) or not raw_from:
        return False
    start_d = date.fromisoformat(raw_from)
    end_d = date.fromisoformat(raw_to) if isinstance(raw_to, str) and raw_to else None
    passage_iv = Interval(start_d, end_d, "date")
    return overlaps(passage_iv, scope)


def _keywords(text: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if tok not in _STOPWORDS}


class EvidenceService:
    """Controlled evidence acquisition, indexing, temporal filtering, and authority checks."""

    def __init__(self, repo: EvidenceRepository, embeddings: EmbeddingService) -> None:
        """Bind service to persistent ``EvidenceRepository`` and ``EmbeddingService``."""
        self._repo = repo
        self._embeddings = embeddings
        self._lock = threading.Lock()
        self._idempotency_cache: dict[str, RetrievalResult] = {}
        self._log = get_logger("dle.host.services.evidence")

    async def register_document(
        self,
        *,
        title: str,
        authority_class: str,
        content_text: str,
        jurisdiction: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        retainable: bool = True,
        revision: str = "rev-1",
        source_id: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, object]:
        """Validate, chunk, embed, and persist an evidence document in ``evidence.db``."""
        if authority_class not in AUTHORITY_PRIOR:
            raise ContractValidationError(
                f"invalid authorityClass {authority_class!r}",
                file_path="source",
                pointer="/authorityClass",
            )
        norm_from, norm_to = _validate_interval_dates(valid_from, valid_to)
        chunks = chunk_document_text(content_text)
        vectors = await self._embeddings.embed_batch(chunks, api_key=api_key)

        eff_source_id = source_id or str(uuid.uuid4())
        now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._repo.register_source(
            source_id=eff_source_id,
            title=title,
            authority_class=authority_class,
            jurisdiction=jurisdiction,
            is_retainable=retainable,
            registered_utc=now_utc,
        )
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True), start=1):
            locator = f"p{idx:03d}"
            passage_id = f"{eff_source_id}@{revision}#{locator}"
            self._repo.insert_passage(
                passage_id=passage_id,
                source_id=eff_source_id,
                revision=revision,
                locator=locator,
                content_sha256=sha256_text(chunk),
                body_text=chunk,
                valid_from=norm_from,
                valid_to=norm_to,
                retrieved_utc=now_utc,
                embedding=vec,
            )

        self._log.info(
            "evidence.source_registered",
            source_id=eff_source_id,
            authority_class=authority_class,
            revision=revision,
            chunk_count=len(chunks),
        )
        return {
            "sourceId": eff_source_id,
            "title": title,
            "authorityClass": authority_class,
            "revision": revision,
            "validFrom": norm_from,
            "validTo": norm_to,
            "retainable": retainable,
        }

    async def retrieve(
        self,
        *,
        query: str,
        scope_interval: Interval | None = None,
        limit: int = 8,
        idempotency_key: str | None = None,
        api_key: str | None = None,
    ) -> RetrievalResult:
        """Run hybrid FTS5 + ``sqlite-vec`` retrieval with ``DVSS-K05`` idempotency & K06 dates."""
        if limit < 1:
            raise ValueError("limit must be >= 1")
        eff_key = idempotency_key or sha256_text(
            f"{query}|{scope_interval.start.isoformat() if scope_interval else '*'}"
            f"|{scope_interval.end.isoformat() if scope_interval and scope_interval.end else '*'}"
            f"|{limit}"
        )
        with self._lock:
            cached = self._idempotency_cache.get(eff_key)
        if cached is not None:
            return RetrievalResult(
                idempotency_key=eff_key,
                attempted=False,
                succeeded=cached.succeeded,
                from_cache=True,
                passages=cached.passages,
                excluded_temporal=cached.excluded_temporal,
            )

        start = time.perf_counter()
        candidate_k = max(limit * 3, 20)
        fts_hits = self._repo.search_fts(query, limit=candidate_k)
        query_vec = await self._embeddings.embed_text(query, api_key=api_key)
        vec_hits = self._repo.search_vec(query_vec, limit=candidate_k)

        rows_by_id: dict[str, dict[str, object]] = {}
        rrf_scores: dict[str, float] = {}

        for rank, (row, _bm25) in enumerate(fts_hits, start=1):
            pid = str(row["passage_id"])
            rows_by_id[pid] = row
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (60.0 + rank)

        for rank, (row, _dist) in enumerate(vec_hits, start=1):
            pid = str(row["passage_id"])
            rows_by_id[pid] = row
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (60.0 + rank)

        retained: list[RetrievedPassage] = []
        excluded: list[dict[str, str]] = []
        ranked_ids = sorted(rows_by_id, key=lambda pid: (-rrf_scores[pid], pid))

        for pid in ranked_ids:
            row = rows_by_id[pid]
            if not _passage_overlaps_scope(row, scope_interval):
                excluded.append({"passage_id": pid, "reason": "out_of_scope_temporal"})
                continue
            retained.append(
                RetrievedPassage(
                    passage_id=pid,
                    source_id=str(row["source_id"]),
                    title=str(row["title"]),
                    authority_class=str(row["authority_class"]),
                    revision=str(row["revision"]),
                    locator=str(row["locator"]),
                    content_sha256=str(row["content_sha256"]),
                    text=str(row["text"]),
                    valid_from=str(row["valid_from"]) if row["valid_from"] is not None else None,
                    valid_to=str(row["valid_to"]) if row["valid_to"] is not None else None,
                    jurisdiction=(
                        str(row["jurisdiction"]) if row["jurisdiction"] is not None else None
                    ),
                    is_retainable=bool(row["is_retainable"]),
                    retrieved_utc=str(row["retrieved_utc"]),
                    score=round(rrf_scores[pid], 6),
                    active_in_scope=True,
                )
            )
            if len(retained) >= limit:
                break

        result = RetrievalResult(
            idempotency_key=eff_key,
            attempted=True,
            succeeded=True,
            from_cache=False,
            passages=tuple(retained),
            excluded_temporal=tuple(excluded),
        )
        with self._lock:
            self._idempotency_cache[eff_key] = result

        self._log.info(
            "evidence.retrieve",
            idempotency_key=eff_key[:16],
            fts_count=len(fts_hits),
            vec_count=len(vec_hits),
            retained_count=len(retained),
            excluded_count=len(excluded),
            duration_ms=round((time.perf_counter() - start) * 1000.0, 3),
        )
        return result

    def verify_binding_authority(
        self,
        *,
        claim_id: str,
        assertion: str,
        binding: bool,
        passages: Sequence[RetrievedPassage],
        attached_passage_ids: Sequence[str] = (),
        source_unavailable: bool = False,
    ) -> AuthorityCheckResult:
        """Check whether a binding claim has an active qualifying authority passage (`DVSS-K05`)."""
        if not binding:
            return AuthorityCheckResult(
                claim_id=claim_id,
                status="not_applicable",
                supporting_passage_ids=(),
                reason="claim is non-binding",
            )
        if source_unavailable:
            return AuthorityCheckResult(
                claim_id=claim_id,
                status="unavailable",
                supporting_passage_ids=(),
                reason="authority source was unavailable during verification",
            )

        attached = set(attached_passage_ids)
        claim_terms = _keywords(assertion)
        qualifying_ids: list[str] = []

        for passage in passages:
            if not passage.active_in_scope:
                continue
            if passage.authority_class not in QUALIFYING_BINDING_CLASSES:
                continue
            if attached and passage.passage_id not in attached:
                continue
            overlap = len(claim_terms & _keywords(passage.text))
            if attached or overlap >= 1 or not claim_terms:
                qualifying_ids.append(passage.passage_id)

        if qualifying_ids:
            return AuthorityCheckResult(
                claim_id=claim_id,
                status="verified",
                supporting_passage_ids=tuple(qualifying_ids),
                reason="verified against active qualifying authority source",
            )
        return AuthorityCheckResult(
            claim_id=claim_id,
            status="not_found",
            supporting_passage_ids=(),
            reason="no active qualifying authority passage found in scope",
        )


__all__ = [
    "AUTHORITY_PRIOR",
    "QUALIFYING_BINDING_CLASSES",
    "AuthorityCheckResult",
    "EvidenceService",
    "RetrievalResult",
    "RetrievedPassage",
    "chunk_document_text",
]
