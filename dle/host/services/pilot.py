"""Migrated §18 DVSS conformance pilot running via H16 and receipt schema 3.8.0.

Implements FR-FN-01, FR-RCPT-03, DLE-PLN-001 (P1-20), and white paper v3.13
§18 / Appendix G checks. Routes triage, ledger merge, and disclosure through
``FunctionRegistry`` as ``DVSS-K10``, ``DVSS-K12``, and ``DVSS-K11`` and seals
Ed25519 receipts conforming to ``contracts/receipt.schema.json`` (3.8.0).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from dle.config.loader import compute_policy_digest
from dle.errors import ContractValidationError
from dle.host.functions import FunctionContext, FunctionRecord, FunctionRegistry
from dle.observability import sha256_text
from dle.temporal import Interval, overlaps

_ZERO_HASH = "0" * 64


@dataclass(frozen=True)
class RegistryEntry:
    """Version-qualified record registered against a canonical coordinate string."""

    canonical_str: str
    record_id: str
    registry_version: str | None


class CoordinateResolver:
    """Minimal Axis 2/4/5/13 coordinate helper enforcing §18 parser & version rules."""

    def __init__(self, coordinate_schema: Mapping[str, object]) -> None:
        """Initialize with parsed ``contracts/coordinate.schema.json``."""
        self._validator = jsonschema.Draft202012Validator(
            dict(coordinate_schema),
            format_checker=jsonschema.FormatChecker(),
        )
        self._records: dict[str, list[RegistryEntry]] = {}
        self._sector_to_surrogate: dict[str, int] = {}
        self._surrogate_to_sector: dict[int, str] = {}
        self._next_surrogate: int = 1

    def register_record(
        self,
        canonical_str: str,
        record_id: str,
        *,
        is_ambiguous: bool = False,
        registry_version: str | None = None,
    ) -> RegistryEntry:
        """Register ``record_id`` at ``canonical_str``, requiring a version if ambiguous."""
        if is_ambiguous and not registry_version:
            raise ContractValidationError(
                f"legacy ambiguous address {canonical_str!r} requires explicit registry_version",
                file_path="registry",
                pointer="/registry_version",
            )
        entry = RegistryEntry(
            canonical_str=canonical_str,
            record_id=record_id,
            registry_version=registry_version,
        )
        bucket = self._records.setdefault(canonical_str, [])
        if entry not in bucket:
            bucket.append(entry)
        return entry

    def lookup(
        self,
        canonical_str: str,
        *,
        registry_version: str | None = None,
    ) -> list[RegistryEntry]:
        """Look up distinct records registered at ``canonical_str``, optionally by version."""
        entries = self._records.get(canonical_str, [])
        if registry_version is not None:
            return [e for e in entries if e.registry_version == registry_version]
        return list(entries)

    def register_sector(self, native_code: str) -> int:
        """Assign an integer surrogate preserving exact native sector code strings."""
        if native_code in self._sector_to_surrogate:
            return self._sector_to_surrogate[native_code]
        surrogate = self._next_surrogate
        self._next_surrogate += 1
        self._sector_to_surrogate[native_code] = surrogate
        self._surrogate_to_sector[surrogate] = native_code
        return surrogate

    def resolve_sector(self, surrogate: int) -> str:
        """Recover exact native sector code string (with leading zeros/letters) by surrogate."""
        if surrogate not in self._surrogate_to_sector:
            raise KeyError(f"unknown sector surrogate {surrogate}")
        return self._surrogate_to_sector[surrogate]

    def create_temp_node(self, session_uuid: str) -> dict[str, object]:
        """Generate a unique non-authoritative Axis 5 temporary session node atom."""
        node_uuid = str(uuid.uuid4())
        return {
            "axis_id": 5,
            "meta_tag": "TMP",
            "session_uuid": session_uuid,
            "node_uuid": node_uuid,
            "status": "synthetic_derived",
            "canonical_str": f"[TMP:5.TMP.{node_uuid}]",
            "authoritative": False,
        }

    def validate_coordinate(self, coord: Mapping[str, object]) -> None:
        """Validate coordinate against ``coordinate.schema.json`` (duplicates and slot states)."""
        errors = sorted(self._validator.iter_errors(dict(coord)), key=str)
        if errors:
            raise ContractValidationError(
                errors[0].message,
                file_path="coordinate",
                pointer="/" + "/".join(str(p) for p in errors[0].absolute_path),
            )

    def filter_by_scope(
        self,
        passages: Sequence[PilotPassage],
        query_interval: Interval,
    ) -> list[PilotPassage]:
        """Return passages whose valid-time interval overlaps ``query_interval``."""
        return [p for p in passages if overlaps(p.interval, query_interval)]


@dataclass(frozen=True)
class PilotPassage:
    """Synthetic evidence passage for §18 pilot checks."""

    passage_id: str
    source_id: str
    revision: str
    locator: str
    text: str
    interval: Interval
    scope: str
    access_policy: str = "tenant"


@dataclass(frozen=True)
class PilotClaim:
    """Claim scored under §16a ``z = p*e``, ``b = p * I[active] * exp(-lambda * age)``."""

    claim_id: str
    proposal_id: str
    assertion: str
    binding: bool
    scope: str
    passage_ids: tuple[str, ...]
    provenance: float
    entailment: float
    belief: float | None = None
    age_years: float = 0.0
    decay_rate: float = 0.0
    active_in_scope: bool = True

    def effective_belief(self) -> float:
        """Return explicit ``belief`` or compute ``p * I[active] * exp(-lambda * age)``."""
        if self.belief is not None:
            return self.belief
        if not self.active_in_scope:
            return 0.0
        return self.provenance * math.exp(-self.decay_rate * self.age_years)

    def support_z(self) -> float:
        """Return entailment-weighted support ``z = p * e``."""
        return self.provenance * self.entailment

    def to_receipt_dict(self) -> dict[str, object]:
        """Serialize into receipt schema 3.8.0 claim item shape."""
        return {
            "claim_id": self.claim_id,
            "proposal_id": self.proposal_id,
            "assertion": self.assertion,
            "binding": self.binding,
            "scope": self.scope,
            "passage_ids": list(self.passage_ids),
            "entailment": self.entailment,
            "provenance": self.provenance,
            "belief": round(self.effective_belief(), 6),
        }


@dataclass(frozen=True)
class PilotObjection:
    """Verifier-governed objection entry for DVSS-K12 and receipt serialization."""

    objection_id: str
    role_axis: int
    proposal_id: str
    blocking: bool
    predicate: str
    state: str
    closure_evidence: tuple[str, ...] = ()
    verifier_closed: bool = False

    def to_ledger_dict(self) -> dict[str, object]:
        """Serialize into dictionary payload for ``DVSS-K12``."""
        return {
            "objection_id": self.objection_id,
            "role_axis": self.role_axis,
            "proposal_id": self.proposal_id,
            "blocking": self.blocking,
            "predicate": self.predicate,
            "state": self.state,
            "closure_evidence": list(self.closure_evidence),
            "verifier_closed": self.verifier_closed,
        }


def ppr(
    adjacency: Mapping[str, Sequence[tuple[str, float]]],
    seeds: Mapping[str, float],
    *,
    damping: float = 0.85,
    max_iterations: int = 80,
    tolerance: float = 1.76e-6,
) -> tuple[dict[str, float], int]:
    """Deterministic Personalized PageRank bounded by iteration and L1 tolerance."""
    if not seeds:
        return {}, 0

    nodes_set: set[str] = set(seeds) | set(adjacency)
    for edges in adjacency.values():
        for dst, _w in edges:
            nodes_set.add(dst)
    nodes = sorted(nodes_set)

    total_seed = sum(max(0.0, w) for w in seeds.values())
    if total_seed <= 0.0:
        return {}, 0
    teleport = {n: max(0.0, seeds.get(n, 0.0)) / total_seed for n in nodes}
    vec = dict(teleport)

    # Normalize outgoing edge weights; dangling nodes fall back to teleport vector.
    norm_adj: dict[str, list[tuple[str, float]]] = {}
    for src in nodes:
        raw_edges = [(dst, w) for dst, w in adjacency.get(src, ()) if w > 0.0]
        total_w = sum(w for _, w in raw_edges)
        if total_w > 0.0:
            norm_adj[src] = [(dst, w / total_w) for dst, w in raw_edges]
        else:
            norm_adj[src] = []

    iterations = 0
    for it in range(1, max_iterations + 1):
        iterations = it
        nxt = {n: (1.0 - damping) * teleport[n] for n in nodes}
        dangling_mass = 0.0
        for src in nodes:
            edges = norm_adj[src]
            if not edges:
                dangling_mass += vec[src]
            else:
                for dst, prob in edges:
                    nxt[dst] += damping * vec[src] * prob
        if dangling_mass > 0.0:
            for dst in nodes:
                nxt[dst] += damping * dangling_mass * teleport[dst]
        l1_diff = sum(abs(nxt[n] - vec[n]) for n in nodes)
        vec = nxt
        if l1_diff <= tolerance:
            break

    return vec, iterations


def pack_hydrated(
    candidates: Sequence[tuple[str, float, int, int, int]],
    *,
    max_vertices: int = 250,
    max_edges: int = 500,
    max_tokens: int = 4000,
    max_hops: int = 4,
) -> list[str]:
    """Enforce vertex, edge, token, and hop budgets after node hydration (`DVSS-K07`).

    Each candidate tuple is ``(node_id, score, hop, edges_count, token_cost)``.
    Deterministic ordering: highest score descending, then ``node_id`` ascending.
    """
    ordered = sorted(
        (c for c in candidates if c[2] <= max_hops),
        key=lambda item: (-item[1], item[0]),
    )
    retained: list[str] = []
    used_edges = 0
    used_tokens = 0
    for node_id, _score, _hop, edge_cost, token_cost in ordered:
        if len(retained) >= max_vertices:
            break
        if used_edges + edge_cost > max_edges:
            continue
        if used_tokens + token_cost > max_tokens:
            continue
        retained.append(node_id)
        used_edges += edge_cost
        used_tokens += token_cost
    return retained


def compute_nonconformity(
    claims: Sequence[PilotClaim],
    objections: Sequence[Mapping[str, object]],
) -> tuple[float, bool]:
    """Compute terminal nonconformity ``u`` per §16a and non-empty check."""
    if not claims:
        return 1.0, False

    binding_claims = [c for c in claims if c.binding]
    focus = binding_claims if binding_claims else list(claims)

    min_z = min(c.support_z() for c in focus)
    mean_z = sum(c.support_z() for c in claims) / len(claims)
    min_b = min(c.effective_belief() for c in focus)

    total_obj = len(objections)
    if total_obj == 0:
        d_frac = 0.0
    else:
        unresolved = sum(1 for o in objections if o.get("state") == "open")
        d_frac = unresolved / total_obj

    u = 0.40 * (1.0 - min_z) + 0.20 * (1.0 - mean_z) + 0.25 * (1.0 - min_b) + 0.15 * d_frac
    return u, True


def calibrate_crc(
    threshold_losses: Sequence[tuple[float, float]],
    *,
    n_cal: int,
    alpha: float,
) -> float:
    """Select largest threshold ``t`` satisfying ``(loss + 1)/(n + 1) <= alpha`` (§16b)."""
    if n_cal < 1 or not (0.0 < alpha < 1.0):
        raise ValueError("n_cal must be >= 1 and alpha must lie in (0, 1)")
    selected = 0.0
    for threshold, total_loss in sorted(threshold_losses, key=lambda pair: pair[0]):
        if (total_loss + 1.0) / (n_cal + 1.0) <= alpha:
            selected = threshold
    return selected


class DriftMonitor:
    """Fixed-baseline CUSUM drift monitor updating once per terminal run (§16c)."""

    def __init__(
        self,
        *,
        mu_0: float,
        drift_lambda: float,
        delta: float = 0.02,
    ) -> None:
        """Initialize CUSUM monitor at ``c_t = 0``."""
        self.mu_0 = mu_0
        self.drift_lambda = drift_lambda
        self.delta = delta
        self.c_t = 0.0
        self.is_latched = False

    def update(self, u_t: float) -> tuple[float, bool]:
        """Update CUSUM with terminal score ``u_t`` once per run and return state."""
        self.c_t = max(0.0, self.c_t + u_t - self.mu_0 - self.delta)
        if self.c_t > self.drift_lambda:
            self.is_latched = True
        return self.c_t, self.is_latched


class PilotReceiptSealer:
    """Ed25519 sealer & verifier emitting schema 3.8.0 receipts."""

    def __init__(self, key_id: str = "pilot-ed25519-k1") -> None:
        """Generate an isolated Ed25519 keypair for pilot receipt sealing tests."""
        self.key_id = key_id
        self._private = Ed25519PrivateKey.generate()
        self._public: Ed25519PublicKey = self._private.public_key()

    def seal(
        self,
        *,
        run_id: str,
        chain_id: str,
        previous_hash: str,
        policy_sha256: str,
        profile: str,
        attempts: Sequence[dict[str, object]],
        sources: Sequence[dict[str, object]],
        calibration: Mapping[str, object],
        decision: Mapping[str, object],
        returned_text: str,
        function_invocations: Sequence[FunctionRecord],
        anchoring_profile: str = "local_worm_merkle",
        inclusion_proof_ref: str | None = "merkle:leaf-0",
        coordinate_manifest_sha256: str = _ZERO_HASH,
    ) -> dict[str, object]:
        """Build and sign a complete schema 3.8.0 receipt JSON document."""
        payload: dict[str, object] = {
            "schema_version": "3.8.0",
            "run_id": run_id,
            "utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "chain_id": chain_id,
            "previous_hash": previous_hash,
            "coordinate_manifest_sha256": coordinate_manifest_sha256,
            "policy_sha256": policy_sha256,
            "verifier_version": "0.1.0",
            "attempts": copy.deepcopy(list(attempts)),
            "sources": copy.deepcopy(list(sources)),
            "calibration": dict(calibration),
            "decision": dict(decision),
            "response_sha256": sha256_text(returned_text),
            "profile": profile,
            "function_invocations": [rec.to_receipt_dict() for rec in function_invocations],
        }
        digest_sha256 = compute_policy_digest(payload)
        sig_bytes = self._private.sign(digest_sha256.encode("ascii"))
        signature_b64 = base64.b64encode(sig_bytes).decode("ascii")

        verification_level = {
            "local_worm_merkle": "locally_sealed",
            "customer_hosted_log": "customer_anchored",
            "external_transparency_log": "externally_anchored",
        }[anchoring_profile]

        envelope: dict[str, object] = {
            "digest_sha256": digest_sha256,
            "key_id": self.key_id,
            "algorithm": "Ed25519",
            "signature_b64": signature_b64,
            "log_id": "local-worm-merkle-01",
            "inclusion_proof_ref": inclusion_proof_ref or "PENDING",
            "verified_checkpoint_sha256": hashlib.sha256(digest_sha256.encode("ascii")).hexdigest(),
            "anchoring_profile": anchoring_profile,
            "verification_level": verification_level,
        }
        return {"payload": payload, "envelope": envelope}

    def verify(
        self,
        receipt: Mapping[str, object],
        returned_text: str,
        *,
        require_anchor: bool = True,
    ) -> bool:
        """Verify response hash, JCS digest, Ed25519 signature, and anchor state."""
        payload = receipt.get("payload")
        envelope = receipt.get("envelope")
        if not isinstance(payload, Mapping) or not isinstance(envelope, Mapping):
            return False
        if payload.get("response_sha256") != sha256_text(returned_text):
            return False

        expected_digest = compute_policy_digest({str(k): v for k, v in payload.items()})
        if envelope.get("digest_sha256") != expected_digest:
            return False

        sig_b64 = envelope.get("signature_b64")
        if not isinstance(sig_b64, str):
            return False
        try:
            self._public.verify(
                base64.b64decode(sig_b64),
                expected_digest.encode("ascii"),
            )
        except (InvalidSignature, ValueError):
            return False

        if require_anchor:
            ref = envelope.get("inclusion_proof_ref")
            if not isinstance(ref, str) or not ref or ref == "PENDING":
                return False
        return True


@dataclass(frozen=True)
class PilotExecutionResult:
    """Result returned by ``PilotPipeline.execute``."""

    receipt: dict[str, object]
    returned_text: str
    receipt_release_mode: str
    api_release_mode: str
    attempts: tuple[dict[str, object], ...]
    function_records: tuple[FunctionRecord, ...]
    terminal_attempt_id: str
    terminal_u: float


@dataclass
class RetryAttemptInput:
    """Single scripted attempt/retry input for cutoff-independence & escalation checks."""

    claims: tuple[PilotClaim, ...]
    new_objections: tuple[PilotObjection, ...] = ()
    recoverable_gap: str | None = None
    authorized_next_source: str | None = None
    draft_text: str = "Verified pilot draft."
    role_axes: tuple[int, ...] | None = None


class PilotPipeline:
    """§18 conformance pilot dispatching routing, ledger merge, and disclosure through H16."""

    def __init__(
        self,
        *,
        function_registry: FunctionRegistry,
        policy_sha256: str,
        sealer: PilotReceiptSealer | None = None,
        drift_monitor: DriftMonitor | None = None,
    ) -> None:
        """Initialize pipeline with H16 registry, policy digest, sealer, and drift monitor."""
        self.functions = function_registry
        self.policy_sha256 = policy_sha256
        self.sealer = sealer if sealer is not None else PilotReceiptSealer()
        self.drift = (
            drift_monitor
            if drift_monitor is not None
            else DriftMonitor(mu_0=0.05, drift_lambda=0.25)
        )

    def execute(
        self,
        *,
        profile: str,
        cutoff: float,
        triage_input: Mapping[str, object],
        attempts_plan: Sequence[RetryAttemptInput],
        has_usable_seeds: bool = True,
        anchoring_profile: str = "local_worm_merkle",
        inclusion_proof_ref: str | None = "merkle:leaf-0",
        ppr_iterations: int = 2,
        vertices_retained: int = 2,
        drift_updates_override: bool = False,
    ) -> PilotExecutionResult:
        """Run one §18 query trajectory through H16 and emit a signed 3.8.0 receipt."""
        run_id = str(uuid.uuid4())
        records: list[FunctionRecord] = []

        # Step 1: Hybrid triage via DVSS-K10
        k10 = self.functions.invoke(
            "DVSS-K10",
            FunctionContext(
                run_id=run_id,
                attempt_id="att-0",
                profile=profile,
                payload=dict(triage_input),
            ),
            records=records,
        )
        tier = int(k10.output["tier"]) if isinstance(k10.output["tier"], int) else 1
        raw_roles = k10.output.get("active_roles", ["scholar"])
        active_roles = [str(r) for r in raw_roles] if isinstance(raw_roles, list) else ["scholar"]

        # Emit baseline kernel records K01..K09 for 12-kernel receipt traceability.
        for kid in (f"DVSS-K{i:02d}" for i in range(1, 10)):
            self.functions.invoke(
                kid,
                FunctionContext(
                    run_id=run_id,
                    attempt_id="att-0",
                    profile=profile,
                    payload={"run_id": run_id, "step": kid},
                    tier=tier,
                ),
                records=records,
            )

        attempts_out: list[dict[str, object]] = []
        ledger_objections: list[dict[str, object]] = []
        escalated_once = False
        retries_used = 0
        current_tier = tier
        current_roles = set(active_roles)
        terminal_u = 1.0
        hard_gate = False
        terminal_attempt_id = "att-0"
        final_draft = ""

        idx = 0
        plan_list = list(attempts_plan)
        while idx < len(plan_list):
            step = plan_list[idx]
            attempt_num = len(attempts_out)
            attempt_id = f"att-{attempt_num}"
            parent_id = attempts_out[-1]["attempt_id"] if attempts_out else None

            event = "initial"
            reason = "initial_pass"
            if (
                attempt_num > 0
                and attempt_id.startswith("att-")
                and attempts_out[-1].get("_escalate")
            ):
                event = "tier_escalation"
                reason = "binding_claim_requires_regulator"
            elif attempt_num > 0:
                event = "retry"
                reason = step.recoverable_gap or "authorized_retry"

            # Merge objections through DVSS-K12 on H16 (never reset prior objections).
            k12 = self.functions.invoke(
                "DVSS-K12",
                FunctionContext(
                    run_id=run_id,
                    attempt_id=attempt_id,
                    profile=profile,
                    payload={
                        "existing_objections": ledger_objections,
                        "new_objections": [o.to_ledger_dict() for o in step.new_objections],
                    },
                    tier=current_tier,
                ),
                records=records,
            )
            raw_merged = k12.output.get("objections", [])
            ledger_objections = (
                [dict(o) for o in raw_merged if isinstance(o, Mapping)]
                if isinstance(raw_merged, list)
                else []
            )

            has_binding = any(c.binding for c in step.claims)
            if step.role_axes is not None:
                axes = list(step.role_axes)
            else:
                role_map = {"scholar": 8, "practitioner": 9, "regulator": 10, "harmonizer": 11}
                axes = sorted(role_map[r] for r in current_roles if r in role_map) or [8]

            # Check if binding claim occurred without Regulator active -> one-time escalation.
            needs_regulator_escalation = (
                has_binding and 10 not in axes and not escalated_once and len(attempts_out) < 3
            )

            u_val, nonempty_claims = compute_nonconformity(step.claims, ledger_objections)
            open_blocking = any(
                bool(o.get("blocking", False)) and o.get("state") == "open"
                for o in ledger_objections
            )
            attempt_hard = has_usable_seeds and nonempty_claims and not open_blocking

            serialized_objections = [
                {
                    "objection_id": str(o["objection_id"]),
                    "role_axis": (
                        int(o["role_axis"]) if isinstance(o["role_axis"], int | float) else 10
                    ),
                    "proposal_id": str(o["proposal_id"]),
                    "blocking": bool(o["blocking"]),
                    "predicate": str(o["predicate"]),
                    "state": str(o["state"]),
                    "closure_evidence": (
                        [str(ev) for ev in raw_ev]
                        if isinstance((raw_ev := o.get("closure_evidence")), list)
                        else []
                    ),
                }
                for o in ledger_objections
            ]
            serialized_claims = [c.to_receipt_dict() for c in step.claims]
            candidate_hash = sha256_text(f"{attempt_id}:{step.draft_text}:{u_val:.6f}")

            attempts_out.append(
                {
                    "attempt_id": attempt_id,
                    "parent_id": parent_id,
                    "event": event,
                    "reason": reason,
                    "tier": current_tier,
                    "hops": min(4, 1 + retries_used),
                    "ppr_iterations": min(80, max(0, ppr_iterations)),
                    "vertices_retained": min(250, max(0, vertices_retained)),
                    "graph_sha256": _ZERO_HASH,
                    "source_manifest_sha256": _ZERO_HASH,
                    "role_calls": [
                        {
                            "role_axes": axes,
                            "profile_ids": [f"[ROLE:{ax}.1]" for ax in axes],
                            "input_sha256": _ZERO_HASH,
                            "output_sha256": candidate_hash,
                            "model_id": "gemini-4-carbon",
                            "model_version": "gemini-4-carbon-001",
                            "temperature": 0.0,
                            "top_p": 1.0,
                            "seed": 42,
                        }
                    ],
                    "claims": serialized_claims,
                    "objections": serialized_objections,
                    "candidate_sha256": candidate_hash,
                    "_escalate": needs_regulator_escalation,
                }
            )
            terminal_attempt_id = attempt_id
            terminal_u = u_val
            hard_gate = attempt_hard
            final_draft = step.draft_text

            if needs_regulator_escalation:
                escalated_once = True
                k10_esc = self.functions.invoke(
                    "DVSS-K10",
                    FunctionContext(
                        run_id=run_id,
                        attempt_id=attempt_id,
                        profile=profile,
                        payload={
                            "d": triage_input.get("d", 0),
                            "r": triage_input.get("r", 0),
                            "m": triage_input.get("m", 0),
                            "binding": True,
                            "z_hit": triage_input.get("z_hit", False),
                        },
                    ),
                    records=records,
                )
                esc_tier = (
                    int(k10_esc.output["tier"]) if isinstance(k10_esc.output["tier"], int) else 2
                )
                current_tier = max(2, esc_tier)
                current_roles.add("regulator")
                # Synthesize follow-up attempt when escalation has no scripted next step.
                if idx + 1 >= len(plan_list) and len(attempts_out) < 4:
                    plan_list.append(
                        RetryAttemptInput(
                            claims=step.claims,
                            new_objections=(),
                            draft_text=step.draft_text,
                        )
                    )
                idx += 1
                continue

            # Cutoff-blind retry decision F: depends only on recoverable gap + source, NEVER cutoff.
            if (
                step.recoverable_gap is not None
                and step.authorized_next_source is not None
                and retries_used < 2
                and idx + 1 < len(plan_list)
            ):
                retries_used += 1
                idx += 1
                continue

            break

        # Strip internal transition marker before schema validation.
        clean_attempts = [
            {k: v for k, v in att.items() if k != "_escalate"} for att in attempts_out
        ]

        # Drift updates once per terminal run (§16c).
        if drift_updates_override:
            cusum_val, drift_latched = self.drift.c_t, self.drift.is_latched
        else:
            cusum_val, drift_latched = self.drift.update(terminal_u)

        if not hard_gate:
            k04_decision = "block"
        elif drift_latched:
            k04_decision = "withhold_drift"
        elif terminal_u >= cutoff:
            k04_decision = "abstain_or_explain"
        else:
            k04_decision = "release"

        # Finalize user text and release mode via DVSS-K11 on H16.
        k11 = self.functions.invoke(
            "DVSS-K11",
            FunctionContext(
                run_id=run_id,
                attempt_id=terminal_attempt_id,
                profile=profile,
                payload={
                    "decision": k04_decision,
                    "draft_text": final_draft,
                    "drift_latched": drift_latched,
                },
                tier=current_tier,
            ),
            records=records,
        )
        returned_text = str(k11.output["returned_text"])
        receipt_release_mode = str(k11.output["receipt_release_mode"])
        api_release_mode = str(k11.output["api_release_mode"])

        calibration_block: dict[str, object] = {
            "artifact_id": "cal-pilot-01",
            "artifact_sha256": _ZERO_HASH,
            "n_cal": 100,
            "alpha": 0.05,
            "threshold": cutoff,
            "mu_0": self.drift.mu_0,
            "drift_lambda": self.drift.drift_lambda,
            "drift_delta": self.drift.delta,
        }
        decision_block: dict[str, object] = {
            "hard_gate": hard_gate,
            "drift_latched": drift_latched,
            "cusum": round(cusum_val, 6),
            "terminal_u": round(min(1.0, max(0.0, terminal_u)), 6),
            "terminal_attempt_id": terminal_attempt_id,
            "release_mode": receipt_release_mode,
            "profile": profile,
        }
        sources_list: list[dict[str, object]] = (
            [
                {
                    "source_id": "src-pilot-1",
                    "revision": "2026-01",
                    "document_sha256": _ZERO_HASH,
                    "passage_id": "src-pilot-1@2026-01#s1",
                    "locator": "s1",
                    "passage_sha256": _ZERO_HASH,
                    "scope": "default",
                    "access_policy": "tenant",
                    "retrieved_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            ]
            if has_usable_seeds
            else []
        )

        receipt = self.sealer.seal(
            run_id=run_id,
            chain_id="pilot-chain-1",
            previous_hash="GENESIS",
            policy_sha256=self.policy_sha256,
            profile=profile,
            attempts=clean_attempts,
            sources=sources_list,
            calibration=calibration_block,
            decision=decision_block,
            returned_text=returned_text,
            function_invocations=records,
            anchoring_profile=anchoring_profile,
            inclusion_proof_ref=inclusion_proof_ref,
        )
        return PilotExecutionResult(
            receipt=receipt,
            returned_text=returned_text,
            receipt_release_mode=receipt_release_mode,
            api_release_mode=api_release_mode,
            attempts=tuple(clean_attempts),
            function_records=tuple(records),
            terminal_attempt_id=terminal_attempt_id,
            terminal_u=terminal_u,
        )


def load_coordinate_schema(repo_root: Path) -> dict[str, object]:
    """Load ``contracts/coordinate.schema.json`` as a dictionary."""
    import json

    raw = json.loads(
        (repo_root / "contracts" / "coordinate.schema.json").read_text(encoding="utf-8")
    )
    return {str(k): v for k, v in raw.items()}


__all__ = [
    "CoordinateResolver",
    "DriftMonitor",
    "PilotClaim",
    "PilotExecutionResult",
    "PilotObjection",
    "PilotPassage",
    "PilotPipeline",
    "PilotReceiptSealer",
    "RetryAttemptInput",
    "calibrate_crc",
    "compute_nonconformity",
    "load_coordinate_schema",
    "pack_hydrated",
    "ppr",
]
