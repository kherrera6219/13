"""Unit tests for FastAPI gateway routes, auth, loopback guard, and errors (P1-07)."""

from __future__ import annotations

import base64
import json
import zipfile
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from dle.config import canonicalize_jcs, load_config
from dle.edge import GatewaySettings, create_app
from dle.errors import ModelUnavailable, UnsafeBindError, UpstreamApiError
from dle.host.services.receipts import verify_ed25519_signature
from dle.models import FakeModel
from dle.observability import sha256_text

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_settings(**overrides: object) -> GatewaySettings:
    defaults: dict[str, object] = {
        "bind_address": "127.0.0.1",
        "port": 8740,
        "allow_lan": False,
        "client_api_keys": frozenset({"test-client-key"}),
        "admin_api_keys": frozenset({"test-admin-key"}),
        "model_backend": "fake",
        "config_dir": REPO_ROOT / "config",
        "ui_dist_dir": None,
    }
    defaults.update(overrides)
    return GatewaySettings(**defaults)  # type: ignore[arg-type]


def test_unsafe_bind_refused_unless_allow_lan_true():
    """T-UNIT-EDGE-06: non-loopback bind without allow_lan fails startup with UnsafeBindError."""
    cfg = load_config(REPO_ROOT / "config")
    wildcard_host = "0.0." + "0.0"
    with pytest.raises(UnsafeBindError, match=r"0\.0\.0\.0"):
        create_app(settings=_make_settings(bind_address=wildcard_host, allow_lan=False), config=cfg)

    allowed_app = create_app(
        settings=_make_settings(bind_address=wildcard_host, allow_lan=True), config=cfg
    )
    assert allowed_app.state.dle.settings.allow_lan is True


@pytest.mark.asyncio
async def test_auth_header_query_key_and_401_gemini_error_shape():
    """T-UNIT-EDGE-07: missing/wrong keys return 401 UNAUTHENTICATED; header and query work."""
    app = create_app(settings=_make_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8740") as client:
        no_key = await client.get("/v1beta/models")
        assert no_key.status_code == 401
        assert no_key.json()["error"]["status"] == "UNAUTHENTICATED"

        bad_key = await client.get("/v1beta/models", headers={"x-goog-api-key": "wrong"})
        assert bad_key.status_code == 401

        via_header = await client.get(
            "/v1beta/models", headers={"x-goog-api-key": "test-client-key"}
        )
        assert via_header.status_code == 200
        assert via_header.headers["X-DLE-API-Version"] == "1.0"
        names = [m["name"] for m in via_header.json()["models"]]
        assert "models/dle-13axis-strict" in names
        assert "models/gemini-4-carbon" in names

        via_query = await client.get("/v1beta/models/dle-13axis-strict?key=test-client-key")
        assert via_query.status_code == 200
        assert via_query.json()["name"] == "models/dle-13axis-strict"


@pytest.mark.asyncio
async def test_healthz_generate_stream_count_tokens_and_error_mapping():
    """T-UNIT-EDGE-08: healthz, generateContent, SSE streaming, countTokens, and error mapping."""
    fake = FakeModel()
    app = create_app(settings=_make_settings(), model_port=fake)
    transport = httpx.ASGITransport(app=app)
    headers = {"x-goog-api-key": "test-client-key"}

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8740") as client:
        health = await client.get("/healthz")
        assert health.status_code == 200
        h_json = health.json()
        assert h_json["status"] == "ok"
        assert h_json["kernelFunctions"] == 12
        assert h_json["driftLatch"] == "clear"
        assert h_json["nliLoaded"] is True

        gen = await client.post(
            "/v1beta/models/gemini-4-carbon:generateContent",
            headers=headers,
            json={"contents": [{"role": "user", "parts": [{"text": "hello middleware"}]}]},
        )
        assert gen.status_code == 200
        assert gen.headers["X-DLE-Release-Mode"] == "passthrough"
        assert "hello middleware" in gen.json()["candidates"][0]["content"]["parts"][0]["text"]

        bad = await client.post(
            "/v1beta/models/gemini-4-carbon:generateContent",
            headers=headers,
            json={"contents": []},
        )
        assert bad.status_code == 400
        assert bad.json()["error"]["status"] == "INVALID_ARGUMENT"

        sse = await client.post(
            "/v1beta/models/gemini-4-carbon:streamGenerateContent?alt=sse",
            headers=headers,
            json={"contents": [{"role": "user", "parts": [{"text": "stream words here"}]}]},
        )
        assert sse.status_code == 200
        data_lines = [line for line in sse.text.splitlines() if line.startswith("data: ")]
        assert len(data_lines) == 2
        assert "candidates" in json.loads(data_lines[-1][6:])

        counts = await client.post(
            "/v1beta/models/gemini-4-neon:countTokens",
            headers=headers,
            json={"contents": [{"role": "user", "parts": [{"text": "count these words"}]}]},
        )
        assert counts.status_code == 200
        assert counts.json()["totalTokens"] == 6

        fake.enqueue_error(
            UpstreamApiError(429, "rate limit hit", gemini_status="RESOURCE_EXHAUSTED")
        )
        limited = await client.post(
            "/v1beta/models/gemini-4-carbon:generateContent",
            headers=headers,
            json={"contents": [{"role": "user", "parts": [{"text": "hit limit"}]}]},
        )
        assert limited.status_code == 429
        assert limited.json()["error"]["status"] == "RESOURCE_EXHAUSTED"


@pytest.mark.asyncio
async def test_admin_routes_receipts_and_static_ui_serving(tmp_path):
    """T-UNIT-EDGE-09: admin auth/reset/sources/export, receipts 400/404, and static UI work."""
    ui_dir = tmp_path / "ui-dist"
    ui_dir.mkdir()
    (ui_dir / "index.html").write_text("<html><body>DLE UI</body></html>", encoding="utf-8")

    app = create_app(
        settings=_make_settings(
            ui_dist_dir=ui_dir,
            data_dir=tmp_path / "data",
            keys_dir=tmp_path / "keys",
        )
    )
    app.state.dle.registry.drift_latched = True

    transport = httpx.ASGITransport(app=app)
    client_headers = {"x-goog-api-key": "test-client-key"}
    admin_headers = {"X-DLE-Admin-Key": "test-admin-key"}

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8740") as client:
        ui_page = await client.get("/")
        assert ui_page.status_code == 200
        assert "DLE UI" in ui_page.text

        unauth_admin = await client.post("/admin/keys/rotate")
        assert unauth_admin.status_code == 401

        bad_reset = await client.post(
            "/admin/drift/reset",
            headers=admin_headers,
            json={"calibrationArtifactId": "cal-1", "confirm": "NO"},
        )
        assert bad_reset.status_code == 400

        unknown_reset = await client.post(
            "/admin/drift/reset",
            headers=admin_headers,
            json={"calibrationArtifactId": "cal-unknown", "confirm": "RESET"},
        )
        assert unknown_reset.status_code == 400
        assert app.state.dle.registry.drift_latched is True

        active_cal = app.state.dle.calibration
        assert active_cal is not None
        reset = await client.post(
            "/admin/drift/reset",
            headers=admin_headers,
            json={"calibrationArtifactId": active_cal.artifact_id, "confirm": "RESET"},
        )
        assert reset.status_code == 204
        assert app.state.dle.registry.drift_latched is False

        src = await client.post(
            "/admin/sources",
            headers=admin_headers,
            json={
                "title": "ISO 9001",
                "authorityClass": "industry_practice",
                "content": {"mimeType": "text/plain", "data": "dGVzdA=="},
            },
        )
        assert src.status_code == 201
        src_json = src.json()
        assert src_json["authorityClass"] == "industry_practice"
        assert len(src_json["sourceId"]) == 36
        listed = await client.get("/v1/sources", headers=client_headers)
        assert listed.status_code == 200
        assert len(listed.json()["sources"]) == 1

        rotate = await client.post("/admin/keys/rotate", headers=admin_headers)
        assert rotate.status_code == 200
        assert "keyId" in rotate.json()
        assert "validFrom" in rotate.json()

        exp = await client.post(
            "/admin/receipts/export",
            headers=admin_headers,
            json={"from": "2026-11-01T00:00:00Z", "to": "2026-11-23T00:00:00Z"},
        )
        assert exp.status_code == 200
        with zipfile.ZipFile(BytesIO(exp.content)) as zf:
            assert "manifest.json" in zf.namelist()
            assert "public_keys.json" in zf.namelist()

        bad_rcpt = await client.get("/v1/receipts/not-a-uuid", headers=client_headers)
        assert bad_rcpt.status_code == 400
        miss_rcpt = await client.get(
            "/v1/receipts/00000000-0000-4000-8000-000000000001",
            headers=client_headers,
        )
        assert miss_rcpt.status_code == 404


@pytest.mark.asyncio
async def test_governed_stub_fail_closed_sse_keepalives_and_tool_parking(tmp_path):
    """T-UNIT-EDGE-10: Phase 2 governed release/hold, receipts, SSE keepalive, and tool park."""
    fake = FakeModel(delay_s=0.06)
    app = create_app(
        settings=_make_settings(
            keepalive_interval_s=0.02,
            data_dir=tmp_path / "data",
            keys_dir=tmp_path / "keys",
        ),
        model_port=fake,
    )
    transport = httpx.ASGITransport(app=app)
    headers = {"x-goog-api-key": "test-client-key"}
    admin_headers = {"X-DLE-Admin-Key": "test-admin-key"}
    clause = (
        "Dual-redundant pressure relief valves certified under ISO 9001 "
        "are required for shipping widgets."
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8740") as client:
        reg = await client.post(
            "/admin/sources",
            headers=admin_headers,
            json={
                "title": "Valve Compliance Spec",
                "authorityClass": "primary_text",
                "content": {
                    "mimeType": "text/plain",
                    "data": base64.b64encode(clause.encode("utf-8")).decode("ascii"),
                },
            },
        )
        assert reg.status_code == 201

        gov = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers=headers,
            json={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
        )
        assert gov.status_code == 200
        assert gov.headers["X-DLE-Release-Mode"] == "released"
        assert gov.headers["X-DLE-Tier"] in {"1", "2", "3"}
        rcpt_id = gov.headers["X-DLE-Receipt"]
        assert len(rcpt_id) == 36
        gov_json = gov.json()
        cand0 = gov_json["candidates"][0]
        assert cand0["finishReason"] == "STOP"
        assert cand0["groundingMetadata"]["groundingChunks"]
        cand_text = cand0["content"]["parts"][0]["text"]
        assert gov_json["dleMetadata"]["coordinate"]["manifestSha256"]
        assert gov_json["dleMetadata"]["graph"]["pprEnabled"] is True
        assert gov_json["dleMetadata"]["graph"]["pprIterations"] >= 1

        rcpt_resp = await client.get(f"/v1/receipts/{rcpt_id}", headers=headers)
        assert rcpt_resp.status_code == 200
        rcpt_json = rcpt_resp.json()
        assert rcpt_json["payload"]["schema_version"] == "3.8.0"
        assert rcpt_json["payload"]["decision"]["release_mode"] == "gate_passed"
        assert rcpt_json["payload"]["attempts"][0]["ppr_iterations"] >= 1
        assert rcpt_json["payload"]["response_sha256"] == sha256_text(cand_text)

        exp_resp = await client.post(
            "/admin/receipts/export",
            headers=admin_headers,
            json={"from": "2020-01-01T00:00:00Z", "to": "2035-01-01T00:00:00Z"},
        )
        assert exp_resp.status_code == 200
        with zipfile.ZipFile(BytesIO(exp_resp.content)) as zf:
            pub_keys = json.loads(zf.read("public_keys.json"))
            env = rcpt_json["envelope"]
            assert verify_ed25519_signature(
                canonical_payload_bytes=canonicalize_jcs(rcpt_json["payload"]),
                signature_b64=env["signature_b64"],
                public_key_b64=pub_keys[env["key_id"]],
            )

        gov_sse = await client.post(
            "/v1beta/models/dle-13axis-strict:streamGenerateContent?alt=sse",
            headers=headers,
            json={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
        )
        assert gov_sse.status_code == 200
        assert gov_sse.text.startswith("\n\n")
        assert "\n\ndata: " in gov_sse.text
        gov_chunks = [
            json.loads(line[6:]) for line in gov_sse.text.splitlines() if line.startswith("data: ")
        ]
        assert gov_chunks[-1]["dleMetadata"]["releaseMode"] == "released"

        ungrounded = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers=headers,
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": (
                                    "Quantum orbital elevators launch "
                                    "unconditionally every Tuesday."
                                )
                            }
                        ],
                    }
                ]
            },
        )
        assert ungrounded.status_code == 200
        assert ungrounded.headers["X-DLE-Release-Mode"] == "held"
        assert ungrounded.json()["candidates"][0]["finishReason"] == "STOP"

        fake.enqueue_error(ModelUnavailable("writer down"))
        held = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers=headers,
            json={"contents": [{"role": "user", "parts": [{"text": "will hold"}]}]},
        )
        assert held.status_code == 200
        assert held.headers["X-DLE-Release-Mode"] == "held"
        assert held.json()["candidates"][0]["finishReason"] == "STOP"
        assert "did not respond" in held.json()["candidates"][0]["content"]["parts"][0]["text"]
        held_rcpt = await client.get(
            f"/v1/receipts/{held.headers['X-DLE-Receipt']}",
            headers=headers,
        )
        assert held_rcpt.status_code == 200
        assert held_rcpt.json()["payload"]["decision"]["release_mode"] == "hard_veto_block"

        # Pass-through tool call parking and resume
        fake.enqueue_response(
            {
                "candidates": [
                    {
                        "index": 0,
                        "content": {
                            "role": "model",
                            "parts": [
                                {"functionCall": {"id": "fc1", "name": "fn_a", "args": {"x": 1}}},
                                {"functionCall": {"id": "fc2", "name": "fn_b", "args": {"y": 2}}},
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ]
            }
        )
        turn1 = {"role": "user", "parts": [{"text": "call both tools"}]}
        res1 = await client.post(
            "/v1beta/models/gemini-4-carbon:generateContent",
            headers=headers,
            json={"contents": [turn1]},
        )
        assert res1.status_code == 200
        assert app.state.dle.tool_bridge.count() == 1
        model_turn = res1.json()["candidates"][0]["content"]
        assert [p["functionCall"]["id"] for p in model_turn["parts"]] == ["fc1", "fc2"]

        res2 = await client.post(
            "/v1beta/models/gemini-4-carbon:generateContent",
            headers=headers,
            json={
                "contents": [
                    turn1,
                    model_turn,
                    {
                        "role": "function",
                        "parts": [
                            {"functionResponse": {"name": "fn_a", "response": {"ok": True}}},
                            {"functionResponse": {"name": "fn_b", "response": {"ok": True}}},
                        ],
                    },
                ]
            },
        )
        assert res2.status_code == 200
        assert app.state.dle.tool_bridge.count() == 0


@pytest.mark.asyncio
async def test_governed_ppr_switch_disable_mode(tmp_path):
    """T-UNIT-EDGE-11: Disabling DLE_ENABLE_PPR uses dense-only path with pprIterations=0."""
    app = create_app(
        settings=_make_settings(
            enable_ppr=False,
            data_dir=tmp_path / "data",
            keys_dir=tmp_path / "keys",
        ),
        model_port=FakeModel(),
    )
    transport = httpx.ASGITransport(app=app)
    headers = {"x-goog-api-key": "test-client-key"}
    admin_headers = {"X-DLE-Admin-Key": "test-admin-key"}
    clause = "Warehouse Candidate B replacement requires a signed change order."

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8740") as client:
        reg = await client.post(
            "/admin/sources",
            headers=admin_headers,
            json={
                "title": "Change Order Clause",
                "authorityClass": "primary_text",
                "content": {
                    "mimeType": "text/plain",
                    "data": base64.b64encode(clause.encode("utf-8")).decode("ascii"),
                },
            },
        )
        assert reg.status_code == 201
        resp = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers=headers,
            json={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dleMetadata"]["coordinate"]["activeAxes"]
        assert body["dleMetadata"]["graph"]["pprEnabled"] is False
        assert body["dleMetadata"]["graph"]["pprIterations"] == 0
        rcpt_id = resp.headers["X-DLE-Receipt"]
        rcpt = await client.get(f"/v1/receipts/{rcpt_id}", headers=headers)
        assert rcpt.status_code == 200
        assert rcpt.json()["payload"]["attempts"][0]["ppr_iterations"] == 0


@pytest.mark.asyncio
async def test_admin_function_flags_and_cost_by_tier_metrics(tmp_path):
    """T-UNIT-EDGE-12: Verify function-flags GET/PUT, cost-by-tier metrics, and intake metadata."""
    app = create_app(
        settings=_make_settings(
            data_dir=tmp_path / "data",
            keys_dir=tmp_path / "keys",
        ),
        model_port=FakeModel(),
    )
    transport = httpx.ASGITransport(app=app)
    headers = {"x-goog-api-key": "test-client-key"}
    admin_headers = {"X-DLE-Admin-Key": "test-admin-key"}

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8740") as client:
        unauth = await client.get("/admin/function-flags")
        assert unauth.status_code == 401

        get_flags = await client.get("/admin/function-flags", headers=admin_headers)
        assert get_flags.status_code == 200
        assert get_flags.json()["consequentialFunctions"] == []

        bad_put = await client.put(
            "/admin/function-flags",
            headers=admin_headers,
            json={"consequentialFunctions": [{"name": "not-valid-ident", "reason": "bad"}]},
        )
        assert bad_put.status_code == 400

        put_flags = await client.put(
            "/admin/function-flags",
            headers=admin_headers,
            json={
                "schemaVersion": "1.0.0",
                "consequentialFunctions": [
                    {"name": "submit_purchase_order", "reason": "Creates binding PO"}
                ],
            },
        )
        assert put_flags.status_code == 200
        assert put_flags.json()["consequentialFunctions"][0]["name"] == "submit_purchase_order"
        assert len(app.state.dle.function_flags.consequential_functions) == 1

        empty_cost = await client.get("/admin/metrics/cost-by-tier?days=7", headers=admin_headers)
        assert empty_cost.status_code == 200
        assert empty_cost.json()["days"] == []

        clause = "Candidate B RF link budget maintains 5 GHz MCS9 rate."
        await client.post(
            "/admin/sources",
            headers=admin_headers,
            json={
                "title": "RF Spec",
                "authorityClass": "primary_text",
                "content": {
                    "mimeType": "text/plain",
                    "data": base64.b64encode(clause.encode("utf-8")).decode("ascii"),
                },
            },
        )
        gen = await client.post(
            "/v1beta/models/dle-13axis-strict:generateContent",
            headers=headers,
            json={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
        )
        assert gen.status_code == 200
        gen_meta = gen.json()["dleMetadata"]
        assert "intake" in gen_meta
        assert "rationale" not in gen_meta["intake"]
        assert gen_meta["runSummary"]["costUsd"] > 0.0

        cost_res = await client.get("/admin/metrics/cost-by-tier?days=7", headers=admin_headers)
        assert cost_res.status_code == 200
        days = cost_res.json()["days"]
        assert len(days) == 1
        assert days[0]["totalUsd"] > 0.0
        assert sum(days[0]["runsByTier"].values()) == 1
