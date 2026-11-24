"""Unit & contract tests for Phase 4 Wave 4A (H11 Ledger, DVSS-P02 Pareto, H9 Writer)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import jsonschema
import pytest

from dle.config import load_config
from dle.errors import ContractValidationError
from dle.host.services.ledger import LedgerService
from dle.host.services.pareto import (
    CandidateOption,
    ParetoObjective,
    filter_pareto_options,
)
from dle.host.services.release import LedgerObjection
from dle.host.services.writer import (
    WRITER_PROMPT_VERSION,
    RoleFinding,
    WriterService,
    extract_inline_citations,
)
from dle.models.fake import FakeModel
from dle.store import SessionRepository, open_stores

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "config"
CONTRACTS_FN = REPO_ROOT / "contracts" / "functions"


def _validate_fn_contract(fn_name: str, direction: str, payload: dict[str, object]) -> None:
    schema = json.loads((CONTRACTS_FN / f"{fn_name}.{direction}.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=payload, schema=schema)


def test_h11_verifier_only_append_ledger_k12_persistence(tmp_path: Path) -> None:
    """T-UNIT-FN-K12-05..08: Role cannot close, verifier closes only with verified passages."""
    stores = open_stores(tmp_path / "db", enable_vec=False)
    try:
        repo = SessionRepository(stores.sessions)
        ledger = LedgerService(repo)
        allowed = {"src-1@v1#p1", "src-2@v1#p2"}
        utc = "2026-11-23T19:00:00Z"

        # Role attempts to submit 'proposed_closed' / 'closed' directly -> normalized to open!
        recorded, proposed = ledger.record_role_objections(
            run_id="run-k12-1",
            attempt_id="att-0",
            raw_objections=[
                {
                    "objection_id": "R1",
                    "role_axis": 10,
                    "proposal_id": "p0",
                    "blocking": True,
                    "predicate": "signed change order required",
                    "state": "proposed_closed",
                    "closure_evidence": ["src-1@v1#p1"],
                },
                {
                    "objection_id": "H1",
                    "role_axis": 11,
                    "proposal_id": "p0",
                    "blocking": True,
                    "predicate": "acceptance test must match site plan",
                    "state": "closed",
                    "closure_evidence": ["src-2@v1#p2"],
                },
            ],
            utc_iso=utc,
        )
        assert all(o.state == "open" for o in recorded)
        assert len(proposed) == 2
        assert len(ledger.open_blocking_objections("run-k12-1")) == 2
        assert len(ledger.carry_forward_snapshot("run-k12-1")) == 2

        # SQLite append-only trigger prevents mutation or deletion
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            stores.sessions.execute("UPDATE ledger_entries SET state = 'closed'")

        # Reject closure with empty evidence, unverified predicate, or out-of-packet passage IDs
        with pytest.raises(ContractValidationError, match="predicate not satisfied"):
            ledger.close_by_verifier(
                run_id="run-k12-1",
                attempt_id="att-1",
                objection_id="R1",
                evidence_ids=["src-1@v1#p1"],
                allowed_passage_ids=allowed,
                predicate_satisfied=False,
                utc_iso=utc,
            )
        with pytest.raises(ContractValidationError, match="without non-empty"):
            ledger.close_by_verifier(
                run_id="run-k12-1",
                attempt_id="att-1",
                objection_id="R1",
                evidence_ids=[],
                allowed_passage_ids=allowed,
                predicate_satisfied=True,
                utc_iso=utc,
            )
        with pytest.raises(ContractValidationError, match="unknown passages"):
            ledger.close_by_verifier(
                run_id="run-k12-1",
                attempt_id="att-1",
                objection_id="R1",
                evidence_ids=["outside-packet#p9"],
                allowed_passage_ids=allowed,
                predicate_satisfied=True,
                utc_iso=utc,
            )

        # Verifier closes R1 cleanly -> H1 remains open
        closed_r1 = ledger.close_by_verifier(
            run_id="run-k12-1",
            attempt_id="att-1",
            objection_id="R1",
            evidence_ids=["src-1@v1#p1"],
            allowed_passage_ids=allowed,
            predicate_satisfied=True,
            utc_iso="2026-11-23T19:01:00Z",
        )
        assert closed_r1.state == "closed" and closed_r1.closed_by == "verifier"
        open_rem = ledger.open_blocking_objections("run-k12-1")
        assert [o.objection_id for o in open_rem] == ["H1"]
    finally:
        stores.close()


def test_dvss_p02_pareto_options_feasibility_and_units() -> None:
    """T-UNIT-FN-P02-01..04: Infeasible filtered first, <2 bypass, unit mismatch conflict."""
    objectives = [
        ParetoObjective(name="cost_usd", direction="min", unit="USD"),
        ParetoObjective(name="throughput_mbps", direction="max", unit="Mbps"),
    ]
    options = [
        CandidateOption(
            option_id="opt-infeas",
            label="Unlicensed vendor",
            feasible=False,
            metrics={"cost_usd": 100.0, "throughput_mbps": 5000.0},
            units={"cost_usd": "USD", "throughput_mbps": "Mbps"},
            infeasibility_reason="Fails PoE power budget",
        ),
        CandidateOption(
            option_id="opt-a",
            label="Candidate A",
            feasible=True,
            metrics={"cost_usd": 1200.0, "throughput_mbps": 1200.0},
            units={"cost_usd": "USD", "throughput_mbps": "Mbps"},
        ),
        CandidateOption(
            option_id="opt-b-dom",
            label="Dominated option",
            feasible=True,
            metrics={"cost_usd": 1500.0, "throughput_mbps": 1000.0},
            units={"cost_usd": "USD", "throughput_mbps": "Mbps"},
        ),
        CandidateOption(
            option_id="opt-c",
            label="High throughput upgrade",
            feasible=True,
            metrics={"cost_usd": 1800.0, "throughput_mbps": 2400.0},
            units={"cost_usd": "USD", "throughput_mbps": "Mbps"},
        ),
    ]
    _validate_fn_contract(
        "p02",
        "in",
        {
            "options": [
                {
                    "option_id": o.option_id,
                    "label": o.label,
                    "feasible": o.feasible,
                    "metrics": dict(o.metrics),
                    "units": dict(o.units),
                    "infeasibility_reason": o.infeasibility_reason,
                }
                for o in options
            ],
            "objectives": [
                {"name": obj.name, "direction": obj.direction, "unit": obj.unit}
                for obj in objectives
            ],
        },
    )

    res = filter_pareto_options(options=options, objectives=objectives)
    assert res.applied is True
    assert [o.option_id for o in res.retained] == ["opt-a", "opt-c"]
    assert res.dominated == ("opt-b-dom",)
    assert res.infeasible == ("opt-infeas",)
    assert res.unit_conflicts == ()
    _validate_fn_contract(
        "p02",
        "out",
        {
            "applied": res.applied,
            "retained_ids": [o.option_id for o in res.retained],
            "dominated_ids": list(res.dominated),
            "infeasible_ids": list(res.infeasible),
            "unit_conflicts": [],
        },
    )

    # Fewer than 2 feasible options bypasses dominance filtering
    single = filter_pareto_options(options=options[:2], objectives=objectives)
    assert single.applied is False
    assert [o.option_id for o in single.retained] == ["opt-a"]

    # Incompatible units recorded explicitly without unsafe cross-unit elimination
    eur_opt = CandidateOption(
        option_id="opt-eur",
        label="Euro quote",
        feasible=True,
        metrics={"cost_usd": 900.0, "throughput_mbps": 1200.0},
        units={"cost_usd": "EUR", "throughput_mbps": "Mbps"},
    )
    conflict_res = filter_pareto_options(
        options=[options[1], eur_opt],
        objectives=objectives,
    )
    assert len(conflict_res.unit_conflicts) == 1
    assert conflict_res.unit_conflicts[0].actual_unit == "EUR"


@pytest.mark.asyncio
async def test_h9_writer_synthesis_order_minority_and_inline_citations() -> None:
    """H9 writer orders strictly by synthesis_weight, keeps objections/minorities & extracts IDs."""
    assert WRITER_PROMPT_VERSION == "writer-1.0.0"
    cfg = load_config(CONFIG_DIR)
    writer = WriterService()

    findings = [
        RoleFinding(
            role_axis=11,
            role_name="Harmonizer",
            profile_id="[ROLE:11.1]",
            scope="site-acceptance",
            assertion="Minority caution: site acceptance schedule needs signed appendix.",
            passage_ids=("src-2@v1#p2",),
            minority=True,
        ),
        RoleFinding(
            role_axis=8,
            role_name="Scholar",
            profile_id="[ROLE:8.1]",
            scope="rf-equivalence",
            assertion="Candidate B satisfies 5 GHz link budget in corridor tests.",
            passage_ids=("src-1@v1#p1",),
            minority=False,
        ),
    ]
    open_objs = [
        LedgerObjection(
            objection_id="R1",
            role_axis=10,
            proposal_id="p0",
            blocking=True,
            predicate="Buyer must sign change order before cutover",
            state="open",
        )
    ]
    packet = writer.build_packet(
        question="Can Candidate B replace Candidate A?",
        proposal_id="p0",
        findings=findings,
        supported_claims=[{"claim_id": "c1", "assertion": "RF budget holds [src-1@v1#p1]."}],
        open_objections=open_objs,
        pareto_options=[],
        passages=[
            {"passage_id": "src-1@v1#p1", "content_str": "Candidate B passes 5 GHz RF budget."},
            {
                "passage_id": "src-2@v1#p2",
                "content_str": "Acceptance appendix requires buyer sign-off.",
            },
        ],
        conduct_config=cfg.conduct,
    )
    assert [f.role_axis for f in packet.ordered_findings] == [8, 11]
    assert "Never turn an open blocking objection into approval" in packet.system_instruction
    assert "Never drop a minority finding" in packet.system_instruction

    fake = FakeModel()
    fake.enqueue_response(
        {
            "candidates": [
                {
                    "index": 0,
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "text": (
                                    "Candidate B passes RF checks [src-1@v1#p1], subject to "
                                    "site acceptance [src-2@v1#p2] and resolving open objection "
                                    "R1 [bogus#9]."
                                )
                            }
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "modelVersion": "gemini-4-carbon-001",
        }
    )
    res = await writer.draft(
        packet=packet,
        model_port=fake,
        model_id="gemini-4-carbon",
        api_key="test-key",
    )
    assert res.cited_passage_ids == ("src-1@v1#p1", "src-2@v1#p2")
    assert extract_inline_citations(
        "Check [src-1@v1#p1] only.", allowed_passage_ids=packet.allowed_passage_ids
    ) == ("src-1@v1#p1",)
