"""Hybrid Intake Router (``H2``, ``DVSS-K10``) and Tier Call Budget enforcement.

Implements FR-TIER-01..04, DLE-SPC-002 (D/R/M/B/Z intake scoring), and
``config/tiers.yaml`` call limits (9/21 Tier 1, 18/22 Tier 2, 18 Tier 3).
Model rationale is stored internally on ``IntakeDecision`` and stripped from
public response metadata.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from dle.config.models import TiersConfig, TierSpec
from dle.errors import ConfigError
from dle.models.embeddings import EmbeddingService
from dle.models.port import ModelPort
from dle.models.registry import ModelRegistry

INTAKE_PROMPT_VERSION = "intake-1.0.0"

DEONTIC_PREDICATES: tuple[str, ...] = (
    "may",
    "must",
    "shall",
    "prohibited",
    "approve",
    "authorize",
    "permitted",
    "required",
    "compliant",
)

_DEONTIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (term, re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)) for term in DEONTIC_PREDICATES
)

_CONFLICT_RULE_TERMS: tuple[str, ...] = (
    "conflict",
    "contradict",
    "preemption",
    "mutually exclusive",
    "extraterritorial",
    "cross-jurisdiction",
)

_BINDING_FRAMEWORK_TERMS: tuple[str, ...] = (
    "statute",
    "treaty",
    "gdpr",
    "compliance",
    "regulatory",
    "regulation",
    "binding",
    "mandatory",
    "prohibit",
    "enforceable",
)

_VOLUNTARY_GUIDANCE_TERMS: tuple[str, ...] = (
    "policy",
    "guidance",
    "technical standard",
    "safety standard",
    "compliance standard",
    "guideline",
    "iso",
    "sop",
    "audit",
    "advisory",
    "operating procedure",
)

_INTAKE_SYSTEM_INSTRUCTION = (
    "Score a normalized user query for DLE Hybrid Intake Triage (DLE-SPC-002 / DVSS-K10).\n"
    "Output strict JSON with keys: R (integer 0..3), M (integer 0..3), "
    "binding_flag (boolean), rationale (concise string).\n\n"
    "Band definitions (paper section 07):\n"
    "- R (regulatory exposure, 0..3):\n"
    "  0 = none (pure technical/factual lookup with no policy or regulatory nexus)\n"
    "  1 = voluntary guidance (internal policy, SOP, technical standard, advisory)\n"
    "  2 = binding framework (statute, enforceable regulation, formal compliance obligation)\n"
    "  3 = cross-framework conflict "
    "(contradictory statutes, preemption, multi-jurisdiction conflict)\n"
    "- M (ambiguity, 0..3) with anchored examples per band:\n"
    "  0 = lookup: e.g. 'What is the maximum operating temperature listed on Datasheet X?', "
    "'Which IEC connector pin carries 24V?', 'What hours is Depot 4 staffed?'\n"
    "  1 = comparison: e.g. 'Compare aluminum vs steel conduit under Spec A.', "
    "'Contrast throughput of Candidate A versus Candidate B.', "
    "'Distinguish Section 3.1 inspection cadence from Section 3.4.'\n"
    "  2 = conditional or multi-period decision: e.g. 'May Candidate B ship if Q3 exemption "
    "applies under the 2025 vs 2026 rules?', 'When does the temporary variance expire depending "
    "on volume?', "
    "'Resolve whether Phase 2 signoff transfers under prior-period contract amendments.'\n"
    "  3 = open counterfactual: e.g. 'What if dual cooling loops fail simultaneously under "
    "storm surge?', "
    "'Simulate cascading outage across interconnected hubs if interlock checks are bypassed.', "
    "'Assess worst-case failure chain if an irreversible commitment executes without approval.'\n"
    "Set binding_flag=true if the query requests authorization, compliance certification, "
    "obligation creation, or safety interlock bypass/override."
)


def _clamp_band(val: object, *, default: int = 0) -> int:
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int | float):
        return max(0, min(3, round(float(val))))
    return default


def _normalize_vec(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm <= 0.0:
        return [0.0 for _ in values]
    return [v / norm for v in values]


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    return max(-1.0, min(1.0, dot))


def _extract_response_text(body: Mapping[str, object]) -> str:
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    if not isinstance(first, Mapping):
        return ""
    content = first.get("content")
    if not isinstance(content, Mapping):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, Mapping) and not part.get("thought"):
            val = part.get("text")
            if isinstance(val, str):
                chunks.append(val)
    return "\n".join(chunks).strip()


def _extract_usage_tokens(body: Mapping[str, object]) -> tuple[int, int, int, int]:
    usage = body.get("usageMetadata")
    if not isinstance(usage, Mapping):
        return 0, 0, 0, 0

    def _int_val(key: str) -> int:
        raw = usage.get(key)
        return int(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else 0

    return (
        _int_val("promptTokenCount"),
        _int_val("candidatesTokenCount"),
        _int_val("cachedContentTokenCount"),
        _int_val("thoughtsTokenCount"),
    )


def detect_deontic_predicates(query_str: str) -> tuple[str, ...]:
    """Return canonical deontic predicates matched on word boundaries in ``query_str``."""
    return tuple(term for term, pattern in _DEONTIC_PATTERNS if pattern.search(query_str))


def band_pillar_count(distinct_pillars: int) -> int:
    """Map distinct Axis 1 pillar count to paper §07 ``D`` band ``0..3``."""
    if distinct_pillars <= 1:
        return 0
    if distinct_pillars == 2:
        return 1
    if distinct_pillars <= 4:
        return 2
    return 3


def score_r_rules(
    *,
    query_str: str,
    coordinate: Mapping[str, object] | None = None,
    matched_sources: Sequence[Mapping[str, object]] = (),
) -> tuple[int, tuple[str, ...]]:
    """Compute auditable rule floor ``R_rules`` (0..3) and rule evidence labels."""
    r_floor = 0
    reasons: list[str] = []
    lower = f" {query_str.lower()} "

    if coordinate is not None:
        hubs = coordinate.get("axis_6_octopus")
        meshes = coordinate.get("axis_7_spiderweb")
        jurs = coordinate.get("axis_12_jurisdiction")
        jur_state = str(coordinate.get("jurisdiction_state", "unscoped"))
        has_hub = isinstance(hubs, list) and len(hubs) > 0
        has_mesh = isinstance(meshes, list) and len(meshes) > 0
        jur_count = len(jurs) if isinstance(jurs, list) else 0

        if has_hub:
            reasons.append("axis6_hub")
            r_floor = max(r_floor, 2 if jur_state == "specified" else 1)
        if has_mesh:
            reasons.append("axis7_crosswalk")
            r_floor = max(r_floor, 2)
        if jur_count >= 2:
            reasons.append("multi_jurisdiction")
            r_floor = max(r_floor, 3)

    for src in matched_sources:
        auth = str(src.get("authorityClass") or src.get("authority_class") or "").strip().lower()
        if auth == "binding_instrument":
            if "binding_source" not in reasons:
                reasons.append("binding_source")
            r_floor = max(r_floor, 2)

    if any(term in lower for term in _CONFLICT_RULE_TERMS):
        reasons.append("rule_conflict")
        r_floor = max(r_floor, 3)
    elif any(term in lower for term in _BINDING_FRAMEWORK_TERMS):
        reasons.append("rule_binding_framework")
        r_floor = max(r_floor, 2)
    elif any(term in lower for term in _VOLUNTARY_GUIDANCE_TERMS):
        reasons.append("rule_guidance")
        r_floor = max(r_floor, 1)

    return r_floor, tuple(reasons)


def build_intake_request(query_str: str) -> dict[str, object]:
    """Construct temperature-0 Gemini request for ``job='intake'`` scoring."""
    user_prompt = (
        f"Score the query below for R, M, and binding_flag.\n<query>\n{query_str.strip()}\n</query>"
    )
    return {
        "systemInstruction": {"parts": [{"text": _INTAKE_SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }


def parse_intake_model_output(raw_text: str) -> tuple[int, int, bool, str]:
    """Parse ``{R, M, binding_flag, rationale}`` JSON safely with conservative fallback."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return 0, 1, False, "intake_parse_fallback"
    if not isinstance(parsed, Mapping):
        return 0, 1, False, "intake_non_object_fallback"
    r_val = _clamp_band(parsed.get("R"), default=0)
    m_val = _clamp_band(parsed.get("M"), default=0)
    binding_flag = bool(parsed.get("binding_flag", False))
    rationale = str(parsed.get("rationale", "")).strip() or "none"
    return r_val, m_val, binding_flag, rationale


@dataclass(frozen=True)
class FailureCentroidCluster:
    """Single development failure-mode cluster with exemplar phrases."""

    cluster_id: str
    description: str
    exemplars: tuple[str, ...]


class FailureCentroidCatalog:
    """Curated development failure-centroid index scored with pinned embeddings."""

    def __init__(
        self,
        *,
        schema_version: str,
        threshold: float,
        clusters: Sequence[FailureCentroidCluster],
    ) -> None:
        """Initialize threshold and cluster exemplar definitions."""
        if not 0.0 < threshold <= 1.0:
            raise ConfigError(f"centroid threshold must be in (0, 1], got {threshold}")
        self.schema_version = schema_version
        self.threshold = float(threshold)
        self.clusters: tuple[FailureCentroidCluster, ...] = tuple(clusters)
        self._centroid_cache: dict[str, dict[str, list[float]]] = {}

    async def _ensure_centroids(
        self,
        embedding_service: EmbeddingService,
        *,
        model_id: str,
        api_key: str | None = None,
    ) -> dict[str, list[float]]:
        if model_id in self._centroid_cache:
            return self._centroid_cache[model_id]
        vectors_by_cluster: dict[str, list[float]] = {}
        for cluster in self.clusters:
            if not cluster.exemplars:
                continue
            exemplar_vecs = await embedding_service.embed_batch(
                cluster.exemplars,
                api_key=api_key,
            )
            dims = len(exemplar_vecs[0])
            summed = [
                sum(vec[idx] for vec in exemplar_vecs) / float(len(exemplar_vecs))
                for idx in range(dims)
            ]
            vectors_by_cluster[cluster.cluster_id] = _normalize_vec(summed)
        self._centroid_cache[model_id] = vectors_by_cluster
        return vectors_by_cluster

    async def score_query(
        self,
        query_str: str,
        embedding_service: EmbeddingService,
        *,
        model_id: str,
        api_key: str | None = None,
    ) -> tuple[int, float, str | None]:
        """Compute ``(z_hit, max_cosine, matched_centroid_id)`` via pinned embeddings."""
        if not self.clusters or not query_str.strip():
            return 0, 0.0, None
        centroids = await self._ensure_centroids(
            embedding_service,
            model_id=model_id,
            api_key=api_key,
        )
        if not centroids:
            return 0, 0.0, None
        query_vec = await embedding_service.embed_text(query_str, api_key=api_key)
        best_id: str | None = None
        best_cos = -1.0
        for cluster_id, centroid_vec in centroids.items():
            cos = _cosine_similarity(query_vec, centroid_vec)
            if cos > best_cos:
                best_cos = cos
                best_id = cluster_id
        best_cos = round(best_cos, 6)
        z_hit = 1 if best_cos >= self.threshold else 0
        return z_hit, best_cos, (best_id if z_hit else None)


def load_failure_centroids(path: Path) -> FailureCentroidCatalog:
    """Load curated development failure centroids YAML from ``path``."""
    if not path.is_file():
        raise ConfigError(f"missing failure centroid file: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ConfigError(f"centroid catalog root must be mapping: {path}")
    schema_version = str(loaded.get("schema_version", "1.0.0"))
    threshold = float(loaded.get("threshold", 0.55))
    raw_clusters = loaded.get("centroids", [])
    if not isinstance(raw_clusters, list) or not raw_clusters:
        raise ConfigError(f"centroid catalog must list >= 1 centroids: {path}")
    clusters: list[FailureCentroidCluster] = []
    for entry in raw_clusters:
        if not isinstance(entry, Mapping):
            raise ConfigError("each failure centroid entry must be a mapping")
        cid = str(entry.get("id", "")).strip()
        desc = str(entry.get("description", "")).strip()
        raw_ex = entry.get("exemplars", [])
        if not cid or not isinstance(raw_ex, list) or not raw_ex:
            raise ConfigError(f"invalid failure centroid entry {cid!r}")
        exemplars = tuple(str(x).strip() for x in raw_ex if str(x).strip())
        clusters.append(
            FailureCentroidCluster(cluster_id=cid, description=desc, exemplars=exemplars)
        )
    return FailureCentroidCatalog(
        schema_version=schema_version,
        threshold=threshold,
        clusters=clusters,
    )


@dataclass(frozen=True)
class IntakeDecision:
    """Complete ``H2`` intake evaluation including stored internal rationale."""

    d: int
    r_rules: int
    r_model: int
    r_final: int
    m: int
    b: int
    z: int
    s: int
    s_eff: int
    tier: int
    active_roles: tuple[str, ...]
    starting_hops: int
    max_model_calls: int
    max_model_calls_escalated: int
    has_axis7: bool
    pillar_count: int
    deontic_hits: tuple[str, ...]
    r_rule_reasons: tuple[str, ...]
    z_max_cosine: float
    z_matched_centroid: str | None
    model_binding_flag: bool
    rationale: str
    model_id: str
    model_version: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: float

    def to_k10_payload(self) -> dict[str, object]:
        """Build input dictionary passed to ``DVSS-K10`` (rationale omitted)."""
        return {
            "d": self.d,
            "r": self.r_final,
            "m": self.m,
            "binding": bool(self.b),
            "z_hit": bool(self.z),
            "has_axis7": self.has_axis7,
            "evidence": self.to_public_metadata(),
        }

    def to_public_metadata(self) -> dict[str, object]:
        """Serialize intake scores & evidence for receipts/responses without ``rationale``."""
        return {
            "promptVersion": INTAKE_PROMPT_VERSION,
            "d": self.d,
            "rRules": self.r_rules,
            "rModel": self.r_model,
            "rFinal": self.r_final,
            "m": self.m,
            "b": self.b,
            "z": self.z,
            "s": self.s,
            "sEff": self.s_eff,
            "tier": self.tier,
            "activeRoles": list(self.active_roles),
            "startingHops": self.starting_hops,
            "maxModelCalls": self.max_model_calls,
            "maxModelCallsEscalated": self.max_model_calls_escalated,
            "pillarCount": self.pillar_count,
            "deonticHits": list(self.deontic_hits),
            "rRuleReasons": list(self.r_rule_reasons),
            "zMaxCosine": self.z_max_cosine,
            "zMatchedCentroid": self.z_matched_centroid,
            "modelBindingFlag": self.model_binding_flag,
        }


def resolve_tier_spec(tiers_config: TiersConfig, tier: int) -> TierSpec:
    """Return configured ``TierSpec`` matching ``tier`` (1..3)."""
    for spec in tiers_config.tiers:
        if spec.tier == tier:
            return spec
    raise ConfigError(f"missing tier {tier} specification in config/tiers.yaml")


def _tier_from_s_eff(tiers_config: TiersConfig, s_eff: int) -> TierSpec:
    for spec in sorted(tiers_config.tiers, key=lambda item: item.tier):
        low, high = spec.s_eff
        if low <= s_eff <= high:
            return spec
    return resolve_tier_spec(tiers_config, 3)


def _roles_for_tier(
    spec: TierSpec,
    *,
    b_flag: int,
    z_flag: int,
    r_final: int,
    has_axis7: bool,
) -> tuple[str, ...]:
    if spec.roles == "all_when_b_or_z_else_relevant":
        if b_flag or z_flag:
            return ("scholar", "practitioner", "regulator", "harmonizer")
        roles: list[str] = ["scholar", "practitioner"]
        if r_final >= 1:
            roles.append("regulator")
        if has_axis7:
            roles.append("harmonizer")
        return tuple(roles)
    roles_out = list(spec.roles)
    if b_flag and "regulator" not in roles_out:
        roles_out.append("regulator")
    if spec.tier == 2 and has_axis7 and "harmonizer" not in roles_out:
        roles_out.append("harmonizer")
    return tuple(roles_out)


def safe_compute_cost(
    registry: ModelRegistry,
    model_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    thought_tokens: int = 0,
    model_version: str | None = None,
) -> float:
    """Meter token USD cost via ``ModelRegistry``, falling back to 0.0 for synthetic test pins."""
    try:
        usage = registry.compute_cost(
            model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            thought_tokens=thought_tokens,
            model_version=model_version,
        )
        return round(usage.cost_usd, 8)
    except ConfigError:
        return 0.0


class ModelCallBudget:
    """Tracks and enforces per-tier model call ceilings from ``config/tiers.yaml``."""

    def __init__(self, tiers_config: TiersConfig, *, initial_tier: int) -> None:
        """Initialize budget for ``initial_tier``."""
        self._tiers_config = tiers_config
        spec = resolve_tier_spec(tiers_config, initial_tier)
        self.tier: int = spec.tier
        self.base_limit: int = spec.max_model_calls
        self.escalated_limit: int = spec.max_model_calls_escalated or spec.max_model_calls
        self.escalated: bool = False
        self.used: int = 0

    @property
    def limit(self) -> int:
        """Return active model call budget ceiling accounting for one-time escalation."""
        return self.escalated_limit if self.escalated else self.base_limit

    def remaining(self) -> int:
        """Return non-negative remaining model calls in budget."""
        return max(0, self.limit - self.used)

    def can_spend(self, calls_needed: int = 1) -> bool:
        """Return True if spending ``calls_needed`` stays within the active tier ceiling."""
        return (self.used + max(0, calls_needed)) <= self.limit

    def record_call(self, calls: int = 1) -> int:
        """Consume ``calls`` from the active budget and return updated total."""
        self.used += max(0, calls)
        return self.used

    def on_escalate(self, next_tier: int | None = None) -> int:
        """Apply post-escalation call ceiling and return the updated limit."""
        self.escalated = True
        if next_tier is not None and next_tier != self.tier:
            prev_spec = resolve_tier_spec(self._tiers_config, self.tier)
            next_spec = resolve_tier_spec(self._tiers_config, next_tier)
            self.tier = next_spec.tier
            self.escalated_limit = max(
                prev_spec.max_model_calls_escalated or prev_spec.max_model_calls,
                next_spec.max_model_calls,
            )
        return self.limit


@dataclass
class IntakeRouter:
    """Hybrid Intake Router (``H2`` / ``DVSS-K10``) combining rules, LLM, and centroids."""

    tiers_config: TiersConfig
    model_registry: ModelRegistry
    model_port: ModelPort
    embedding_service: EmbeddingService
    centroid_catalog: FailureCentroidCatalog | None = field(default=None)

    async def evaluate(
        self,
        *,
        query_str: str,
        coordinate: Mapping[str, object] | None = None,
        matched_sources: Sequence[Mapping[str, object]] = (),
        consequential_tool_hit: bool = False,
        api_key: str | None = None,
        override_model_scores: tuple[int, int, bool] | None = None,
        override_z: tuple[int, float, str | None] | None = None,
    ) -> IntakeDecision:
        """Evaluate ``query_str`` across ``D``, ``R``, ``M``, ``B``, and ``Z``."""
        t0 = time.perf_counter()

        raw_pillars = coordinate.get("axis_1_pillars") if coordinate is not None else None
        distinct_pillars = (
            {
                str(item.get("id", item)) if isinstance(item, Mapping) else str(item)
                for item in raw_pillars
            }
            if isinstance(raw_pillars, list)
            else set()
        )
        pillar_count = len(distinct_pillars)
        d_band = band_pillar_count(pillar_count)

        raw_meshes = coordinate.get("axis_7_spiderweb") if coordinate is not None else None
        has_axis7 = isinstance(raw_meshes, list) and len(raw_meshes) > 0

        r_rules, r_reasons = score_r_rules(
            query_str=query_str,
            coordinate=coordinate,
            matched_sources=matched_sources,
        )
        deontic_hits = detect_deontic_predicates(query_str)

        model_id = self.model_registry.pin_for_job("intake")
        model_version: str | None = None
        in_tok = 0
        out_tok = 0
        call_cost = 0.0
        if override_model_scores is not None:
            raw_rm, raw_mm, raw_bm = override_model_scores
            r_model = _clamp_band(raw_rm)
            m_band = _clamp_band(raw_mm)
            model_binding_flag = bool(raw_bm)
            rationale = "override_model_scores"
        else:
            req_payload = build_intake_request(query_str)
            res = await self.model_port.generate(
                model_id,
                req_payload,
                api_key=api_key,
                job="intake",
            )
            model_version = res.model_version
            in_tok, out_tok, cached_tok, thought_tok = _extract_usage_tokens(res.body)
            raw_text = _extract_response_text(res.body)
            r_model, m_band, model_binding_flag, rationale = parse_intake_model_output(raw_text)
            call_cost = safe_compute_cost(
                self.model_registry,
                model_id,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cached_input_tokens=cached_tok,
                thought_tokens=thought_tok,
                model_version=model_version,
            )

        if override_z is not None:
            z_flag, z_cos, z_centroid = override_z
        elif self.centroid_catalog is not None:
            emb_model = self.model_registry.pin_for_job("embeddings")
            z_flag, z_cos, z_centroid = await self.centroid_catalog.score_query(
                query_str,
                self.embedding_service,
                model_id=emb_model,
                api_key=api_key,
            )
        else:
            z_flag, z_cos, z_centroid = 0, 0.0, None

        r_final = max(r_rules, r_model)
        b_flag = (
            1
            if (deontic_hits or r_final >= 2 or model_binding_flag or consequential_tool_hit)
            else 0
        )
        s_score = d_band + r_final + m_band
        s_eff = max(s_score, 3 * b_flag, 6 * z_flag)

        tier_spec = _tier_from_s_eff(self.tiers_config, s_eff)
        roles = _roles_for_tier(
            tier_spec,
            b_flag=b_flag,
            z_flag=z_flag,
            r_final=r_final,
            has_axis7=has_axis7,
        )
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)

        return IntakeDecision(
            d=d_band,
            r_rules=r_rules,
            r_model=r_model,
            r_final=r_final,
            m=m_band,
            b=b_flag,
            z=z_flag,
            s=s_score,
            s_eff=s_eff,
            tier=tier_spec.tier,
            active_roles=roles,
            starting_hops=tier_spec.starting_hops,
            max_model_calls=tier_spec.max_model_calls,
            max_model_calls_escalated=(
                tier_spec.max_model_calls_escalated or tier_spec.max_model_calls
            ),
            has_axis7=has_axis7,
            pillar_count=pillar_count,
            deontic_hits=deontic_hits,
            r_rule_reasons=r_reasons,
            z_max_cosine=z_cos,
            z_matched_centroid=z_centroid,
            model_binding_flag=model_binding_flag,
            rationale=rationale,
            model_id=model_id,
            model_version=model_version,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=call_cost,
            duration_ms=duration_ms,
        )


__all__ = [
    "DEONTIC_PREDICATES",
    "INTAKE_PROMPT_VERSION",
    "FailureCentroidCatalog",
    "FailureCentroidCluster",
    "IntakeDecision",
    "IntakeRouter",
    "ModelCallBudget",
    "band_pillar_count",
    "build_intake_request",
    "detect_deontic_predicates",
    "load_failure_centroids",
    "parse_intake_model_output",
    "resolve_tier_spec",
    "safe_compute_cost",
    "score_r_rules",
]
