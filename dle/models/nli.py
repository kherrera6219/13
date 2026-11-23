"""Independent NLI entailment scorer interface and implementations (``M3``, ADR-006).

Implements FR-VER-02 with an independent non-generator scorer abstraction:
``DeterministicLexicalNliScorer`` for offline deterministic CI/dev runs and
``OnnxNliScorer`` for SHA-256 verified DeBERTa-v3 ONNX inference.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import onnxruntime as ort

from dle.errors import ConfigError

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
_NEGATION_TERMS: frozenset[str] = frozenset(
    {
        "cannot",
        "cant",
        "denied",
        "denies",
        "deny",
        "disallow",
        "disallowed",
        "disallows",
        "excluded",
        "expired",
        "forbid",
        "forbidden",
        "forbids",
        "invalid",
        "never",
        "no",
        "not",
        "prohibit",
        "prohibited",
        "prohibiting",
        "prohibits",
        "refused",
        "unauthorized",
    }
)


@dataclass(frozen=True)
class NliScore:
    """Normalized NLI probability triple ``(entailment, contradiction, neutral)``."""

    entailment: float
    contradiction: float
    neutral: float

    def __post_init__(self) -> None:  # noqa: D105
        for name, val in (
            ("entailment", self.entailment),
            ("contradiction", self.contradiction),
            ("neutral", self.neutral),
        ):
            if val < -1e-6 or val > 1.0 + 1e-6:
                raise ValueError(f"{name} probability out of [0, 1]: {val}")


class NliScorer(Protocol):
    """Protocol implemented by all independent NLI scorers."""

    @property
    def is_loaded(self) -> bool:
        """Whether the scorer backend is ready for inference."""
        ...

    @property
    def model_id(self) -> str:
        """Pinned NLI scorer identifier."""
        ...

    def score(self, premise: str, hypothesis: str) -> NliScore:
        """Score whether ``premise`` entails or contradicts ``hypothesis``."""
        ...

    def score_batch(self, pairs: Sequence[tuple[str, str]]) -> list[NliScore]:
        """Score a batch of ``(premise, hypothesis)`` text pairs."""
        ...


def _normalize_probs(e: float, c: float, n: float) -> NliScore:
    total = e + c + n
    if total <= 0.0:
        return NliScore(entailment=0.0, contradiction=0.0, neutral=1.0)
    return NliScore(
        entailment=round(e / total, 6),
        contradiction=round(c / total, 6),
        neutral=round(max(0.0, 1.0 - round(e / total, 6) - round(c / total, 6)), 6),
    )


def _content_and_negations(text: str) -> tuple[set[str], bool]:
    tokens = _TOKEN_RE.findall(text.lower())
    has_neg = any(tok in _NEGATION_TERMS for tok in tokens)
    content = {tok for tok in tokens if tok not in _STOPWORDS and tok not in _NEGATION_TERMS}
    return content, has_neg


def _numeric_tokens(tokens: set[str]) -> set[str]:
    return {t for t in tokens if any(ch.isdigit() for ch in t)}


class DeterministicLexicalNliScorer:
    """Offline deterministic NLI scorer for dev, CI, and fallback verification."""

    @property
    def is_loaded(self) -> bool:
        """Always ready without external model weights."""
        return True

    @property
    def model_id(self) -> str:
        """Stable identifier for lexical deterministic NLI scorer."""
        return "deterministic-lexical-nli-v1"

    def score(self, premise: str, hypothesis: str) -> NliScore:
        """Score lexical entailment vs negation/numeric contradiction deterministically."""
        p_tokens, p_neg = _content_and_negations(premise)
        h_tokens, h_neg = _content_and_negations(hypothesis)
        if not p_tokens or not h_tokens:
            return NliScore(entailment=0.0, contradiction=0.0, neutral=1.0)

        overlap = len(p_tokens & h_tokens)
        coverage = overlap / len(h_tokens)

        p_nums = _numeric_tokens(p_tokens)
        h_nums = _numeric_tokens(h_tokens)
        numeric_conflict = bool(h_nums and p_nums and not (h_nums <= p_nums) and coverage >= 0.35)

        if (p_neg != h_neg and coverage >= 0.35) or numeric_conflict:
            contra = min(0.95, 0.72 + 0.23 * coverage)
            rem = 1.0 - contra
            return _normalize_probs(0.2 * rem, contra, 0.8 * rem)

        if coverage >= 0.60:
            ent = min(0.96, 0.75 + 0.21 * ((coverage - 0.60) / 0.40))
            rem = 1.0 - ent
            return _normalize_probs(ent, 0.1 * rem, 0.9 * rem)

        if coverage >= 0.25:
            ent = 0.30 + 0.40 * ((coverage - 0.25) / 0.35)
            neu = max(0.05, 0.95 - ent)
            return _normalize_probs(ent, 0.05, neu)

        return _normalize_probs(0.05 + 0.15 * coverage, 0.05, 0.90 - 0.15 * coverage)

    def score_batch(self, pairs: Sequence[tuple[str, str]]) -> list[NliScore]:
        """Score each ``(premise, hypothesis)`` pair cleanly."""
        return [self.score(p, h) for p, h in pairs]


def _softmax3(logits: Sequence[float]) -> tuple[float, float, float]:
    vals = [float(x) for x in logits[:3]]
    m = max(vals)
    exps = [math.exp(x - m) for x in vals]
    s = sum(exps) or 1.0
    return (exps[0] / s, exps[1] / s, exps[2] / s)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class OnnxNliScorer:
    """SHA-256 verified ONNX DeBERTa-v3 NLI scorer (`ADR-006`)."""

    def __init__(
        self,
        *,
        model_path: Path,
        expected_sha256: str,
        tokenizer: Callable[[str, str], Mapping[str, Sequence[int]]] | None = None,
        label_order: tuple[str, str, str] = ("entailment", "neutral", "contradiction"),
        model_id: str = "deberta-v3-nli-onnx",
        session: Any | None = None,  # noqa: ANN401
    ) -> None:
        """Verify ONNX file digest and load ``onnxruntime.InferenceSession``."""
        if not expected_sha256 or len(expected_sha256) != 64:
            raise ConfigError(
                "OnnxNliScorer requires a 64-hex expected_sha256 pin (ADR-006)",
                code="DLE-E1001",
            )
        if not model_path.is_file():
            raise ConfigError(
                f"ONNX NLI model file missing: {model_path}",
                code="DLE-E1001",
            )
        actual_sha = _sha256_file(model_path)
        if actual_sha.lower() != expected_sha256.lower():
            raise ConfigError(
                f"ONNX NLI SHA-256 mismatch for {model_path.name}: "
                f"expected {expected_sha256}, got {actual_sha}",
                code="DLE-E1001",
            )

        self._model_id = model_id
        self._label_order = label_order
        self._tokenizer = tokenizer
        self._session = (
            session
            if session is not None
            else ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        )

    @property
    def is_loaded(self) -> bool:
        """Return ``True`` once verified session is loaded."""
        return self._session is not None

    @property
    def model_id(self) -> str:
        """Configured NLI model identifier."""
        return self._model_id

    def _encode(self, premise: str, hypothesis: str) -> dict[str, Any]:
        if self._tokenizer is not None:
            encoded = self._tokenizer(premise, hypothesis)
            return {k: np.asarray([list(v)], dtype=np.int64) for k, v in encoded.items()}
        # Fallback hashed token ID encoding when testing with fixed-input ONNX graphs.
        p_ids = [101] + [1000 + (abs(hash(t)) % 29000) for t in premise.split()[:62]] + [102]
        h_ids = [1000 + (abs(hash(t)) % 29000) for t in hypothesis.split()[:61]] + [102]
        ids = (p_ids + h_ids)[:128]
        mask = [1] * len(ids)
        return {
            "input_ids": np.asarray([ids], dtype=np.int64),
            "attention_mask": np.asarray([mask], dtype=np.int64),
        }

    def score(self, premise: str, hypothesis: str) -> NliScore:
        """Run ONNX inference on ``(premise, hypothesis)`` and return normalized probabilities."""
        feeds = self._encode(premise, hypothesis)
        input_names = {inp.name for inp in self._session.get_inputs()}
        filtered = {k: v for k, v in feeds.items() if not input_names or k in input_names}
        outputs = self._session.run(None, filtered)
        logits_arr = np.asarray(outputs[0], dtype=np.float64).reshape(-1)
        p0, p1, p2 = _softmax3(logits_arr.tolist())
        by_label = {
            self._label_order[0]: p0,
            self._label_order[1]: p1,
            self._label_order[2]: p2,
        }
        return _normalize_probs(
            by_label.get("entailment", 0.0),
            by_label.get("contradiction", 0.0),
            by_label.get("neutral", 0.0),
        )

    def score_batch(self, pairs: Sequence[tuple[str, str]]) -> list[NliScore]:
        """Run ONNX inference across a batch of pairs."""
        return [self.score(p, h) for p, h in pairs]


__all__ = [
    "DeterministicLexicalNliScorer",
    "NliScore",
    "NliScorer",
    "OnnxNliScorer",
]
