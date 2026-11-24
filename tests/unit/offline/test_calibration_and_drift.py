"""Tests for Phase 6 O1 calibration, held-out sealing, CUSUM drift, and strict recovery."""

from __future__ import annotations

import base64
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
import jsonschema
import pytest

from dle.config import load_config
from dle.edge import GatewaySettings, create_app
from dle.errors import CalibrationError, ContaminationError
from dle.host.services.calibration import (
    HeldoutHashRegistry,
    PilotTrajectory,
    assert_no_heldout_contamination,
    calibrate_cusum_parameters,
    compute_calibration_artifact_sha256,
    compute_cohen_kappa,
    compute_query_item_hash,
    load_calibration_artifact,
    load_heldout_hash_registry,
    load_pilot_dataset,
    run_offline_calibration,
    select_crc_threshold,
)
from dle.host.services.release import CalibrationArtifact, evaluate_release_gate
from dle.host.services.scorer import ScoredClaim, TerminalScore
from dle.models import FakeModel
from dle.tools.calibrate import main as calibrate_cli_main
from dle.tools.verify_receipt import verify_bundle_zip

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_trajectory(
    idx: int,
    *,
    u: float,
    hard_gate: bool = True,
    loss_a: float = 0.0,
    loss_b: float = 0.0,
    loss_adj: float = 0.0,
    volatility: str = "technical",
    tier: int = 1,
) -> PilotTrajectory:
    question = f"Pilot query {idx} on hazardous seal tolerance."
    as_of = "2026-11-20"
    sources = (f"src-{idx:04d}",)
    return PilotTrajectory(
        item_id=f"P-{idx:04d}",
        question=question,
        as_of_date=as_of,
        source_set=sources,
        tier=tier,
        domain="warehouse_logistics",
        hard_gate=hard_gate,
        terminal_u=u,
        grader_a_loss=loss_a,
        grader_b_loss=loss_b,
        adjudicated_loss=loss_adj,
        decisive_claim="Seal tolerance claim",
        author="test-author",
        license_id="CC-BY-4.0",
        volatility_class=volatility,
        query_hash=compute_query_item_hash(
            question=question,
            as_of_date=as_of,
            source_set=sources,
        ),
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n",
        encoding="utf-8",
    )


def test_crc_paper_16b_checkable_example_and_strict_less_than() -> None:
    """Reproduce paper §16b exact example (n=300, alpha=.01) and strict `<` ties."""
    # Checkable example from §16b: 300 queries with observed losses 0, 2, 3 at three thresholds.
    items: list[PilotTrajectory] = []
    # Put 2 full errors between [0.10, 0.20) -> u = 0.15
    items.append(_make_trajectory(1, u=0.15, loss_a=1.0, loss_b=1.0, loss_adj=1.0))
    items.append(_make_trajectory(2, u=0.15, loss_a=1.0, loss_b=1.0, loss_adj=1.0))
    # Put 1 error on [0.20, 0.30) -> u = 0.20 (tests strict u < t boundary too)
    items.append(_make_trajectory(3, u=0.20, loss_a=1.0, loss_b=1.0, loss_adj=1.0))
    for k in range(4, 301):
        items.append(_make_trajectory(k, u=0.05, loss_a=0.0, loss_b=0.0, loss_adj=0.0))

    crc = select_crc_threshold(
        items,
        alpha=0.01,
        grid_values=[0.0, 0.10, 0.20, 0.30],
    )
    # 1/301 <= .01, 3/301 <= .01, 4/301 > .01 => middle cutoff 0.20 wins; tie u==0.20 excluded.
    assert crc.threshold == 0.20
    assert crc.accepted_loss_sum == 2.0
    assert crc.corrected_risk == pytest.approx(3.0 / 301.0, abs=1e-6)
    assert crc.accepted_count == 299

    # Small sample n=5, alpha=0.05 => (0+1)/(5+1) = 1/6 > 0.05 => no positive threshold qualifies.
    tiny = [_make_trajectory(i, u=0.01) for i in range(5)]
    crc_zero = select_crc_threshold(tiny, alpha=0.05, grid_step=0.05)
    assert crc_zero.threshold == 0.0
    assert crc_zero.accepted_count == 0
    assert crc_zero.empirical_coverage == 0.0


def test_cohen_kappa_three_level_scale_and_low_kappa_rejection(tmp_path: Path) -> None:
    """Verify exact 3-level Cohen's kappa math and rejection when kappa < 0.6."""
    perfect = [_make_trajectory(i, u=0.1, loss_a=0.5, loss_b=0.5, loss_adj=0.5) for i in range(10)]
    res_perf = compute_cohen_kappa(perfect)
    assert res_perf.kappa == 1.0
    assert res_perf.exact_agreement == 1.0
    assert res_perf.adjudication_rate == 0.0

    # Construct balanced 3-class table with minor disagreement: kappa clearly computable
    mixed = [
        *[_make_trajectory(i, u=0.1, loss_a=0.0, loss_b=0.0, loss_adj=0.0) for i in range(10)],
        *[_make_trajectory(10 + i, u=0.3, loss_a=0.5, loss_b=0.5, loss_adj=0.5) for i in range(8)],
        *[_make_trajectory(20 + i, u=0.8, loss_a=1.0, loss_b=1.0, loss_adj=1.0) for i in range(8)],
        _make_trajectory(30, u=0.3, loss_a=0.0, loss_b=0.5, loss_adj=0.5),
        _make_trajectory(31, u=0.4, loss_a=0.5, loss_b=1.0, loss_adj=0.5),
    ]
    res_mix = compute_cohen_kappa(mixed)
    assert res_mix.kappa >= 0.85
    assert res_mix.adjudication_rate == pytest.approx(2.0 / 28.0, abs=1e-6)

    # Low-kappa dataset must be rejected by O1 calibration
    bad_rows: list[dict[str, object]] = []
    for i in range(20):
        a = 0.0 if i % 2 == 0 else 1.0
        b = 1.0 if i % 2 == 0 else 0.0
        q = f"Disagreed pilot query {i}"
        src = [f"src-lowk-{i}"]
        bad_rows.append(
            {
                "item_id": f"LOWK-{i:02d}",
                "question": q,
                "as_of_date": "2026-11-20",
                "source_set": src,
                "tier": 1,
                "domain": "general",
                "hard_gate": True,
                "terminal_u": 0.15,
                "grader_a_loss": a,
                "grader_b_loss": b,
                "adjudicated_loss": 0.5,
                "decisive_claim": "claim",
                "author": "qa",
                "license_id": "CC-BY-4.0",
                "query_hash": compute_query_item_hash(
                    question=q, as_of_date="2026-11-20", source_set=src
                ),
            }
        )
    lowk_path = tmp_path / "low_kappa.jsonl"
    _write_jsonl(lowk_path, bad_rows)
    cfg = load_config(REPO_ROOT / "config")
    with pytest.raises(CalibrationError, match="Cohen's kappa"):
        run_offline_calibration(
            pilot_path=lowk_path,
            heldout_registry_path=REPO_ROOT / "offline" / "registry" / "heldout_hashes.json",
            artifact_id="cal-lowk",
            policy_sha256=cfg.policy_sha256,
            model_versions={"gemini-4-carbon": "gemini-4-carbon-001"},
            min_kappa=0.6,
        )


def test_heldout_contamination_guard_refuses_sealed_hashes(tmp_path: Path) -> None:
    """ContaminationError aborts O1 calibration if any hash hits heldout_hashes.json."""
    committed_reg = load_heldout_hash_registry(
        REPO_ROOT / "offline" / "registry" / "heldout_hashes.json"
    )
    assert committed_reg.counts_by_set == {"heldout_test": 150, "heldout_challenge": 100}
    assert len(committed_reg.hashes) == 250

    heldout_q = "Do not leak sealed evaluation question into errors."
    secret_item = PilotTrajectory(
        item_id="CONTAM-001",
        question=heldout_q,
        as_of_date="2026-11-20",
        source_set=("src-contam-1",),
        tier=2,
        domain="safety",
        hard_gate=True,
        terminal_u=0.1,
        grader_a_loss=0.0,
        grader_b_loss=0.0,
        adjudicated_loss=0.0,
        decisive_claim="claim",
        author="qa",
        license_id="CC-BY-4.0",
        query_hash=compute_query_item_hash(
            question=heldout_q, as_of_date="2026-11-20", source_set=("src-contam-1",)
        ),
    )
    test_reg = HeldoutHashRegistry(
        schema_version="1.0.0",
        file_sha256="a" * 64,
        hashes=frozenset({secret_item.query_hash or ""}),
        counts_by_set={"heldout_test": 1},
    )
    with pytest.raises(ContaminationError) as exc_info:
        assert_no_heldout_contamination([secret_item], test_reg)
    assert "CONTAM-001" in exc_info.value.message
    assert "Do not leak" not in exc_info.value.message

    # End-to-end CLI exit code 2 without producing an output artifact
    heldout_file = tmp_path / "heldout.json"
    heldout_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "sets": {"heldout_test": {"target_size": 1, "hashes": [secret_item.query_hash]}},
            }
        ),
        encoding="utf-8",
    )
    pilot_file = tmp_path / "pilot_contaminated.jsonl"
    _write_jsonl(
        pilot_file,
        [
            {
                "item_id": secret_item.item_id,
                "question": heldout_q,
                "as_of_date": secret_item.as_of_date,
                "source_set": list(secret_item.source_set),
                "tier": 2,
                "domain": "safety",
                "hard_gate": True,
                "terminal_u": 0.1,
                "grader_a_loss": 0.0,
                "grader_b_loss": 0.0,
                "adjudicated_loss": 0.0,
                "decisive_claim": "claim",
                "author": "qa",
                "license_id": "CC-BY-4.0",
            }
        ],
    )
    out_art = tmp_path / "should_not_exist.json"
    exit_code = calibrate_cli_main(
        [
            "--pilot",
            str(pilot_file),
            "--heldout-registry",
            str(heldout_file),
            "--config-dir",
            str(REPO_ROOT / "config"),
            "--output",
            str(out_art),
            "--artifact-id",
            "cal-contam",
        ]
    )
    assert exit_code == 2
    assert not out_art.exists()


def test_cusum_calibration_and_p14_contract_validation(tmp_path: Path) -> None:
    """Verify deterministic CUSUM calibration, fail-closed u=1 inclusion, and P14 contracts."""
    scores = [0.05] * 60 + [0.30] * 25 + [1.0] * 15
    c1 = calibrate_cusum_parameters(scores, drift_delta=0.02, target_arl=1000, seed=42)
    c2 = calibrate_cusum_parameters(scores, drift_delta=0.02, target_arl=1000, seed=42)
    assert c1 == c2
    assert c1.mu_0 == pytest.approx(sum(scores) / len(scores), abs=1e-6)
    assert c1.drift_lambda > 0.0
    assert c1.estimated_arl >= 1000.0

    # Validate committed artifact and P14 output schemas
    cfg = load_config(REPO_ROOT / "config")
    artifact_doc, p14_out = run_offline_calibration(
        pilot_path=REPO_ROOT / "offline" / "pilot" / "pilot_graded_100.jsonl",
        heldout_registry_path=REPO_ROOT / "offline" / "registry" / "heldout_hashes.json",
        artifact_id="cal-test-p14",
        policy_sha256=cfg.policy_sha256,
        model_versions={"gemini-4-carbon": "gemini-4-carbon-001"},
        seed=20261123,
        approve=True,
    )
    cal_schema = json.loads((REPO_ROOT / "contracts" / "calibration.schema.json").read_text())
    p14_schema = json.loads((REPO_ROOT / "contracts" / "functions" / "p14.out.json").read_text())
    jsonschema.validate(artifact_doc, cal_schema)
    jsonschema.validate(p14_out, p14_schema)

    out_path = tmp_path / "cal-test-p14.json"
    out_path.write_text(json.dumps(artifact_doc), encoding="utf-8")
    loaded = load_calibration_artifact(out_path, require_approved=True)
    assert loaded.artifact_id == "cal-test-p14"
    assert loaded.status == "approved"


@pytest.mark.asyncio
async def test_calibration_artifact_tamper_unapproved_and_fail_closed_gateway(
    tmp_path: Path,
) -> None:
    """Tampered or unapproved calibration fails closed at both unit gate and FastAPI startup."""
    committed = json.loads(
        (REPO_ROOT / "config" / "calibration" / "cal-phase6-v1.json").read_text(encoding="utf-8")
    )

    tampered = dict(committed)
    tampered["threshold"] = 0.99
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(CalibrationError, match="SHA-256 mismatch"):
        load_calibration_artifact(tampered_path)

    staged = dict(committed)
    staged["status"] = "staged"
    staged["approved_by"] = None
    staged["approved_utc"] = None
    staged["artifact_sha256"] = compute_calibration_artifact_sha256(staged)
    staged_path = tmp_path / "staged.json"
    staged_path.write_text(json.dumps(staged), encoding="utf-8")
    with pytest.raises(CalibrationError, match="staged"):
        load_calibration_artifact(staged_path, require_approved=True)

    staged_obj = load_calibration_artifact(staged_path, require_approved=False)
    sample_claim = ScoredClaim(
        claim_id="c1",
        proposal_id="p0",
        assertion="Test assertion",
        binding=False,
        scope_label="general",
        passage_ids=("psg-1",),
        entailment=0.95,
        provenance=1.0,
        belief=1.0,
        support_z=0.95,
        contradiction=0.0,
        authority_status="primary_text",
        span_start=0,
        span_end=14,
    )
    gate = evaluate_release_gate(
        schema_scope_valid=True,
        claims=[sample_claim],
        all_binding_verified=True,
        open_blocking_objections=[],
        score=TerminalScore(
            u=0.05, min_z_j=0.95, mean_z=0.95, min_b_j=1.0, d=0.0, weakest_claim_id="c1"
        ),
        calibration=staged_obj,
        drift_latched=False,
        cusum=0.0,
    )
    assert gate.decision == "block"
    assert gate.block_reason == "unapproved_calibration_artifact"
    assert gate.drift_latched is True

    # Gateway startup with tampered DLE_CALIBRATION_PATH must fail closed and latch drift
    app = create_app(
        settings=GatewaySettings(
            bind_address="127.0.0.1",
            port=8740,
            allow_lan=False,
            client_api_keys=frozenset({"k-cli"}),
            admin_api_keys=frozenset({"k-adm"}),
            model_backend="fake",
            config_dir=REPO_ROOT / "config",
            ui_dist_dir=None,
            data_dir=tmp_path / "data",
            keys_dir=tmp_path / "keys",
            calibration_path=tampered_path,
        ),
        model_port=FakeModel(),
    )
    assert app.state.dle.calibration is None
    assert app.state.dle.registry.drift_latched is True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8740"
    ) as client:
        h = (await client.get("/healthz")).json()
        assert h["status"] == "degraded"
        assert h["driftLatch"] == "tripped"
        assert h["calibrationArtifactId"] is None
        res = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers={"x-goog-api-key": "k-cli"},
            json={"contents": [{"role": "user", "parts": [{"text": "Any query."}]}]},
        )
        assert res.status_code == 200
        assert res.headers["x-dle-release-mode"] == "held"
        assert isinstance(CalibrationArtifact, type)


def test_committed_phase6_pilot_artifact_passes_gate_thresholds() -> None:
    """Committed Phase 6 pilot artifact satisfies DLE-EVL-001, DLE-EVL-002, and §16b."""
    cal_path = REPO_ROOT / "config" / "calibration" / "cal-phase6-v1.json"
    cal = load_calibration_artifact(cal_path, require_approved=True, min_kappa=0.6)
    raw = json.loads(cal_path.read_text(encoding="utf-8"))
    pilot_items, _sha = load_pilot_dataset(
        REPO_ROOT / "offline" / "pilot" / "pilot_graded_100.jsonl"
    )
    heldout = load_heldout_hash_registry(REPO_ROOT / "offline" / "registry" / "heldout_hashes.json")
    assert_no_heldout_contamination(pilot_items, heldout)

    assert cal.artifact_id == "cal-phase6-v1"
    assert cal.n_cal == 100
    assert cal.alpha == pytest.approx(0.05)
    assert cal.cohen_kappa is not None and cal.cohen_kappa >= 0.6
    assert raw["corrected_risk"] <= 0.05
    assert raw["estimated_in_control_arl"] >= 1000.0
    assert raw["tier_distribution"] == {"tier_1": 40, "tier_2": 35, "tier_3": 25}
    assert 0.15 <= cal.threshold <= 0.50


@pytest.mark.asyncio
async def test_strict_mode_drift_trip_hold_recalibrate_reset_and_offline_verify(
    tmp_path: Path,
) -> None:
    """Strict drift latch -> NOTICE-HOLD-05 -> recalibrate -> reset -> ZIP verify."""
    cfg_dir = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", cfg_dir)

    settings = GatewaySettings(
        bind_address="127.0.0.1",
        port=8740,
        allow_lan=False,
        client_api_keys=frozenset({"cli-key"}),
        admin_api_keys=frozenset({"adm-key"}),
        model_backend="fake",
        config_dir=cfg_dir,
        ui_dist_dir=None,
        data_dir=tmp_path / "data",
        keys_dir=tmp_path / "keys",
        calibration_path=cfg_dir / "calibration" / "cal-phase6-v1.json",
    )
    fake = FakeModel()
    app = create_app(settings=settings, model_port=fake)
    transport = httpx.ASGITransport(app=app)
    cli_h = {"x-goog-api-key": "cli-key"}
    adm_h = {"X-DLE-Admin-Key": "adm-key"}

    clause = "Batch P6-A1 enforces calibrated torque 42 Nm during turbine assembly."
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8740") as client:
        h0 = (await client.get("/healthz")).json()
        assert h0["status"] == "ok"
        assert h0["driftLatch"] == "clear"
        assert h0["calibrationArtifactId"] == "cal-phase6-v1"

        src_resp = await client.post(
            "/admin/sources",
            headers=adm_h,
            json={
                "title": "Turbine Torque Spec",
                "authorityClass": "primary_text",
                "content": {
                    "mimeType": "text/plain",
                    "data": base64.b64encode(clause.encode("utf-8")).decode("ascii"),
                },
            },
        )
        assert src_resp.status_code == 201

        # 1. Baseline strict query releases cleanly under cal-phase6-v1
        r1 = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers=cli_h,
            json={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
        )
        assert r1.status_code == 200
        assert r1.headers["x-dle-release-mode"] == "released"
        rid_released_1 = r1.headers["x-dle-receipt"]
        rcpt1 = (await client.get(f"/v1/receipts/{rid_released_1}", headers=cli_h)).json()
        assert rcpt1["payload"]["calibration"]["artifact_id"] == "cal-phase6-v1"

        # 2. Trip CUSUM drift latch cleanly via sustained high-uncertainty unmatched queries
        cal = app.state.dle.calibration
        assert cal is not None
        # Seed near threshold so 2 bad ungrounded queries deterministically cross drift_lambda
        app.state.dle.ops_repo.upsert_drift_state(
            c_t=round(max(0.0, cal.drift_lambda - 0.10), 6),
            mu0=cal.mu_0,
            delta=cal.drift_delta,
            lambda_val=cal.drift_lambda,
            is_latched=False,
            latch_reason=None,
            updated_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        unmatched = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers=cli_h,
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": "Completely unmatched cryogenic helium valve procedure 99Z."}
                        ],
                    }
                ]
            },
        )
        assert unmatched.status_code == 200

        h_tripped = (await client.get("/healthz")).json()
        assert h_tripped["driftLatch"] == "tripped"
        assert h_tripped["status"] == "degraded"

        # 3. Same grounded query under strict profile MUST hold with NOTICE-HOLD-05
        r_held = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers=cli_h,
            json={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
        )
        assert r_held.status_code == 200
        assert r_held.headers["x-dle-release-mode"] == "held"
        assert "verification is paused while the system is recalibrated" in r_held.text
        rid_held = r_held.headers["x-dle-receipt"]
        rcpt_held = (await client.get(f"/v1/receipts/{rid_held}", headers=cli_h)).json()
        assert rcpt_held["payload"]["decision"]["drift_latched"] is True
        assert rcpt_held["payload"]["decision"]["release_mode"] == "review_required"

        # Advisory profile under latched drift annotates with NOTICE-ADV-02
        r_adv = await client.post(
            "/v1beta/models/dle-13axis-advisory:generateContent",
            headers=cli_h,
            json={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
        )
        assert r_adv.status_code == 200
        assert r_adv.headers["x-dle-release-mode"] == "released_advisory"
        assert "verification is being recalibrated; this answer is not certified." in r_adv.text

        # 4. Unknown or staged artifact IDs are refused on /admin/drift/reset
        bad_reset = await client.post(
            "/admin/drift/reset",
            headers=adm_h,
            json={"calibrationArtifactId": "cal-missing-id", "confirm": "RESET"},
        )
        assert bad_reset.status_code == 400

        cal_raw = json.loads((cfg_dir / "calibration" / "cal-phase6-v1.json").read_text())
        cal_raw["artifact_id"] = "cal-staged-v2"
        cal_raw["status"] = "staged"
        cal_raw["approved_by"] = None
        cal_raw["approved_utc"] = None
        cal_raw["artifact_sha256"] = compute_calibration_artifact_sha256(cal_raw)
        (cfg_dir / "calibration" / "cal-staged-v2.json").write_text(
            json.dumps(cal_raw), encoding="utf-8"
        )
        staged_reset = await client.post(
            "/admin/drift/reset",
            headers=adm_h,
            json={"calibrationArtifactId": "cal-staged-v2", "confirm": "RESET"},
        )
        assert staged_reset.status_code == 400
        assert (await client.get("/healthz")).json()["driftLatch"] == "tripped"

        # 5. Recalibrate via O1 CLI to produce approved cal-phase6-v2 and reset
        cal_v2_path = cfg_dir / "calibration" / "cal-phase6-v2.json"
        cli_rc = calibrate_cli_main(
            [
                "--pilot",
                str(REPO_ROOT / "offline" / "pilot" / "pilot_graded_100.jsonl"),
                "--heldout-registry",
                str(REPO_ROOT / "offline" / "registry" / "heldout_hashes.json"),
                "--config-dir",
                str(cfg_dir),
                "--output",
                str(cal_v2_path),
                "--artifact-id",
                "cal-phase6-v2",
                "--approve",
                "--approved-by",
                "release-manager",
            ]
        )
        assert cli_rc == 0

        ok_reset = await client.post(
            "/admin/drift/reset",
            headers=adm_h,
            json={"calibrationArtifactId": "cal-phase6-v2", "confirm": "RESET"},
        )
        assert ok_reset.status_code == 204
        h_clear = (await client.get("/healthz")).json()
        assert h_clear["status"] == "ok"
        assert h_clear["driftLatch"] == "clear"
        assert h_clear["calibrationArtifactId"] == "cal-phase6-v2"

        # 6. Strict query releases again citing cal-phase6-v2
        r2 = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers=cli_h,
            json={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
        )
        assert r2.status_code == 200
        assert r2.headers["x-dle-release-mode"] == "released"
        rid_released_2 = r2.headers["x-dle-receipt"]
        rcpt2 = (await client.get(f"/v1/receipts/{rid_released_2}", headers=cli_h)).json()
        assert rcpt2["payload"]["calibration"]["artifact_id"] == "cal-phase6-v2"

        # 7. Export signed receipt ZIP and verify offline via verify_bundle_zip
        exp = await client.post(
            "/admin/receipts/export",
            headers=adm_h,
            json={"from": "2020-01-01T00:00:00Z", "to": "2099-01-01T00:00:00Z"},
        )
        assert exp.status_code == 200
        bundle_path = tmp_path / "export_bundle.zip"
        bundle_path.write_bytes(exp.content)
        ok, errs = verify_bundle_zip(bundle_path)
        assert ok is True, f"bundle verification failed: {errs}"
        assert errs == []


@pytest.mark.asyncio
async def test_model_version_change_latches_drift_and_resets_cleanly(tmp_path: Path) -> None:
    """Changing upstream modelVersion relative to calibration artifact trips drift latch."""
    settings = GatewaySettings(
        bind_address="127.0.0.1",
        port=8740,
        allow_lan=False,
        client_api_keys=frozenset({"cli-key"}),
        admin_api_keys=frozenset({"adm-key"}),
        model_backend="fake",
        config_dir=REPO_ROOT / "config",
        ui_dist_dir=None,
        data_dir=tmp_path / "data",
        keys_dir=tmp_path / "keys",
        calibration_path=REPO_ROOT / "config" / "calibration" / "cal-phase6-v1.json",
    )
    app = create_app(settings=settings)
    # Construct FakeModel with drifted suffix referencing runtime's ModelRegistry
    app.state.dle.model_port = FakeModel(
        registry=app.state.dle.registry,
        default_version_suffix="999-drifted",
    )
    transport = httpx.ASGITransport(app=app)
    cli_h = {"x-goog-api-key": "cli-key"}
    adm_h = {"X-DLE-Admin-Key": "adm-key"}

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8740") as client:
        clause = "Lot MV-10 requires double containment verification."
        await client.post(
            "/admin/sources",
            headers=adm_h,
            json={
                "title": "Containment Rule",
                "authorityClass": "primary_text",
                "content": {
                    "mimeType": "text/plain",
                    "data": base64.b64encode(clause.encode("utf-8")).decode("ascii"),
                },
            },
        )
        res = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers=cli_h,
            json={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
        )
        assert res.status_code == 200
        assert res.headers["x-dle-release-mode"] == "held"
        assert app.state.dle.registry.drift_latched is True
        assert (await client.get("/healthz")).json()["driftLatch"] == "tripped"
