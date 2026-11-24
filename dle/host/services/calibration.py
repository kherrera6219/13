"""Offline calibration, CRC cutoff selection, CUSUM tuning, and loader (``O1``, ``DVSS-P14``).

Implements FR-REL-01..04, paper §16b finite-sample Conformal Risk Control (CRC),
§16c fixed-baseline CUSUM ARL calibration, DLE-EVL-001 held-out contamination
sealing, and DLE-EVL-002 three-level Cohen's kappa inter-rater reliability checks.
"""

from __future__ import annotations

import bisect
import hashlib
import hmac
import json
import math
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import jsonschema

from dle.config.loader import canonicalize_jcs
from dle.errors import CalibrationError, ContaminationError
from dle.host.services.release import CalibrationArtifact

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CALIBRATION_SCHEMA = _REPO_ROOT / "contracts" / "calibration.schema.json"
_DEFAULT_P14_IN_SCHEMA = _REPO_ROOT / "contracts" / "functions" / "p14.in.json"
_DEFAULT_P14_OUT_SCHEMA = _REPO_ROOT / "contracts" / "functions" / "p14.out.json"
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
VALID_LOSS_LEVELS: tuple[float, ...] = (0.0, 0.5, 1.0)
VALID_VOLATILITY_CLASSES: frozenset[str] = frozenset({"stable", "technical", "amended"})


@dataclass(frozen=True)
class HeldoutHashRegistry:
    """Committed SHA-256 registry of sealed held-out evaluation query hashes."""

    schema_version: str
    file_sha256: str
    hashes: frozenset[str]
    counts_by_set: dict[str, int]


@dataclass(frozen=True)
class PilotTrajectory:
    """Single graded calibration trajectory tuple ``(H, u, l_A, l_B, l_adj)``."""

    item_id: str
    question: str
    as_of_date: str
    source_set: tuple[str, ...]
    tier: int
    domain: str
    hard_gate: bool
    terminal_u: float
    grader_a_loss: float
    grader_b_loss: float
    adjudicated_loss: float
    decisive_claim: str
    author: str
    license_id: str
    volatility_class: str = "technical"
    query_hash: str | None = None


@dataclass(frozen=True)
class KappaResult:
    """Three-level Cohen's kappa inter-rater agreement metrics (``DLE-EVL-002``)."""

    kappa: float
    exact_agreement: float
    expected_agreement: float
    adjudication_rate: float
    confusion_matrix: dict[str, dict[str, int]]


@dataclass(frozen=True)
class CrcResult:
    """Finite-sample Conformal Risk Control cutoff selection output (paper §16b)."""

    threshold: float
    n_cal: int
    alpha: float
    grid_step: float
    accepted_count: int
    empirical_coverage: float
    accepted_loss_sum: float
    corrected_risk: float
    conditional_accepted_loss: float


@dataclass(frozen=True)
class CusumCalibrationResult:
    """Fixed-baseline CUSUM calibration result from in-control block bootstrap (§16c)."""

    mu_0: float
    drift_delta: float
    drift_lambda: float
    target_arl: int
    estimated_arl: float


def compute_query_item_hash(
    *,
    question: str,
    as_of_date: str,
    source_set: Sequence[str],
) -> str:
    """Compute canonical SHA-256 over JCS of normalized ``(question, as_of_date, source_set)``."""
    normalized_question = " ".join(question.strip().split())
    payload: dict[str, object] = {
        "question": normalized_question,
        "as_of_date": str(as_of_date).strip(),
        "source_set": sorted(str(src) for src in source_set),
    }
    return hashlib.sha256(canonicalize_jcs(payload)).hexdigest()


def load_heldout_hash_registry(path: Path) -> HeldoutHashRegistry:
    """Load and validate sealed held-out query hashes from JSON."""
    if not path.is_file():
        raise CalibrationError(f"held-out hash registry does not exist: {path}")
    try:
        raw_bytes = path.read_bytes()
        doc = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"failed to read held-out hash registry {path.name}: {exc}") from exc
    if not isinstance(doc, Mapping):
        raise CalibrationError("held-out hash registry must be a JSON object")

    raw_sets = doc.get("sets")
    if not isinstance(raw_sets, Mapping) or not raw_sets:
        raise CalibrationError("held-out hash registry must define a non-empty 'sets' mapping")

    collected: set[str] = set()
    counts_by_set: dict[str, int] = {}
    for set_name, entry in raw_sets.items():
        if not isinstance(entry, Mapping):
            raise CalibrationError(f"held-out set {set_name!r} must be an object")
        raw_hashes = entry.get("hashes")
        if not isinstance(raw_hashes, list) or not raw_hashes:
            raise CalibrationError(f"held-out set {set_name!r} must have a non-empty 'hashes' list")
        counts_by_set[str(set_name)] = len(raw_hashes)
        for item_hash in raw_hashes:
            if not isinstance(item_hash, str) or not _HEX64_RE.match(item_hash):
                raise CalibrationError(
                    f"held-out set {set_name!r} contains invalid SHA-256 hash entry"
                )
            collected.add(item_hash)

    return HeldoutHashRegistry(
        schema_version=str(doc.get("schema_version", "1.0.0")),
        file_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        hashes=frozenset(collected),
        counts_by_set=counts_by_set,
    )


def assert_no_heldout_contamination(
    items: Sequence[PilotTrajectory],
    registry: HeldoutHashRegistry,
) -> None:
    """Refuse calibration or tuning if any item matches a sealed held-out query hash."""
    contaminated: list[str] = []
    for item in items:
        item_hash = item.query_hash or compute_query_item_hash(
            question=item.question,
            as_of_date=item.as_of_date,
            source_set=item.source_set,
        )
        if item_hash in registry.hashes:
            contaminated.append(f"{item.item_id} ({item_hash[:12]})")
    if contaminated:
        sample = ", ".join(contaminated[:5])
        raise ContaminationError(
            f"dataset contaminated with {len(contaminated)} sealed held-out hash(es): {sample}",
            details={"contaminated_count": len(contaminated), "items": contaminated[:10]},
        )


def _parse_loss_level(raw: object, *, item_id: str, field_name: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise CalibrationError(f"{item_id}.{field_name} must be 0, 0.5, or 1")
    val = float(raw)
    if val not in VALID_LOSS_LEVELS:
        raise CalibrationError(f"{item_id}.{field_name} must be in {{0, 0.5, 1}}, got {val!r}")
    return val


def load_pilot_dataset(path: Path) -> tuple[list[PilotTrajectory], str]:
    """Load and validate JSONL graded calibration trajectories."""
    if not path.is_file():
        raise CalibrationError(f"pilot dataset does not exist: {path}")
    try:
        raw_bytes = path.read_bytes()
        lines = raw_bytes.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CalibrationError(f"failed to read pilot dataset {path.name}: {exc}") from exc

    dataset_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    trajectories: list[PilotTrajectory] = []
    seen_ids: set[str] = set()

    for line_no, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise CalibrationError(f"pilot line {line_no}: invalid JSON ({exc.msg})") from exc
        if not isinstance(row, Mapping):
            raise CalibrationError(f"pilot line {line_no}: record must be a JSON object")

        item_id = str(row.get("item_id", "")).strip()
        if not item_id:
            raise CalibrationError(f"pilot line {line_no}: missing item_id")
        if item_id in seen_ids:
            raise CalibrationError(f"pilot line {line_no}: duplicate item_id {item_id!r}")
        seen_ids.add(item_id)

        raw_question = row.get("question")
        if not isinstance(raw_question, str) or not raw_question.strip():
            raise CalibrationError(f"{item_id}: missing non-empty question")

        raw_date = row.get("as_of_date")
        if not isinstance(raw_date, str) or not raw_date.strip():
            raise CalibrationError(f"{item_id}: missing as_of_date")

        raw_sources = row.get("source_set")
        if not isinstance(raw_sources, list) or not all(isinstance(s, str) for s in raw_sources):
            raise CalibrationError(f"{item_id}: source_set must be a list of strings")

        raw_tier = row.get("tier")
        if isinstance(raw_tier, bool) or not isinstance(raw_tier, int) or raw_tier not in (1, 2, 3):
            raise CalibrationError(f"{item_id}: tier must be 1, 2, or 3")

        raw_hg = row.get("hard_gate")
        if not isinstance(raw_hg, bool):
            raise CalibrationError(f"{item_id}: hard_gate must be boolean")

        raw_u = row.get("terminal_u")
        if isinstance(raw_u, bool) or not isinstance(raw_u, int | float):
            raise CalibrationError(f"{item_id}: terminal_u must be numeric")
        u_val = float(raw_u)
        if not math.isfinite(u_val) or not (0.0 <= u_val <= 1.0):
            raise CalibrationError(f"{item_id}: terminal_u must be in [0, 1], got {u_val!r}")

        loss_a = _parse_loss_level(
            row.get("grader_a_loss"), item_id=item_id, field_name="grader_a_loss"
        )
        loss_b = _parse_loss_level(
            row.get("grader_b_loss"), item_id=item_id, field_name="grader_b_loss"
        )
        loss_adj = _parse_loss_level(
            row.get("adjudicated_loss"), item_id=item_id, field_name="adjudicated_loss"
        )
        if loss_a == loss_b and loss_adj != loss_a:
            raise CalibrationError(
                f"{item_id}: adjudicated_loss ({loss_adj}) disagrees with "
                f"unanimous grade ({loss_a})"
            )

        volatility = str(row.get("volatility_class", "technical")).strip()
        if volatility not in VALID_VOLATILITY_CLASSES:
            raise CalibrationError(f"{item_id}: invalid volatility_class {volatility!r}")

        computed_hash = compute_query_item_hash(
            question=raw_question,
            as_of_date=raw_date,
            source_set=raw_sources,
        )
        declared_hash = row.get("query_hash")
        if declared_hash is not None and declared_hash != computed_hash:
            raise CalibrationError(f"{item_id}: declared query_hash does not match JCS digest")

        trajectories.append(
            PilotTrajectory(
                item_id=item_id,
                question=raw_question,
                as_of_date=raw_date,
                source_set=tuple(str(s) for s in raw_sources),
                tier=raw_tier,
                domain=str(row.get("domain", "general")),
                hard_gate=raw_hg,
                terminal_u=u_val,
                grader_a_loss=loss_a,
                grader_b_loss=loss_b,
                adjudicated_loss=loss_adj,
                decisive_claim=str(row.get("decisive_claim", "")),
                author=str(row.get("author", "")),
                license_id=str(row.get("license_id", "CC-BY-4.0")),
                volatility_class=volatility,
                query_hash=computed_hash,
            )
        )

    if not trajectories:
        raise CalibrationError(f"pilot dataset {path.name} contains zero records")
    return trajectories, dataset_sha256


def compute_cohen_kappa(trajectories: Sequence[PilotTrajectory]) -> KappaResult:
    """Compute unweighted Cohen's kappa across blind dual gradings on ``{0, 0.5, 1}``."""
    if not trajectories:
        raise CalibrationError("cannot compute Cohen's kappa on empty dataset")

    n = len(trajectories)
    counts: dict[tuple[float, float], int] = {
        (la, lb): 0 for la in VALID_LOSS_LEVELS for lb in VALID_LOSS_LEVELS
    }
    disagreements = 0
    for item in trajectories:
        counts[(item.grader_a_loss, item.grader_b_loss)] += 1
        if item.grader_a_loss != item.grader_b_loss:
            disagreements += 1

    agree = sum(counts[(lvl, lvl)] for lvl in VALID_LOSS_LEVELS)
    po = agree / n
    row_totals = {la: sum(counts[(la, lb)] for lb in VALID_LOSS_LEVELS) for la in VALID_LOSS_LEVELS}
    col_totals = {lb: sum(counts[(la, lb)] for la in VALID_LOSS_LEVELS) for lb in VALID_LOSS_LEVELS}
    pe = sum((row_totals[lvl] / n) * (col_totals[lvl] / n) for lvl in VALID_LOSS_LEVELS)

    if abs(1.0 - pe) <= 1e-12:
        kappa = 1.0 if abs(po - 1.0) <= 1e-12 else 0.0
    else:
        kappa = (po - pe) / (1.0 - pe)

    matrix: dict[str, dict[str, int]] = {
        str(la): {str(lb): counts[(la, lb)] for lb in VALID_LOSS_LEVELS} for la in VALID_LOSS_LEVELS
    }
    return KappaResult(
        kappa=round(kappa, 6),
        exact_agreement=round(po, 6),
        expected_agreement=round(pe, 6),
        adjudication_rate=round(disagreements / n, 6),
        confusion_matrix=matrix,
    )


def _build_crc_grid(*, grid_step: float, grid_values: Sequence[float] | None) -> tuple[float, ...]:
    if grid_values is not None:
        cleaned = sorted({0.0, *(float(v) for v in grid_values)})
        for val in cleaned:
            if not math.isfinite(val) or not (0.0 <= val <= 1.0):
                raise CalibrationError(f"CRC grid value {val!r} out of [0, 1]")
        return tuple(cleaned)

    if not math.isfinite(grid_step) or not (0.0 < grid_step <= 1.0):
        raise CalibrationError(f"grid_step must be in (0, 1], got {grid_step!r}")
    steps = max(1, round(1.0 / grid_step))
    pts = [min(1.0, round(k * grid_step, 6)) for k in range(steps + 1)]
    if pts[0] != 0.0:
        pts.insert(0, 0.0)
    if pts[-1] != 1.0:
        pts.append(1.0)
    return tuple(dict.fromkeys(pts))


def select_crc_threshold(
    trajectories: Sequence[PilotTrajectory],
    *,
    alpha: float = 0.05,
    grid_step: float = 0.005,
    grid_values: Sequence[float] | None = None,
) -> CrcResult:
    """Select finite-sample Conformal Risk Control cutoff ``t_hat`` per paper §16b."""
    if not trajectories:
        raise CalibrationError("cannot run CRC calibration on empty dataset")
    if not math.isfinite(alpha) or not (0.0 < alpha < 1.0):
        raise CalibrationError(f"alpha must be in (0, 1), got {alpha!r}")

    grid = _build_crc_grid(grid_step=grid_step, grid_values=grid_values)
    n = len(trajectories)
    selected_t = 0.0
    selected_loss_sum = 0.0
    selected_accepted = 0
    selected_risk = 1.0 / (n + 1.0)

    for candidate_t in grid:
        accepted = [
            item for item in trajectories if item.hard_gate and item.terminal_u < candidate_t
        ]
        loss_sum = sum(item.adjudicated_loss for item in accepted)
        corrected_risk = (loss_sum + 1.0) / (n + 1.0)
        if corrected_risk <= alpha + 1e-15:
            selected_t = candidate_t
            selected_loss_sum = loss_sum
            selected_accepted = len(accepted)
            selected_risk = corrected_risk

    cond_loss = (selected_loss_sum / selected_accepted) if selected_accepted > 0 else 0.0
    return CrcResult(
        threshold=round(selected_t, 6),
        n_cal=n,
        alpha=alpha,
        grid_step=grid_step,
        accepted_count=selected_accepted,
        empirical_coverage=round(selected_accepted / n, 6),
        accepted_loss_sum=round(selected_loss_sum, 6),
        corrected_risk=round(selected_risk, 6),
        conditional_accepted_loss=round(cond_loss, 6),
    )


def _mean_first_passage(
    max_paths: Sequence[list[float]], *, threshold: float, horizon: int
) -> float:
    total = 0
    for path in max_paths:
        idx = bisect.bisect_right(path, threshold)
        total += (idx + 1) if idx < horizon else horizon
    return total / len(max_paths)


def calibrate_cusum_parameters(
    u_values: Sequence[float],
    *,
    drift_delta: float = 0.02,
    target_arl: int = 1000,
    seed: int = 20261123,
    num_sequences: int = 200,
    max_horizon: int = 4000,
    mean_block_length: float = 5.0,
) -> CusumCalibrationResult:
    """Compute ``mu_0`` and block-bootstrap ``drift_lambda`` meeting ``target_arl`` (§16c)."""
    if not u_values:
        raise CalibrationError("cannot calibrate CUSUM on empty score sequence")
    if not math.isfinite(drift_delta) or not (0.0 < drift_delta < 1.0):
        raise CalibrationError(f"drift_delta must be in (0, 1), got {drift_delta!r}")
    if target_arl < 100:
        raise CalibrationError(f"target_arl must be >= 100, got {target_arl}")

    cleaned = [float(u) for u in u_values]
    mu_0 = sum(cleaned) / len(cleaned)

    rng = random.Random(seed)  # noqa: S311 - deterministic statistical bootstrap sampling
    n = len(cleaned)
    p_new = min(1.0, max(1e-3, 1.0 / mean_block_length))
    max_paths: list[list[float]] = []

    for _ in range(num_sequences):
        idx = rng.randrange(n)
        c_t = 0.0
        running_max = 0.0
        path: list[float] = []
        for _step in range(max_horizon):
            idx = rng.randrange(n) if rng.random() < p_new else (idx + 1) % n
            c_t = max(0.0, c_t + cleaned[idx] - mu_0 - drift_delta)
            if c_t > running_max:
                running_max = c_t
            path.append(running_max)
        max_paths.append(path)

    lo = 0.25
    hi = 10.0
    while (
        hi < 100.0
        and _mean_first_passage(max_paths, threshold=hi, horizon=max_horizon) < target_arl
    ):
        hi *= 2.0

    arl_at_lo = _mean_first_passage(max_paths, threshold=lo, horizon=max_horizon)
    if arl_at_lo >= target_arl:
        chosen_lambda = lo
        est_arl = arl_at_lo
    else:
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if _mean_first_passage(max_paths, threshold=mid, horizon=max_horizon) >= target_arl:
                hi = mid
            else:
                lo = mid
        chosen_lambda = math.ceil(hi * 10_000.0) / 10_000.0
        est_arl = _mean_first_passage(max_paths, threshold=chosen_lambda, horizon=max_horizon)
        while est_arl < target_arl and chosen_lambda < 100.0:
            chosen_lambda = round(chosen_lambda + 0.0005, 4)
            est_arl = _mean_first_passage(max_paths, threshold=chosen_lambda, horizon=max_horizon)

    return CusumCalibrationResult(
        mu_0=round(mu_0, 6),
        drift_delta=drift_delta,
        drift_lambda=round(chosen_lambda, 4),
        target_arl=target_arl,
        estimated_arl=round(est_arl, 2),
    )


def recommend_decay_rates(trajectories: Sequence[PilotTrajectory]) -> dict[str, float]:
    """Compute offline ``DVSS-P14`` staged source-age decay recommendations by volatility."""
    base = {"stable": 0.0, "technical": 0.01, "amended": 0.05}
    losses_by_class: dict[str, list[float]] = {k: [] for k in base}
    for item in trajectories:
        losses_by_class.setdefault(item.volatility_class, []).append(item.adjudicated_loss)

    recommended: dict[str, float] = {}
    for cls_name, default_rate in base.items():
        vals = losses_by_class.get(cls_name, [])
        if not vals:
            recommended[cls_name] = default_rate
            continue
        mean_loss = sum(vals) / len(vals)
        recommended[cls_name] = round(
            max(default_rate, min(0.15, default_rate + 0.02 * mean_loss)), 4
        )
    return recommended


def compute_calibration_artifact_sha256(doc: Mapping[str, object]) -> str:
    """Compute canonical RFC 8785 JCS SHA-256 over artifact excluding ``artifact_sha256``."""
    without_digest = {str(k): v for k, v in doc.items() if k != "artifact_sha256"}
    return hashlib.sha256(canonicalize_jcs(without_digest)).hexdigest()


def _validate_against_schema(
    payload: Mapping[str, object], schema_path: Path, *, label: str
) -> None:
    if not schema_path.is_file():
        raise CalibrationError(f"missing schema for {label}: {schema_path}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(dict(payload)), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        ptr = "/" + "/".join(str(p) for p in first.absolute_path)
        raise CalibrationError(f"{label} schema error at {ptr}: {first.message}")


def run_offline_calibration(
    *,
    pilot_path: Path,
    heldout_registry_path: Path,
    artifact_id: str,
    policy_sha256: str,
    model_versions: Mapping[str, str],
    alpha: float = 0.05,
    grid_step: float = 0.005,
    drift_delta: float = 0.02,
    target_arl: int = 1000,
    min_kappa: float = 0.6,
    seed: int = 20261123,
    approve: bool = False,
    approved_by: str | None = None,
    created_utc: str | None = None,
    notes: str | None = None,
    calibration_schema_path: Path | None = None,
    p14_in_schema_path: Path | None = None,
    p14_out_schema_path: Path | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run full ``O1`` / ``DVSS-P14`` calibration pipeline and emit signed artifact + P14 output."""
    trajectories, dataset_sha256 = load_pilot_dataset(pilot_path)
    registry = load_heldout_hash_registry(heldout_registry_path)

    p14_in: dict[str, object] = {
        "pilot_dataset_sha256": dataset_sha256,
        "heldout_hashes_sha256": registry.file_sha256,
        "alpha": alpha,
        "grid_step": grid_step,
        "drift_delta": drift_delta,
        "target_arl": target_arl,
        "min_kappa": min_kappa,
        "seed": seed,
    }
    _validate_against_schema(
        p14_in,
        p14_in_schema_path or _DEFAULT_P14_IN_SCHEMA,
        label="DVSS-P14 input",
    )

    assert_no_heldout_contamination(trajectories, registry)

    kappa_res = compute_cohen_kappa(trajectories)
    if kappa_res.kappa < min_kappa:
        raise CalibrationError(
            f"inter-rater Cohen's kappa {kappa_res.kappa:.4f} is below min {min_kappa:.2f}; "
            "rubric clarification and re-grading required before calibration",
            details={"cohen_kappa": kappa_res.kappa, "min_kappa": min_kappa},
        )

    crc = select_crc_threshold(trajectories, alpha=alpha, grid_step=grid_step)
    cusum = calibrate_cusum_parameters(
        [item.terminal_u for item in trajectories],
        drift_delta=drift_delta,
        target_arl=target_arl,
        seed=seed,
    )
    decay_rec = recommend_decay_rates(trajectories)

    now_utc = created_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    status: Literal["staged", "approved"] = "approved" if approve else "staged"
    eff_approved_by = (approved_by or "ai-risk-owner") if approve else None
    eff_approved_utc = now_utc if approve else None

    tier_dist = {
        "tier_1": sum(1 for item in trajectories if item.tier == 1),
        "tier_2": sum(1 for item in trajectories if item.tier == 2),
        "tier_3": sum(1 for item in trajectories if item.tier == 3),
    }

    artifact_doc: dict[str, object] = {
        "schema_version": "1.0.0",
        "artifact_id": artifact_id,
        "status": status,
        "created_utc": now_utc,
        "approved_by": eff_approved_by,
        "approved_utc": eff_approved_utc,
        "policy_sha256": policy_sha256,
        "model_versions": {str(k): str(v) for k, v in model_versions.items()},
        "heldout_hashes_sha256": registry.file_sha256,
        "n_cal": crc.n_cal,
        "alpha": crc.alpha,
        "grid_step": crc.grid_step,
        "threshold": crc.threshold,
        "accepted_count": crc.accepted_count,
        "empirical_coverage": crc.empirical_coverage,
        "accepted_loss_sum": crc.accepted_loss_sum,
        "corrected_risk": crc.corrected_risk,
        "conditional_accepted_loss": crc.conditional_accepted_loss,
        "mu_0": cusum.mu_0,
        "drift_delta": cusum.drift_delta,
        "drift_lambda": cusum.drift_lambda,
        "target_in_control_arl": cusum.target_arl,
        "estimated_in_control_arl": cusum.estimated_arl,
        "cohen_kappa": kappa_res.kappa,
        "grader_exact_agreement": kappa_res.exact_agreement,
        "adjudication_rate": kappa_res.adjudication_rate,
        "tier_distribution": tier_dist,
        "recommended_decay_rates": decay_rec,
    }
    if notes:
        artifact_doc["notes"] = notes

    artifact_sha256 = compute_calibration_artifact_sha256(artifact_doc)
    artifact_doc["artifact_sha256"] = artifact_sha256

    _validate_against_schema(
        artifact_doc,
        calibration_schema_path or _DEFAULT_CALIBRATION_SCHEMA,
        label="calibration artifact",
    )

    p14_out: dict[str, object] = {
        "artifact_id": artifact_id,
        "artifact_sha256": artifact_sha256,
        "status": status,
        "n_cal": crc.n_cal,
        "alpha": crc.alpha,
        "threshold": crc.threshold,
        "mu_0": cusum.mu_0,
        "drift_delta": cusum.drift_delta,
        "drift_lambda": cusum.drift_lambda,
        "cohen_kappa": kappa_res.kappa,
        "empirical_coverage": crc.empirical_coverage,
        "corrected_risk": crc.corrected_risk,
        "recommended_decay_rates": decay_rec,
    }
    _validate_against_schema(
        p14_out,
        p14_out_schema_path or _DEFAULT_P14_OUT_SCHEMA,
        label="DVSS-P14 output",
    )
    return artifact_doc, p14_out


def load_calibration_artifact(
    path: Path,
    *,
    require_approved: bool = True,
    min_kappa: float = 0.6,
    schema_path: Path | None = None,
) -> CalibrationArtifact:
    """Load, schema-validate, and digest-verify a calibration JSON artifact."""
    if not path.is_file():
        raise CalibrationError(f"calibration artifact not found: {path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"failed to parse calibration artifact {path.name}: {exc}") from exc
    if not isinstance(doc, Mapping):
        raise CalibrationError(f"calibration artifact {path.name} must be a JSON object")

    _validate_against_schema(
        doc,
        schema_path or _DEFAULT_CALIBRATION_SCHEMA,
        label="calibration artifact",
    )

    declared_sha = str(doc["artifact_sha256"])
    actual_sha = compute_calibration_artifact_sha256(doc)
    if not hmac.compare_digest(declared_sha, actual_sha):
        raise CalibrationError(
            f"calibration artifact {doc['artifact_id']!r} SHA-256 mismatch (tampered artifact)"
        )

    status_raw = str(doc["status"])
    if require_approved and status_raw != "approved":
        raise CalibrationError(
            f"calibration artifact {doc['artifact_id']!r} status is {status_raw!r}; "
            "expected 'approved'"
        )

    kappa_val = float(doc["cohen_kappa"])
    if kappa_val < min_kappa:
        raise CalibrationError(
            f"calibration artifact {doc['artifact_id']!r} kappa {kappa_val:.3f} < {min_kappa:.2f}"
        )

    raw_mv = doc["model_versions"]
    model_versions = (
        tuple(sorted((str(k), str(v)) for k, v in raw_mv.items()))
        if isinstance(raw_mv, Mapping)
        else ()
    )
    status_lit = cast(Literal["staged", "approved", "revoked"], status_raw)
    return CalibrationArtifact(
        artifact_id=str(doc["artifact_id"]),
        artifact_sha256=declared_sha,
        n_cal=int(doc["n_cal"]),
        alpha=float(doc["alpha"]),
        threshold=float(doc["threshold"]),
        mu_0=float(doc["mu_0"]),
        drift_lambda=float(doc["drift_lambda"]),
        drift_delta=float(doc["drift_delta"]),
        status=status_lit,
        policy_sha256=str(doc["policy_sha256"]),
        model_versions=model_versions,
        cohen_kappa=kappa_val,
        heldout_hashes_sha256=str(doc["heldout_hashes_sha256"]),
    )


def find_approved_calibration_artifact(
    calibration_dir: Path,
    artifact_id: str,
    *,
    min_kappa: float = 0.6,
) -> CalibrationArtifact | None:
    """Locate and verify an approved artifact matching ``artifact_id`` under ``calibration_dir``."""
    if not calibration_dir.is_dir():
        return None
    for candidate in sorted(calibration_dir.glob("*.json")):
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CalibrationError(f"corrupt calibration file {candidate.name}: {exc}") from exc
        if isinstance(raw, Mapping) and raw.get("artifact_id") == artifact_id:
            return load_calibration_artifact(
                candidate,
                require_approved=True,
                min_kappa=min_kappa,
            )
    return None


__all__ = [
    "VALID_LOSS_LEVELS",
    "VALID_VOLATILITY_CLASSES",
    "CrcResult",
    "CusumCalibrationResult",
    "HeldoutHashRegistry",
    "KappaResult",
    "PilotTrajectory",
    "assert_no_heldout_contamination",
    "calibrate_cusum_parameters",
    "compute_calibration_artifact_sha256",
    "compute_cohen_kappa",
    "compute_query_item_hash",
    "find_approved_calibration_artifact",
    "load_calibration_artifact",
    "load_heldout_hash_registry",
    "load_pilot_dataset",
    "recommend_decay_rates",
    "run_offline_calibration",
    "select_crc_threshold",
]
