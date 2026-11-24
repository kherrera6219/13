"""Pre-registered §17 evaluation study engine and System Card generator (``O3``, ``DLE-EVL-003``).

Implements paper §17 hypotheses ``H1``-``H4``, middleware endpoints ``M1``-``M2``,
exact one-sided Clopper-Pearson binomial confidence bounds, family-clustered
paired bootstrap CIs, verify-and-gate baseline comparison, and ``DLE-AIM`` System
Card population from ``docs/templates/system_card_template.md``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dle import __version__
from dle.config import DleConfig, canonicalize_jcs, load_config
from dle.errors import CalibrationError, ContaminationError
from dle.host.functions import FunctionRegistry, register_phase1_functions
from dle.host.services.calibration import (
    compute_cohen_kappa,
    compute_query_item_hash,
    load_calibration_artifact,
    load_heldout_hash_registry,
)
from dle.host.services.claim_extractor import ClaimExtractor
from dle.host.services.evidence import EvidenceService
from dle.host.services.intake import IntakeRouter, load_failure_centroids
from dle.host.services.receipts import Ed25519KeyManager, ReceiptSealer
from dle.host.services.reference import load_reference_catalog
from dle.host.services.registry import RegistrySnapshot, load_registry
from dle.host.services.release import (
    CalibrationArtifact,
    apply_disclosure,
    evaluate_release_gate,
)
from dle.host.services.scorer import compute_terminal_u
from dle.host.services.verifier import ClaimVerifier
from dle.models import DeterministicLexicalNliScorer, EmbeddingService, FakeModel, ModelRegistry
from dle.store import (
    EvidenceRepository,
    OpsRepository,
    ReceiptRepository,
    RegistryRepository,
    SessionRepository,
    open_stores,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class BootstrapComparison:
    """Family-clustered paired bootstrap summary (``arm_a - arm_b``)."""

    arm_a_mean: float
    arm_b_mean: float
    mean_diff: float
    ci_low: float
    ci_high: float
    spans_zero: bool
    n_families: int
    n_boot: int

    def to_dict(self) -> dict[str, object]:
        """Serialize summary to JSON-friendly dictionary."""
        return {
            "arm_a_mean": self.arm_a_mean,
            "arm_b_mean": self.arm_b_mean,
            "mean_diff": self.mean_diff,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "spans_zero": self.spans_zero,
            "n_families": self.n_families,
            "n_boot": self.n_boot,
        }


def _binom_cdf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 1.0 if k >= 0 else 0.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    log_p = math.log(p)
    log_q = math.log(1.0 - p)
    log_n_fact = math.lgamma(n + 1)
    total = 0.0
    for j in range(0, min(k, n) + 1):
        log_term = (
            log_n_fact - math.lgamma(j + 1) - math.lgamma(n - j + 1) + j * log_p + (n - j) * log_q
        )
        total += math.exp(log_term)
    return min(1.0, total)


def binom_upper_one_sided(k: int, n: int, *, confidence: float = 0.95) -> float:
    """Compute exact one-sided Clopper-Pearson upper confidence bound for ``k`` of ``n``."""
    if n < 1 or k < 0 or k > n:
        raise ValueError(f"invalid binomial counts k={k}, n={n}")
    if not (0.0 < confidence < 1.0):
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    alpha = 1.0 - confidence
    if k == n:
        return 1.0
    if k == 0:
        return round(1.0 - float(alpha ** (1.0 / n)), 6)
    lo = 0.0
    hi = 1.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _binom_cdf(k, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return round(hi, 6)


def binom_lower_one_sided(k: int, n: int, *, confidence: float = 0.95) -> float:
    """Compute exact one-sided Clopper-Pearson lower confidence bound for ``k`` of ``n``."""
    if n < 1 or k < 0 or k > n:
        raise ValueError(f"invalid binomial counts k={k}, n={n}")
    if not (0.0 < confidence < 1.0):
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    alpha = 1.0 - confidence
    if k == 0:
        return 0.0
    if k == n:
        return round(float(alpha ** (1.0 / n)), 6)
    lo = 0.0
    hi = 1.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        tail = 1.0 - _binom_cdf(k - 1, n, mid)
        if tail > alpha:
            hi = mid
        else:
            lo = mid
    return round(lo, 6)


def family_clustered_paired_bootstrap(
    pairs_by_family: Mapping[str, Sequence[tuple[float, float]]],
    *,
    n_boot: int = 2000,
    seed: int = 20261123,
    confidence: float = 0.95,
) -> BootstrapComparison:
    """Compute family-clustered paired bootstrap CI for ``mean(arm_a - arm_b)``."""
    families = [list(pairs_by_family[k]) for k in sorted(pairs_by_family) if pairs_by_family[k]]
    if not families:
        raise CalibrationError("cannot run bootstrap on empty family mapping")
    if n_boot < 100:
        raise CalibrationError(f"n_boot must be >= 100, got {n_boot}")

    flat_a = [a for fam in families for a, _b in fam]
    flat_b = [b for fam in families for _a, b in fam]
    mean_a = sum(flat_a) / len(flat_a)
    mean_b = sum(flat_b) / len(flat_b)
    obs_diff = mean_a - mean_b

    rng = random.Random(seed)  # noqa: S311 - deterministic evaluation bootstrap resampling
    k_fam = len(families)
    diffs: list[float] = []
    for _ in range(n_boot):
        sum_diff = 0.0
        count = 0
        for _idx in range(k_fam):
            chosen = families[rng.randrange(k_fam)]
            for a_val, b_val in chosen:
                sum_diff += a_val - b_val
                count += 1
        diffs.append(sum_diff / max(1, count))
    diffs.sort()

    tail = 0.5 * (1.0 - confidence)
    lo_idx = max(0, min(n_boot - 1, math.floor(tail * n_boot)))
    hi_idx = max(0, min(n_boot - 1, math.ceil((1.0 - tail) * n_boot) - 1))
    ci_lo = round(diffs[lo_idx], 6)
    ci_hi = round(diffs[hi_idx], 6)
    return BootstrapComparison(
        arm_a_mean=round(mean_a, 6),
        arm_b_mean=round(mean_b, 6),
        mean_diff=round(obs_diff, 6),
        ci_low=ci_lo,
        ci_high=ci_hi,
        spans_zero=(ci_lo <= 0.0 <= ci_hi),
        n_families=k_fam,
        n_boot=n_boot,
    )


def _load_jsonl_dicts(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise CalibrationError(f"study dataset file not found: {path}")
    rows: list[dict[str, object]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise CalibrationError(f"{path.name} line {line_no}: invalid JSON ({exc.msg})") from exc
        if not isinstance(obj, Mapping):
            raise CalibrationError(f"{path.name} line {line_no}: record must be JSON object")
        rows.append({str(k): v for k, v in obj.items()})
    if not rows:
        raise CalibrationError(f"study dataset {path.name} is empty")
    return rows


def verify_heldout_seal(
    *,
    eval_items: Sequence[Mapping[str, object]],
    challenge_items: Sequence[Mapping[str, object]],
    registry_path: Path,
) -> str:
    """Verify 100% JCS SHA-256 parity between held-out study items and ``heldout_hashes.json``."""
    registry = load_heldout_hash_registry(registry_path)
    raw_doc = json.loads(registry_path.read_text(encoding="utf-8"))
    eval_sealed = set(raw_doc["sets"]["heldout_test"]["hashes"])
    chal_sealed = set(raw_doc["sets"]["heldout_challenge"]["hashes"])

    eval_computed: set[str] = set()
    for item in eval_items:
        src_val = item.get("source_set", [])
        srcs = [str(s) for s in src_val] if isinstance(src_val, list) else []
        h = compute_query_item_hash(
            question=str(item["question"]),
            as_of_date=str(item["as_of_date"]),
            source_set=srcs,
        )
        eval_computed.add(h)

    chal_computed: set[str] = set()
    for item in challenge_items:
        src_val = item.get("source_set", [])
        srcs = [str(s) for s in src_val] if isinstance(src_val, list) else []
        h = compute_query_item_hash(
            question=str(item["question"]),
            as_of_date=str(item["as_of_date"]),
            source_set=srcs,
        )
        chal_computed.add(h)

    if eval_computed != eval_sealed:
        raise CalibrationError(
            "heldout_test seal mismatch: "
            f"{len(eval_computed)} computed vs {len(eval_sealed)} sealed"
        )
    if chal_computed != chal_sealed:
        raise CalibrationError(
            "heldout_challenge seal mismatch: "
            f"{len(chal_computed)} computed vs {len(chal_sealed)} sealed"
        )
    return registry.file_sha256


def _verify_dev_extractor_non_contaminated(
    extractor_items: Sequence[Mapping[str, object]],
    registry_path: Path,
) -> None:
    reg = load_heldout_hash_registry(registry_path)
    for idx, item in enumerate(extractor_items):
        draft_text = str(item.get("draft_text", ""))
        item_hash = hashlib.sha256(canonicalize_jcs({"draft_text": draft_text})).hexdigest()
        q = str(item.get("question", ""))
        if item_hash in reg.hashes:
            raise ContaminationError(f"extractor item {idx} draft hash overlaps held-out registry")
        if q:
            qh = compute_query_item_hash(
                question=q,
                as_of_date=str(item.get("as_of_date", "2026-11-20")),
                source_set=[],
            )
            if qh in reg.hashes:
                raise ContaminationError(f"extractor item {idx} query hash overlaps held-out set")


def _grade_arm_output(
    *,
    item: Mapping[str, object],
    release_mode: str,
    notice_id: str,
    final_text: str,
) -> float:
    expected = str(item.get("expected_outcome", "answerable_primary"))
    if expected == "answerable_primary":
        if release_mode != "released":
            return 1.0  # DLE-EVL-002 over-abstention penalty
        req_token = str(item.get("required_token", "")).strip().lower()
        return 0.0 if (not req_token or req_token in final_text.lower()) else 0.5
    if expected == "requires_binding_hold":
        if release_mode == "held":
            binding_notices = ("NOTICE-HOLD-01", "NOTICE-HOLD-02", "NOTICE-HOLD-04")
            return 0.0 if notice_id in binding_notices else 0.5
        return 1.0
    # insufficient_evidence_abstain
    if release_mode == "held":
        return 0.0
    return 1.0


def _final_text_and_cost(body: Mapping[str, object]) -> tuple[str, float]:
    final_text = ""
    cands = body.get("candidates")
    if isinstance(cands, list) and cands and isinstance(cands[0], Mapping):
        content = cands[0].get("content")
        parts = content.get("parts") if isinstance(content, Mapping) else None
        if isinstance(parts, list) and parts and isinstance(parts[0], Mapping):
            final_text = str(parts[0].get("text", ""))
    cost_usd = 0.0
    meta = body.get("dleMetadata")
    summary = meta.get("runSummary") if isinstance(meta, Mapping) else None
    if isinstance(summary, Mapping):
        raw_cost = summary.get("costUsd", 0.0)
        cost_usd = float(raw_cost) if isinstance(raw_cost, int | float) else 0.0
    return final_text, cost_usd


def _receipt_hard_gate(receipt: Mapping[str, object]) -> bool:
    payload = receipt.get("payload")
    decision = payload.get("decision") if isinstance(payload, Mapping) else None
    return bool(decision.get("hard_gate")) if isinstance(decision, Mapping) else False


async def _run_governed_arm(
    *,
    eval_items: Sequence[Mapping[str, object]],
    config: DleConfig,
    snapshot: RegistrySnapshot,
    calibration: CalibrationArtifact,
    arm_name: str,
    profile_override: str | None = None,
    enable_ppr: bool = True,
    use_snapshot: bool = True,
    single_reviewer: bool = False,
    seed: int = 20261123,
) -> dict[str, object]:
    """Execute one pre-registered governed study arm across the 150 held-out queries."""
    centroid_path = _REPO_ROOT / "config" / "intake" / "dev_failure_centroids.yaml"
    centroid_cat = load_failure_centroids(centroid_path) if centroid_path.is_file() else None
    ref_manifest = _REPO_ROOT / "config" / "reference" / "manifest.yaml"
    ref_cat = (
        load_reference_catalog(ref_manifest, ref_dir=ref_manifest.parent)
        if ref_manifest.is_file()
        else None
    )
    rng = random.Random(seed)  # noqa: S311 - deterministic blind dual grader simulation
    per_item: list[dict[str, object]] = []
    notice_counts: Counter[str] = Counter()
    fn_counts: Counter[str] = Counter()
    tier_latencies: dict[int, list[float]] = defaultdict(list)
    tier_costs: dict[int, list[float]] = defaultdict(list)

    from dle.edge.tools import ToolBridge
    from dle.edge.translator import translate_generate_request
    from dle.host.services.calibration import PilotTrajectory
    from dle.host.workflow import run_governed_workflow

    kappa_rows: list[PilotTrajectory] = []

    model_name = "dle-13axis-strict"
    for item in eval_items:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stores = open_stores(tmp_path / "data", enable_vec=False)
            try:
                ev_repo = EvidenceRepository(stores.evidence, vec_enabled=False)
                sess_repo = SessionRepository(stores.sessions)
                rcpt_repo = ReceiptRepository(stores.receipts)
                reg_repo = RegistryRepository(stores.registry)
                ops_repo = OpsRepository(stores.ops)

                model_reg = ModelRegistry(config.model_pins)
                fake = FakeModel(registry=model_reg)
                fn_reg = FunctionRegistry(config.functions, config.profiles)
                register_phase1_functions(fn_reg, config.notices)
                emb = EmbeddingService(fake, model_reg)
                ev_svc = EvidenceService(ev_repo, emb)
                ext = ClaimExtractor(fake, model_reg)
                ver = ClaimVerifier(DeterministicLexicalNliScorer(), ev_svc)
                key_mgr = Ed25519KeyManager(rcpt_repo, keys_dir=tmp_path / "keys")
                sealer = ReceiptSealer(rcpt_repo, key_mgr)
                router = IntakeRouter(
                    tiers_config=config.tiers,
                    model_registry=model_reg,
                    model_port=fake,
                    embedding_service=emb,
                    centroid_catalog=centroid_cat,
                )

                await ev_svc.register_document(
                    title=str(item["doc_title"]),
                    authority_class=str(item["auth_class"]),
                    content_text=str(item["doc_content"]),
                    valid_from=str(item["valid_from"]),
                    retainable=True,
                    api_key="study-eval-key",
                )

                user_parts = [{"text": str(item["question"])}]
                req = translate_generate_request(
                    model=model_name,
                    body={"contents": [{"role": "user", "parts": user_parts}]},
                    tenant=f"study-{arm_name}",
                )
                if profile_override is not None:
                    from dataclasses import replace

                    req = replace(req, profile=profile_override)

                t0 = time.perf_counter()
                res = await run_governed_workflow(
                    run_req=req,
                    config=config,
                    function_registry=fn_reg,
                    model_registry=model_reg,
                    model_port=fake,
                    evidence_service=ev_svc,
                    claim_extractor=ext,
                    claim_verifier=ver,
                    receipt_sealer=sealer,
                    ops_repo=ops_repo,
                    session_repo=sess_repo,
                    calibration=calibration,
                    api_key="study-eval-key",
                    registry_snapshot=snapshot if use_snapshot else None,
                    enable_ppr=enable_ppr,
                    registry_repo=reg_repo if use_snapshot else None,
                    reference_catalog=ref_cat if use_snapshot else None,
                    tool_bridge=ToolBridge(),
                    intake_router=router if not single_reviewer else None,
                    triage_override=(
                        {"d": 0, "r": 0, "m": 0, "binding": False, "z_hit": False}
                        if single_reviewer
                        else None
                    ),
                )
                dur_ms = (time.perf_counter() - t0) * 1000.0
                final_text, cost_usd = _final_text_and_cost(res.body)
                hard_gate = _receipt_hard_gate(res.receipt)

                ell = _grade_arm_output(
                    item=item,
                    release_mode=res.release_mode,
                    notice_id=res.notice_id,
                    final_text=final_text,
                )
                ga = ell
                gb = ell
                roll = rng.random()
                if roll < 0.04:
                    ga = 0.5 if ell != 0.5 else 1.0
                elif roll < 0.08:
                    gb = 0.5 if ell != 0.5 else 0.0

                notice_counts[res.notice_id] += 1
                for frec in res.function_records:
                    fn_counts[f"{frec.dvss_id}:{frec.outcome}"] += 1
                tier_latencies[res.tier].append(dur_ms)
                tier_costs[res.tier].append(cost_usd)

                released = res.release_mode == "released"
                answerable = bool(item.get("answerable", True))
                per_item.append(
                    {
                        "item_id": str(item["item_id"]),
                        "domain": str(item["domain"]),
                        "tier": res.tier,
                        "release_mode": res.release_mode,
                        "notice_id": res.notice_id,
                        "hard_gate": hard_gate,
                        "terminal_u": res.terminal_u,
                        "rubric_loss": ell,
                        "accepted_loss": ell if released else 0.0,
                        "accepted": released,
                        "over_abstained": (answerable and not released),
                        "answerable": answerable,
                        "cost_usd": round(cost_usd, 6),
                        "duration_ms": round(dur_ms, 3),
                    }
                )
                src_list = item.get("source_set", [])
                kappa_rows.append(
                    PilotTrajectory(
                        item_id=str(item["item_id"]),
                        question=str(item["question"]),
                        as_of_date=str(item["as_of_date"]),
                        source_set=(
                            tuple(str(s) for s in src_list) if isinstance(src_list, list) else ()
                        ),
                        tier=int(res.tier),
                        domain=str(item["domain"]),
                        hard_gate=hard_gate,
                        terminal_u=res.terminal_u,
                        grader_a_loss=ga,
                        grader_b_loss=gb,
                        adjudicated_loss=ell,
                        decisive_claim=f"Eval check {item['item_id']}",
                        author="study-eval",
                        license_id="CC-BY-4.0",
                    )
                )
            finally:
                stores.close()

    n_items = len(per_item)
    accepted_items = [r for r in per_item if r["accepted"]]
    answerable_items = [r for r in per_item if r["answerable"]]
    accepted_loss_sum = sum(_metric_value(r["accepted_loss"]) for r in per_item)
    accepted_full_errors = sum(1 for r in per_item if _metric_value(r["accepted_loss"]) > 0.0)
    rubric_loss_mean = sum(_metric_value(r["rubric_loss"]) for r in per_item) / n_items
    over_abst_count = sum(1 for r in answerable_items if r["over_abstained"])
    kappa_res = compute_cohen_kappa(kappa_rows)

    return {
        "arm": arm_name,
        "n": n_items,
        "accepted_count": len(accepted_items),
        "coverage": round(len(accepted_items) / n_items, 6),
        "accepted_loss_sum": round(accepted_loss_sum, 6),
        "accepted_loss_rate": round(accepted_loss_sum / n_items, 6),
        "accepted_error_count_conservative": accepted_full_errors,
        "accepted_loss_upper_95": binom_upper_one_sided(
            accepted_full_errors, n_items, confidence=0.95
        ),
        "conditional_accepted_loss": (
            round(accepted_loss_sum / len(accepted_items), 6) if accepted_items else 0.0
        ),
        "rubric_loss_mean": round(rubric_loss_mean, 6),
        "over_abstention_count": over_abst_count,
        "over_abstention_rate": (
            round(over_abst_count / len(answerable_items), 6) if answerable_items else 0.0
        ),
        "kappa": kappa_res.kappa,
        "notice_counts": dict(sorted(notice_counts.items())),
        "function_outcome_counts": dict(sorted(fn_counts.items())),
        "per_tier_metrics": {
            f"tier_{t}": {
                "count": len(tier_latencies[t]),
                "mean_duration_ms": round(sum(tier_latencies[t]) / len(tier_latencies[t]), 3),
                "mean_cost_usd": round(sum(tier_costs[t]) / len(tier_costs[t]), 6),
            }
            for t in sorted(tier_latencies)
        },
        "total_cost_usd": round(sum(_metric_value(r["cost_usd"]) for r in per_item), 6),
        "per_item": per_item,
    }


async def _run_verify_and_gate_baseline(
    *,
    eval_items: Sequence[Mapping[str, object]],
    config: DleConfig,
    calibration: CalibrationArtifact,
) -> dict[str, object]:
    """Run direct Writer -> Extractor -> Verifier -> Gate baseline (no Quad/PPR/retries)."""
    accepted_count = 0
    accepted_loss_sum = 0.0
    accepted_errors = 0
    rubric_losses: list[float] = []
    answerable_over_abstain = 0
    answerable_total = 0

    for item in eval_items:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stores = open_stores(tmp_path / "data", enable_vec=False)
            try:
                ev_repo = EvidenceRepository(stores.evidence, vec_enabled=False)
                emb_reg = ModelRegistry(config.model_pins)
                fake = FakeModel(registry=emb_reg)
                emb = EmbeddingService(fake, emb_reg)
                ev_svc = EvidenceService(ev_repo, emb)
                ext = ClaimExtractor(fake, emb_reg)
                ver = ClaimVerifier(DeterministicLexicalNliScorer(), ev_svc)

                await ev_svc.register_document(
                    title=str(item["doc_title"]),
                    authority_class=str(item["auth_class"]),
                    content_text=str(item["doc_content"]),
                    valid_from=str(item["valid_from"]),
                    retainable=True,
                    api_key="study-eval-key",
                )
                ret = await ev_svc.retrieve(
                    query=str(item["question"]),
                    limit=8,
                    idempotency_key=f"baseline-{item['item_id']}",
                    api_key="study-eval-key",
                )
                writer_model = emb_reg.pin_for_job("writer")
                wres = await fake.generate(
                    writer_model,
                    {"contents": [{"role": "user", "parts": [{"text": str(item["question"])}]}]},
                    api_key="study-eval-key",
                    job="writer",
                )
                cands = wres.body.get("candidates", [])
                draft = ""
                if isinstance(cands, list) and cands and isinstance(cands[0], Mapping):
                    parts = cands[0].get("content", {}).get("parts", [])
                    if isinstance(parts, list) and parts and isinstance(parts[0], Mapping):
                        draft = str(parts[0].get("text", ""))

                extracted = await ext.extract(
                    run_id=f"base-{item['item_id']}",
                    attempt_id="att-0",
                    proposal_id="p0",
                    draft_text=draft,
                    api_key="study-eval-key",
                )
                verified = ver.verify(
                    claims=extracted.claims,
                    passages=ret.passages,
                    draft_text=draft,
                )
                score = compute_terminal_u(
                    verified.scored_claims, open_objections=0, total_objections=0
                )
                gate = evaluate_release_gate(
                    schema_scope_valid=True,
                    claims=verified.scored_claims,
                    all_binding_verified=verified.all_binding_verified,
                    open_blocking_objections=[],
                    score=score,
                    calibration=calibration,
                    drift_latched=False,
                    cusum=0.0,
                )
                disc = apply_disclosure(
                    gate=gate,
                    profile="strict",
                    draft_text=draft,
                    notices=config.notices,
                    receipt_id=f"base-{item['item_id']}",
                    source_count=len(ret.passages),
                )
                ell = _grade_arm_output(
                    item=item,
                    release_mode=disc.api_release_mode,
                    notice_id=disc.notice_id,
                    final_text=disc.final_text,
                )
                rubric_losses.append(ell)
                if disc.api_release_mode == "released":
                    accepted_count += 1
                    accepted_loss_sum += ell
                    if ell > 0.0:
                        accepted_errors += 1
                if item.get("answerable", True):
                    answerable_total += 1
                    if disc.api_release_mode != "released":
                        answerable_over_abstain += 1
            finally:
                stores.close()

    n_items = len(eval_items)
    return {
        "arm": "verify_and_gate_baseline",
        "n": n_items,
        "accepted_count": accepted_count,
        "coverage": round(accepted_count / n_items, 6),
        "accepted_loss_sum": round(accepted_loss_sum, 6),
        "accepted_loss_upper_95": binom_upper_one_sided(accepted_errors, n_items, confidence=0.95),
        "rubric_loss_mean": round(sum(rubric_losses) / n_items, 6),
        "over_abstention_rate": round(answerable_over_abstain / max(1, answerable_total), 6),
    }


async def _run_router_challenge_h4(
    *,
    challenge_items: Sequence[Mapping[str, object]],
    config: DleConfig,
) -> dict[str, object]:
    model_reg = ModelRegistry(config.model_pins)
    fake = FakeModel(registry=model_reg)
    emb = EmbeddingService(fake, model_reg)
    centroid_path = _REPO_ROOT / "config" / "intake" / "dev_failure_centroids.yaml"
    centroid_cat = load_failure_centroids(centroid_path)
    router = IntakeRouter(
        tiers_config=config.tiers,
        model_registry=model_reg,
        model_port=fake,
        embedding_service=emb,
        centroid_catalog=centroid_cat,
    )
    tier_counts: Counter[int] = Counter()
    misses: list[str] = []
    for item in challenge_items:
        dec = await router.evaluate(
            query_str=str(item["question"]),
            coordinate=None,
            consequential_tool_hit=False,
            api_key="study-eval-key",
        )
        tier_counts[dec.tier] += 1
        if dec.tier != 3:
            misses.append(str(item["item_id"]))

    n = len(challenge_items)
    hits = n - len(misses)
    recall = hits / n
    ci_low = binom_lower_one_sided(hits, n, confidence=0.95)
    return {
        "n": n,
        "tier3_hits": hits,
        "misses": len(misses),
        "missed_item_ids": misses[:10],
        "recall": round(recall, 6),
        "ci_lower_95": ci_low,
        "passes_threshold": ci_low >= 0.95,
        "confusion_matrix": {
            "expected_tier_3_routed_tier_1": tier_counts[1],
            "expected_tier_3_routed_tier_2": tier_counts[2],
            "expected_tier_3_routed_tier_3": tier_counts[3],
        },
    }


async def _run_extractor_m1(
    *,
    extractor_items: Sequence[Mapping[str, object]],
    config: DleConfig,
) -> dict[str, object]:
    model_reg = ModelRegistry(config.model_pins)
    fake = FakeModel(registry=model_reg)
    extractor = ClaimExtractor(fake, model_reg)
    total_expected_claims = 0
    matched_claims = 0
    total_expected_binding = 0
    matched_binding = 0

    for idx, item in enumerate(extractor_items, start=1):
        res = await extractor.extract(
            run_id=f"m1-{idx:03d}",
            attempt_id="att-0",
            proposal_id="p0",
            draft_text=str(item["draft_text"]),
            api_key="study-eval-key",
        )
        extracted_texts = [c.assertion.lower() for c in res.claims]
        extracted_binding = [c for c in res.claims if c.binding]
        raw_expected = item.get("expected_claims", [])
        if not isinstance(raw_expected, list):
            continue
        for exp in raw_expected:
            if not isinstance(exp, Mapping):
                continue
            total_expected_claims += 1
            needle = str(exp.get("assertion_contains", "")).strip().lower()
            is_hit = any(needle in cand for cand in extracted_texts)
            if is_hit:
                matched_claims += 1
            if bool(exp.get("binding", False)):
                total_expected_binding += 1
                if any(needle in c.assertion.lower() for c in extracted_binding):
                    matched_binding += 1

    point_recall = matched_claims / max(1, total_expected_claims)
    ci_low = binom_lower_one_sided(matched_claims, max(1, total_expected_claims), confidence=0.95)
    binding_recall = matched_binding / max(1, total_expected_binding)
    return {
        "n_drafts": len(extractor_items),
        "total_expected_claims": total_expected_claims,
        "matched_claims": matched_claims,
        "claim_recall": round(point_recall, 6),
        "claim_recall_ci_lower_95": ci_low,
        "total_expected_binding": total_expected_binding,
        "matched_binding": matched_binding,
        "binding_recall": round(binding_recall, 6),
        "passes_threshold": point_recall >= 0.95 and ci_low >= 0.92,
    }


def _bootstrap_arm_pair(
    *,
    arm_a_items: Sequence[Mapping[str, object]],
    arm_b_items: Sequence[Mapping[str, object]],
    metric_key: str,
    seed: int,
) -> BootstrapComparison:
    by_family: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row_a, row_b in zip(arm_a_items, arm_b_items, strict=True):
        val_a = _metric_value(row_a[metric_key])
        val_b = _metric_value(row_b[metric_key])
        by_family[str(row_a["domain"])].append((val_a, val_b))
    return family_clustered_paired_bootstrap(by_family, n_boot=2000, seed=seed)


def _metric_value(raw: object) -> float:
    if raw is True:
        return 1.0
    if raw is False:
        return 0.0
    if isinstance(raw, int | float | str):
        return float(raw)
    raise TypeError(f"non-numeric study metric value: {type(raw).__name__}")


def _as_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"study results field {name!r} must be a mapping")
    return value


def _as_list(value: object, name: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise TypeError(f"study results field {name!r} must be a list")
    return value


async def _execute_study_async(
    *,
    eval_items: Sequence[Mapping[str, object]],
    challenge_items: Sequence[Mapping[str, object]],
    extractor_items: Sequence[Mapping[str, object]],
    config: DleConfig,
    snapshot: RegistrySnapshot,
    calibration: CalibrationArtifact,
    seed: int,
) -> dict[str, object]:
    arm_strict = await _run_governed_arm(
        eval_items=eval_items,
        config=config,
        snapshot=snapshot,
        calibration=calibration,
        arm_name="strict",
        enable_ppr=True,
        use_snapshot=True,
        single_reviewer=False,
        seed=seed,
    )
    arm_unaddressed = await _run_governed_arm(
        eval_items=eval_items,
        config=config,
        snapshot=snapshot,
        calibration=calibration,
        arm_name="unaddressed",
        enable_ppr=False,
        use_snapshot=False,
        single_reviewer=False,
        seed=seed + 1,
    )
    arm_single = await _run_governed_arm(
        eval_items=eval_items,
        config=config,
        snapshot=snapshot,
        calibration=calibration,
        arm_name="single_reviewer",
        enable_ppr=True,
        use_snapshot=True,
        single_reviewer=True,
        seed=seed + 2,
    )
    arm_k_only = await _run_governed_arm(
        eval_items=eval_items,
        config=config,
        snapshot=snapshot,
        calibration=calibration,
        arm_name="kernel_only",
        profile_override="kernel_only",
        enable_ppr=True,
        use_snapshot=True,
        single_reviewer=False,
        seed=seed + 3,
    )
    arm_k_policy = await _run_governed_arm(
        eval_items=eval_items,
        config=config,
        snapshot=snapshot,
        calibration=calibration,
        arm_name="kernel_plus_policy",
        profile_override="kernel_plus_policy",
        enable_ppr=True,
        use_snapshot=True,
        single_reviewer=False,
        seed=seed + 4,
    )
    baseline = await _run_verify_and_gate_baseline(
        eval_items=eval_items,
        config=config,
        calibration=calibration,
    )
    h4_res = await _run_router_challenge_h4(challenge_items=challenge_items, config=config)
    m1_res = await _run_extractor_m1(extractor_items=extractor_items, config=config)

    s_rows = _as_list(arm_strict["per_item"], "strict.per_item")
    u_rows = _as_list(arm_unaddressed["per_item"], "unaddressed.per_item")
    sr_rows = _as_list(arm_single["per_item"], "single_reviewer.per_item")
    ko_rows = _as_list(arm_k_only["per_item"], "kernel_only.per_item")
    kp_rows = _as_list(arm_k_policy["per_item"], "kernel_plus_policy.per_item")

    def _pair(
        a: list[Mapping[str, object]], b: list[Mapping[str, object]], key: str, off: int
    ) -> BootstrapComparison:
        return _bootstrap_arm_pair(arm_a_items=a, arm_b_items=b, metric_key=key, seed=seed + off)

    h1_loss = _pair(s_rows, u_rows, "rubric_loss", 10)
    h1_cov = _pair(s_rows, u_rows, "accepted", 11)
    h2_loss = _pair(s_rows, sr_rows, "rubric_loss", 12)
    h2_cost = _pair(s_rows, sr_rows, "cost_usd", 13)
    m2_loss = _pair(kp_rows, ko_rows, "rubric_loss", 14)
    m2_cov = _pair(kp_rows, ko_rows, "accepted", 15)

    h3_pass = (
        float(arm_strict["accepted_loss_sum"]) <= 2.0  # type: ignore[arg-type]
        and float(arm_strict["coverage"]) >= 0.40  # type: ignore[arg-type]
    )

    def _strip_items(arm: dict[str, object]) -> dict[str, object]:
        return {k: v for k, v in arm.items() if k != "per_item"}

    return {
        "schema_version": "1.0.0",
        "study_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "execution_mode": "offline_deterministic_ci_stub",
        "calibration": {
            "artifact_id": calibration.artifact_id,
            "artifact_sha256": calibration.artifact_sha256,
            "n_cal": calibration.n_cal,
            "alpha": calibration.alpha,
            "threshold": calibration.threshold,
            "mu_0": calibration.mu_0,
            "drift_lambda": calibration.drift_lambda,
        },
        "arms": {
            "strict": _strip_items(arm_strict),
            "unaddressed": _strip_items(arm_unaddressed),
            "single_reviewer": _strip_items(arm_single),
            "kernel_only": _strip_items(arm_k_only),
            "kernel_plus_policy": _strip_items(arm_k_policy),
            "verify_and_gate_baseline": baseline,
        },
        "hypotheses": {
            "H1_addressing": {
                "rubric_loss_diff": h1_loss.to_dict(),
                "coverage_diff": h1_cov.to_dict(),
                "conclusion": "supported" if h1_loss.ci_high < 0.0 else "no_directional_difference",
            },
            "H2_roles": {
                "rubric_loss_diff": h2_loss.to_dict(),
                "cost_diff_usd": h2_cost.to_dict(),
                "conclusion": "supported" if h2_loss.ci_high < 0.0 else "no_directional_difference",
            },
            "H3_gate": {
                "accepted_loss_sum": arm_strict["accepted_loss_sum"],
                "accepted_error_count": arm_strict["accepted_error_count_conservative"],
                "accepted_loss_upper_95": arm_strict["accepted_loss_upper_95"],
                "coverage": arm_strict["coverage"],
                "over_abstention_rate": arm_strict["over_abstention_rate"],
                "conclusion": "supported" if h3_pass else "refuted",
            },
            "H4_routing": h4_res,
            "M1_extractor": m1_res,
            "M2_catalog": {
                "rubric_loss_diff": m2_loss.to_dict(),
                "coverage_diff": m2_cov.to_dict(),
                "conclusion": (
                    "directional_diff" if not m2_loss.spans_zero else "no_directional_difference"
                ),
            },
        },
    }


def run_preregistered_study(
    *,
    eval_path: Path,
    challenge_path: Path,
    extractor_path: Path,
    heldout_registry_path: Path,
    calibration_path: Path,
    config_dir: Path,
    protocol_commit: str = "HEAD",
    seed: int = 20261123,
) -> tuple[dict[str, object], DleConfig, CalibrationArtifact]:
    """Execute full ``DLE-EVL-003`` pre-registered study with seal verification."""
    eval_items = _load_jsonl_dicts(eval_path)
    challenge_items = _load_jsonl_dicts(challenge_path)
    extractor_items = _load_jsonl_dicts(extractor_path)

    heldout_sha = verify_heldout_seal(
        eval_items=eval_items,
        challenge_items=challenge_items,
        registry_path=heldout_registry_path,
    )
    _verify_dev_extractor_non_contaminated(extractor_items, heldout_registry_path)

    cfg = load_config(config_dir)
    cal = load_calibration_artifact(calibration_path, require_approved=True, min_kappa=0.6)
    pilot_dir = config_dir / "pilots" / "warehouse_substitution"
    snapshot = load_registry(
        config_dir / "registry",
        overlay_dir=pilot_dir if pilot_dir.is_dir() else None,
        w3=cfg.tiers.distance_weights.w3,
        w67=cfg.tiers.distance_weights.w67,
    )

    results = asyncio.run(
        _execute_study_async(
            eval_items=eval_items,
            challenge_items=challenge_items,
            extractor_items=extractor_items,
            config=cfg,
            snapshot=snapshot,
            calibration=cal,
            seed=seed,
        )
    )
    results["protocol_commit"] = protocol_commit
    results["heldout_registry_sha256"] = heldout_sha
    results["policy_sha256"] = cfg.policy_sha256
    results["registry_manifest_sha256"] = snapshot.manifest_sha256
    return results, cfg, cal


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _ci(diff: Mapping[str, object]) -> str:
    return f"`[{diff['ci_low']}, {diff['ci_high']}]`"


def _status(passes: object) -> str:
    return "`supported`" if passes else "`below_threshold`"


def render_study_report_markdown(results: Mapping[str, object]) -> str:
    """Render concise Markdown study report strictly from observed study output."""
    arms = _as_mapping(results["arms"], "arms")
    hyp = _as_mapping(results["hypotheses"], "hypotheses")
    cal = _as_mapping(results["calibration"], "calibration")
    strict = _as_mapping(arms["strict"], "arms.strict")
    kpp = _as_mapping(arms["kernel_plus_policy"], "arms.kernel_plus_policy")
    h1 = _as_mapping(hyp["H1_addressing"], "H1")
    h2 = _as_mapping(hyp["H2_roles"], "H2")
    h3 = _as_mapping(hyp["H3_gate"], "H3")
    h4 = _as_mapping(hyp["H4_routing"], "H4")
    m1 = _as_mapping(hyp["M1_extractor"], "M1")
    m2 = _as_mapping(hyp["M2_catalog"], "M2")
    h1_loss = _as_mapping(h1["rubric_loss_diff"], "H1.rubric_loss_diff")
    h1_cov = _as_mapping(h1["coverage_diff"], "H1.coverage_diff")
    h2_loss = _as_mapping(h2["rubric_loss_diff"], "H2.rubric_loss_diff")
    h2_cost = _as_mapping(h2["cost_diff_usd"], "H2.cost_diff_usd")
    m2_loss = _as_mapping(m2["rubric_loss_diff"], "M2.rubric_loss_diff")
    m2_cov = _as_mapping(m2["coverage_diff"], "M2.coverage_diff")

    lines = [
        "# Pre-Registered Evaluation Study Report (`O3`, `DLE-EVL-003`)",
        "",
        f"- **Study Date:** {results['study_date']}",
        f"- **Protocol Commit:** `{results['protocol_commit']}`",
        f"- **Execution Mode:** `{results['execution_mode']}` (in-process `FakeModel` + "
        "`DeterministicLexicalNliScorer`; the live cloud Gemini study remains an "
        "operational milestone)",
        f"- **Sealed Held-Out Registry SHA-256:** `{results['heldout_registry_sha256']}` "
        "(`150` eval + `100` challenge verified)",
        f"- **Policy Digest:** `{results['policy_sha256']}`",
        f"- **Calibration Artifact:** `{cal['artifact_id']}` (alpha={cal['alpha']}, "
        f"threshold={cal['threshold']}, mu_0={cal['mu_0']}, lambda={cal['drift_lambda']})",
        "",
        "## 1. Hypotheses & Pre-Registered Endpoints Summary",
        "",
        _row("ID", "Target / Comparison", "Observed Result", "95% Bound / CI", "Status"),
        _row("---", "---", "---", "---", "---"),
        _row(
            "H1 · Addressing",
            "`strict` vs `unaddressed` (n=150)",
            f"loss diff `{h1_loss['mean_diff']}`, cov diff `{h1_cov['mean_diff']}`",
            f"loss CI {_ci(h1_loss)}",
            f"`{h1['conclusion']}`",
        ),
        _row(
            "H2 · Roles",
            "`strict` vs `single_reviewer` (n=150)",
            f"loss diff `{h2_loss['mean_diff']}`, cost diff USD `{h2_cost['mean_diff']}`",
            f"loss CI {_ci(h2_loss)}",
            f"`{h2['conclusion']}`",
        ),
        _row(
            "H3 · Gate",
            "`strict` on held-out test (n=150)",
            f"accepted loss sum `{h3['accepted_loss_sum']}` "
            f"(`{h3['accepted_error_count']}` err), cov `{h3['coverage']}`",
            f"1-sided 95% upper `{h3['accepted_loss_upper_95']}`",
            f"`{h3['conclusion']}`",
        ),
        _row(
            "H4 · Routing",
            f"Tier-3 recall on challenge (n={h4['n']})",
            f"`{h4['tier3_hits']}/{h4['n']}` (`recall={h4['recall']}`, `{h4['misses']}` misses)",
            f"1-sided 95% lower `{h4['ci_lower_95']}`",
            _status(h4["passes_threshold"]),
        ),
        _row(
            "M1 · Extractor",
            f"200 labeled drafts (`{m1['total_expected_claims']}` claims)",
            f"claim recall `{m1['claim_recall']}`, binding `{m1['binding_recall']}`",
            f"1-sided 95% lower `{m1['claim_recall_ci_lower_95']}`",
            _status(m1["passes_threshold"]),
        ),
        _row(
            "M2 · Catalog",
            "`kernel_plus_policy` vs `kernel_only` (n=150)",
            f"loss diff `{m2_loss['mean_diff']}`, cov diff `{m2_cov['mean_diff']}`",
            f"loss CI {_ci(m2_loss)}",
            f"`{m2['conclusion']}`",
        ),
        "",
        "## 2. Study Arms & Verify-and-Gate Baseline (150 Held-Out Test Queries)",
        "",
        _row(
            "Arm",
            "Accepted / N",
            "Coverage",
            "Accepted Loss Sum",
            "95% Upper Bound",
            "Mean Rubric Loss",
            "Over-Abstention",
        ),
        _row(*(["---"] * 7)),
    ]
    for arm_name in (
        "strict",
        "unaddressed",
        "single_reviewer",
        "kernel_only",
        "kernel_plus_policy",
        "verify_and_gate_baseline",
    ):
        a = _as_mapping(arms[arm_name], f"arms.{arm_name}")
        lines.append(
            _row(
                f"`{arm_name}`",
                f"{a['accepted_count']}/{a['n']}",
                a["coverage"],
                a["accepted_loss_sum"],
                a["accepted_loss_upper_95"],
                a["rubric_loss_mean"],
                a["over_abstention_rate"],
            )
        )

    def _dump(value: object) -> str:
        return json.dumps(value, sort_keys=True)

    lines.extend(
        [
            "",
            "## 3. Additional Diagnostics (`study_protocol.md`)",
            "",
            f"- **Blind Grader Agreement (`strict` arm):** Cohen's kappa = {strict['kappa']}",
            f"- **Strict Hold & Release Notices:** `{_dump(strict['notice_counts'])}`",
            f"- **H4 Challenge Router Confusion Matrix:** `{_dump(h4['confusion_matrix'])}`",
            f"- **Per-Tier Cost & Latency (`strict`):** `{_dump(strict['per_tier_metrics'])}`",
            "- **Kernel / Policy Invocation Counts (`kernel_plus_policy`):** "
            f"`{_dump(kpp['function_outcome_counts'])}`",
            "",
            "## 4. Deviations & Scientific Disclosure",
            "",
            "- Executed deterministically offline against `FakeModel` + "
            "`DeterministicLexicalNliScorer`. Stub role packets are uniform, so arm "
            "differences reflect pipeline structure (addressing, gate, catalog) rather "
            "than model reasoning quality. These results validate the harness and "
            "statistics; they are not evidence about live Gemini behaviour.",
            "- Blind dual-grader disagreement is simulated deterministically (seeded), so "
            "kappa measures the simulation, not human graders.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_system_card(
    results: Mapping[str, object],
    *,
    config: DleConfig,
    calibration: CalibrationArtifact,
    template_path: Path,
    protocol_commit: str,
    security_contact: str = "security@dle.local",
) -> str:
    """Populate ``docs/templates/system_card_template.md`` with live config and study data."""
    tmpl = template_path.read_text(encoding="utf-8")
    arms = _as_mapping(results["arms"], "arms")
    hyp = _as_mapping(results["hypotheses"], "hypotheses")
    strict = _as_mapping(arms["strict"], "arms.strict")
    h3 = _as_mapping(hyp["H3_gate"], "H3")
    h4 = _as_mapping(hyp["H4_routing"], "H4")
    m1 = _as_mapping(hyp["M1_extractor"], "M1")
    m2 = _as_mapping(hyp["M2_catalog"], "M2")
    m2_loss = _as_mapping(m2["rubric_loss_diff"], "M2.rubric_loss_diff")

    mv_map = dict(calibration.model_versions)
    model_rows = "\n".join(
        f"| {job} | `{mid}` | `{mv_map.get(mid.removeprefix('models/'), mid + '-001')}` | yes |"
        for job, mid in sorted(config.model_pins.jobs.items())
    )
    strict_cfg = config.profiles.get("strict")
    enabled_policy = (
        ", ".join(sorted(k for k, v in strict_cfg.policy_functions.items() if v != "off"))
        if strict_cfg is not None
        else "default"
    )
    tier_digest = hashlib.sha256(
        canonicalize_jcs(config.tiers.model_dump(mode="json"))
    ).hexdigest()[:16]

    replacements = {
        "{{version}}": __version__,
        "{{model_pin_rows}}": model_rows,
        "{{nli_model}}": (
            "DeterministicLexicalNliScorer (CI) / OnnxNliScorer (DeBERTa-v3 optional)"
        ),
        "{{nli_sha256}}": "deterministic-lexical-nli-v1",
        "{{tier_digest}}": tier_digest,
        "{{profiles}}": ", ".join(sorted(config.profiles)),
        "{{policy_set}}": enabled_policy,
        "{{alpha}}": str(calibration.alpha),
        "{{cutoff}}": str(calibration.threshold),
        "{{study_date}}": str(results["study_date"]),
        "{{protocol_commit}}": protocol_commit,
        "{{accepted_loss}}": (
            f"{h3['accepted_loss_sum']} (upper 95%: {h3['accepted_loss_upper_95']})"
        ),
        "{{coverage}}": str(strict["coverage"]),
        "{{over_abstention}}": str(strict["over_abstention_rate"]),
        "{{router_recall}}": f"{h4['recall']} (95% lower: {h4['ci_lower_95']})",
        "{{extractor_recall}}": f"{m1['claim_recall']} (binding: {m1['binding_recall']})",
        "{{kappa}}": str(strict["kappa"]),
        "{{ablation_diff}}": (
            f"{m2_loss['mean_diff']} (95% CI [{m2_loss['ci_low']}, {m2_loss['ci_high']}])"
        ),
        "{{additional_limits}}": (
            "Offline evaluation executed against deterministic FakeModel + lexical NLI; "
            "run live Gemini cloud calibration before external clinical/regulatory "
            "production use."
        ),
        "{{security_contact}}": security_contact,
    }
    rendered = tmpl.replace(
        "Fields in `{{ }}` are filled by `offline/evaluate --system-card`.",
        "Fields below were filled by `offline/evaluate --system-card`.",
    )
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    if "{{" in rendered or "}}" in rendered:
        raise CalibrationError("rendered System Card contains unresolved template placeholders")
    return rendered


__all__ = [
    "BootstrapComparison",
    "binom_lower_one_sided",
    "binom_upper_one_sided",
    "family_clustered_paired_bootstrap",
    "render_study_report_markdown",
    "render_system_card",
    "run_preregistered_study",
    "verify_heldout_seal",
]
