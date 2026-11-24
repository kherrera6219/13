"""Official ``google-genai`` Python SDK compatibility tests (GC-01..GC-26 P-cases).

Runs the unmodified Google GenAI Python SDK against a live local DLE middleware
server backed by ``FakeUpstream`` per ``docs/test/gemini_compat_test_plan.md``.
"""

import base64
import json
import time
import zipfile
from io import BytesIO

import httpx
import pytest
from google import genai
from google.genai import errors, types

from dle.config import canonicalize_jcs
from dle.edge.sessions import resolve_session_id, session_id_after_response
from dle.host.services.receipts import verify_ed25519_signature
from tests.gemini_compat.conftest import COMPAT_ADMIN_KEY, COMPAT_TEST_KEY, _LiveMiddlewareServer


def _make_client(
    base_url: str,
    *,
    api_key: str = COMPAT_TEST_KEY,
    extra_body: dict[str, object] | None = None,
    retry_attempts: int = 1,
) -> genai.Client:
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            base_url=base_url,
            api_version="v1beta",
            extra_body=extra_body,
            retry_options=types.HttpRetryOptions(
                attempts=retry_attempts,
                initial_delay=0.05,
                max_delay=0.1,
            ),
        ),
    )


def test_gc01_list_models_and_pagination(compat_server: _LiveMiddlewareServer) -> None:
    """GC-01: Virtual DLE models and paginated upstream Gemini models list cleanly."""
    with _make_client(compat_server.base_url) as client:
        names = [m.name for m in client.models.list(config=types.ListModelsConfig(page_size=2))]
    assert "models/dle-13axis-strict" in names
    assert "models/dle-13axis-advisory" in names
    assert "models/gemini-4-carbon" in names
    assert "models/gemini-4-neon" in names
    assert "models/gemini-embedding-001" in names


def test_gc02_get_model(compat_server: _LiveMiddlewareServer) -> None:
    """GC-02: Virtual model and upstream Gemini model descriptors resolve."""
    with _make_client(compat_server.base_url) as client:
        strict = client.models.get(model="models/dle-13axis-strict")
        carbon = client.models.get(model="gemini-4-carbon")
    assert strict.name == "models/dle-13axis-strict"
    assert carbon.name == "models/gemini-4-carbon"


def test_gc03_single_turn_text(compat_server: _LiveMiddlewareServer) -> None:
    """GC-03: Single-turn generate_content populates text and finishReason STOP."""
    with _make_client(compat_server.base_url) as client:
        res_pass = client.models.generate_content(
            model="gemini-4-carbon",
            contents="Summarize warehouse substitution rules.",
        )
        res_gov = client.models.generate_content(
            model="dle-13axis-strict",
            contents="Summarize warehouse substitution rules.",
        )

    assert res_pass.text is not None and "gemini-4-carbon" in res_pass.text
    assert res_pass.candidates is not None
    assert res_pass.candidates[0].finish_reason == types.FinishReason.STOP

    assert res_gov.text is not None and len(res_gov.text) > 0
    assert res_gov.candidates is not None
    assert res_gov.candidates[0].finish_reason == types.FinishReason.STOP


def test_gc04_system_instruction_changes_session_hash(
    compat_server: _LiveMiddlewareServer,
) -> None:
    """GC-04: System instruction reaches upstream and alters session hash."""
    with _make_client(compat_server.base_url) as client:
        compat_server.upstream.recorded_requests.clear()
        res_a = client.models.generate_content(
            model="gemini-4-carbon",
            contents="Status check?",
            config=types.GenerateContentConfig(
                system_instruction="Respond concisely in policy terms."
            ),
        )
        res_b = client.models.generate_content(
            model="gemini-4-carbon",
            contents="Status check?",
            config=types.GenerateContentConfig(system_instruction="Respond with JSON summary."),
        )

    assert res_a.text is not None and "[with-system]" in res_a.text
    assert res_b.text is not None and "[with-system]" in res_b.text
    req_a = compat_server.upstream.recorded_requests[-2].payload
    req_b = compat_server.upstream.recorded_requests[-1].payload
    sid_a = resolve_session_id(
        tenant="t1",
        model="gemini-4-carbon",
        system_instruction=req_a.get("systemInstruction"),  # type: ignore[arg-type]
        contents=req_a["contents"],  # type: ignore[arg-type]
    )
    sid_b = resolve_session_id(
        tenant="t1",
        model="gemini-4-carbon",
        system_instruction=req_b.get("systemInstruction"),  # type: ignore[arg-type]
        contents=req_b["contents"],  # type: ignore[arg-type]
    )
    assert sid_a != sid_b


def test_gc05_multi_turn_chat_round_trip(compat_server: _LiveMiddlewareServer) -> None:
    """GC-05: Multi-turn chats.create preserves full history and continuous session hash."""
    with _make_client(compat_server.base_url) as client:
        compat_server.upstream.recorded_requests.clear()
        chat = client.chats.create(model="gemini-4-carbon")
        r1 = chat.send_message("Turn one: check SKU-4429-A.")
        r2 = chat.send_message("Turn two: check lot expiry.")

    assert r1.text is not None and "turn=1" in r1.text
    assert r2.text is not None and "turn=3" in r2.text

    req1 = compat_server.upstream.recorded_requests[-2].payload
    req2 = compat_server.upstream.recorded_requests[-1].payload
    contents1 = req1["contents"]
    contents2 = req2["contents"]
    assert isinstance(contents1, list) and isinstance(contents2, list)
    assert len(contents2) == 3

    expected_next_sid = session_id_after_response(
        tenant="t1",
        model="gemini-4-carbon",
        system_instruction=None,
        contents=contents1,
        response_content=contents2[1],
    )
    actual_turn2_sid = resolve_session_id(
        tenant="t1",
        model="gemini-4-carbon",
        system_instruction=None,
        contents=contents2,
    )
    assert actual_turn2_sid == expected_next_sid


def test_gc06_generation_config_and_json_schema(compat_server: _LiveMiddlewareServer) -> None:
    """GC-06: generationConfig temperature, maxOutputTokens, JSON mime & schema honored."""
    schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "answer": types.Schema(type=types.Type.STRING),
            "confidence": types.Schema(type=types.Type.NUMBER),
        },
        required=["answer", "confidence"],
    )
    with _make_client(compat_server.base_url) as client:
        compat_server.upstream.recorded_requests.clear()
        res = client.models.generate_content(
            model="gemini-4-carbon",
            contents="Return structured decision JSON.",
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=256,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )

    assert res.text is not None
    parsed = json.loads(res.text)
    assert parsed["answer"] == "verified"
    assert isinstance(parsed["confidence"], float)
    forwarded = compat_server.upstream.recorded_requests[-1].payload["generationConfig"]
    assert isinstance(forwarded, dict)
    assert forwarded["temperature"] == pytest.approx(0.1)
    assert forwarded["maxOutputTokens"] == 256
    assert forwarded["responseMimeType"] == "application/json"


def test_gc07_streaming_and_governed_keepalive(compat_server: _LiveMiddlewareServer) -> None:
    """GC-07: generate_content_stream yields usage chunks; governed SSE emits keepalives."""
    with _make_client(compat_server.base_url) as client:
        chunks = list(
            client.models.generate_content_stream(
                model="gemini-4-carbon",
                contents="Stream pass-through chunks cleanly.",
            )
        )
    assert len(chunks) >= 2
    assert any(c.text for c in chunks)
    assert chunks[-1].usage_metadata is not None
    assert chunks[-1].usage_metadata.total_token_count is not None

    # Exercise governed SSE keepalive frames with slow upstream inside live server.
    prev_delay = compat_server.upstream.delay_s
    compat_server.upstream.delay_s = 0.5
    try:
        with httpx.Client() as raw_http:
            raw_res = raw_http.post(
                f"{compat_server.base_url}/v1beta/models/dle-13axis-strict:streamGenerateContent",
                params={"alt": "sse"},
                headers={"x-goog-api-key": COMPAT_TEST_KEY},
                json={"contents": [{"role": "user", "parts": [{"text": "Keepalive test."}]}]},
            )
        assert raw_res.status_code == 200
        assert raw_res.text.startswith("\n\n")
        assert "\n\ndata: " in raw_res.text

        with _make_client(compat_server.base_url) as client:
            gov_chunks = list(
                client.models.generate_content_stream(
                    model="dle-13axis-strict",
                    contents="Keepalive SDK stream verification.",
                )
            )
        assert len(gov_chunks) >= 1
        assert any(c.text for c in gov_chunks)
    finally:
        compat_server.upstream.delay_s = prev_delay


def test_gc08_count_tokens(compat_server: _LiveMiddlewareServer) -> None:
    """GC-08: count_tokens returns exact token count from upstream."""
    with _make_client(compat_server.base_url) as client:
        counted = client.models.count_tokens(
            model="gemini-4-carbon",
            contents="Count tokens for this policy prompt.",
        )
    assert counted.total_tokens is not None and counted.total_tokens > 0


def test_gc09_auth_header_query_key_and_401(compat_server: _LiveMiddlewareServer) -> None:
    """GC-09: Header & ?key= query param succeed; wrong key raises 401 ClientError."""
    with httpx.Client() as raw_http:
        ok_query = raw_http.get(
            f"{compat_server.base_url}/v1beta/models/gemini-4-carbon",
            params={"key": COMPAT_TEST_KEY},
        )
        assert ok_query.status_code == 200

    with (
        _make_client(compat_server.base_url, api_key="invalid-" + "key-01") as bad_client,
        pytest.raises(errors.ClientError) as exc_info,
    ):
        bad_client.models.generate_content(
            model="gemini-4-carbon",
            contents="Should fail auth.",
        )
    assert exc_info.value.code == 401
    assert exc_info.value.status == "UNAUTHENTICATED"


def test_gc10_invalid_request_400(compat_server: _LiveMiddlewareServer) -> None:
    """GC-10: Invalid request yields 400 INVALID_ARGUMENT ClientError."""
    with httpx.Client() as raw_http:
        bad_res = raw_http.post(
            f"{compat_server.base_url}/v1beta/models/gemini-4-carbon:generateContent",
            headers={"x-goog-api-key": COMPAT_TEST_KEY},
            json={"contents": []},
        )
    assert bad_res.status_code == 400
    assert bad_res.json()["error"]["status"] == "INVALID_ARGUMENT"

    with (
        _make_client(compat_server.base_url) as client,
        pytest.raises(errors.ClientError) as exc_info,
    ):
        client.models.generate_content(
            model="gemini-4-carbon",
            contents="TRIGGER_400 upstream validation check",
        )
    assert exc_info.value.code == 400


def test_gc11_rate_limit_429_retry(compat_server: _LiveMiddlewareServer) -> None:
    """GC-11: 429 RESOURCE_EXHAUSTED preserves SDK retry behavior and exception type."""
    compat_server.upstream.recorded_requests.clear()
    with (
        _make_client(compat_server.base_url, retry_attempts=2) as client,
        pytest.raises(errors.ClientError) as exc_info,
    ):
        client.models.generate_content(
            model="gemini-4-carbon",
            contents="TRIGGER_429 rate limit check",
        )
    assert exc_info.value.code == 429
    assert exc_info.value.status == "RESOURCE_EXHAUSTED"
    assert len(compat_server.upstream.recorded_requests) >= 2


def test_gc12_governed_grounding_metadata_parse(compat_server: _LiveMiddlewareServer) -> None:
    """GC-12: Governed released response exposes GroundingMetadata and signed 3.8.0 receipt."""
    clause = (
        "Container lot C-42 requires dual pressure relief valves "
        "certified under ISO 9001 before hazardous transit."
    )
    with httpx.Client() as raw_http:
        reset = raw_http.post(
            f"{compat_server.base_url}/admin/drift/reset",
            headers={"X-DLE-Admin-Key": COMPAT_ADMIN_KEY},
            json={"calibrationArtifactId": "cal-phase6-v1", "confirm": "RESET"},
        )
        assert reset.status_code == 204
        reg = raw_http.post(
            f"{compat_server.base_url}/admin/sources",
            headers={"X-DLE-Admin-Key": COMPAT_ADMIN_KEY},
            json={
                "title": "Hazardous Container Transit Spec",
                "authorityClass": "primary_text",
                "content": {
                    "mimeType": "text/plain",
                    "data": base64.b64encode(clause.encode("utf-8")).decode("ascii"),
                },
            },
        )
        assert reg.status_code == 201

    with _make_client(compat_server.base_url) as client:
        res = client.models.generate_content(
            model="dle-13axis-strict",
            contents=clause,
        )
    assert res.candidates is not None and len(res.candidates) >= 1
    cand = res.candidates[0]
    assert cand.finish_reason == types.FinishReason.STOP
    assert cand.grounding_metadata is not None
    assert cand.grounding_metadata.grounding_chunks
    assert cand.grounding_metadata.grounding_supports

    with httpx.Client() as raw_http:
        rest_res = raw_http.post(
            f"{compat_server.base_url}/v1beta/models/dle-13axis-strict:generateContent",
            headers={"x-goog-api-key": COMPAT_TEST_KEY},
            json={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
        )
        assert rest_res.status_code == 200
        assert rest_res.headers["X-DLE-Release-Mode"] == "released"
        rcpt_id = rest_res.headers["X-DLE-Receipt"]
        rcpt_res = raw_http.get(
            f"{compat_server.base_url}/v1/receipts/{rcpt_id}",
            headers={"x-goog-api-key": COMPAT_TEST_KEY},
        )
        assert rcpt_res.status_code == 200
        rcpt_json = rcpt_res.json()
        assert rcpt_json["payload"]["schema_version"] == "3.8.0"

        exp_res = raw_http.post(
            f"{compat_server.base_url}/admin/receipts/export",
            headers={"X-DLE-Admin-Key": COMPAT_ADMIN_KEY},
            json={"from": "2020-01-01T00:00:00Z", "to": "2035-01-01T00:00:00Z"},
        )
        assert exp_res.status_code == 200
        with zipfile.ZipFile(BytesIO(exp_res.content)) as zf:
            pub_keys = json.loads(zf.read("public_keys.json"))
            env = rcpt_json["envelope"]
            assert verify_ed25519_signature(
                canonical_payload_bytes=canonicalize_jcs(rcpt_json["payload"]),
                signature_b64=env["signature_b64"],
                public_key_b64=pub_keys[env["key_id"]],
            )


def test_gc13_governed_held_answer_stop_and_headers(compat_server: _LiveMiddlewareServer) -> None:
    """GC-13: Governed hold returns 200 STOP notice text, held header, and signed hold receipt."""
    ungrounded_claim = (
        "Unverified orbital cargo schedules guarantee instantaneous transoceanic delivery."
    )
    with _make_client(compat_server.base_url) as client:
        res = client.models.generate_content(
            model="dle-13axis-strict",
            contents=ungrounded_claim,
        )
    assert res.candidates is not None and len(res.candidates) >= 1
    assert res.candidates[0].finish_reason == types.FinishReason.STOP
    assert res.text is not None and len(res.text.strip()) > 0

    with httpx.Client() as raw_http:
        rest_res = raw_http.post(
            f"{compat_server.base_url}/v1beta/models/dle-13axis-strict:generateContent",
            headers={"x-goog-api-key": COMPAT_TEST_KEY},
            json={"contents": [{"role": "user", "parts": [{"text": ungrounded_claim}]}]},
        )
        assert rest_res.status_code == 200
        assert rest_res.headers["X-DLE-Release-Mode"] == "held"
        rcpt_id = rest_res.headers["X-DLE-Receipt"]
        assert len(rcpt_id) == 36
        rcpt_res = raw_http.get(
            f"{compat_server.base_url}/v1/receipts/{rcpt_id}",
            headers={"x-goog-api-key": COMPAT_TEST_KEY},
        )
        assert rcpt_res.status_code == 200
        assert rcpt_res.json()["payload"]["decision"]["release_mode"] in {
            "hard_veto_block",
            "abstained",
        }


def test_gc14_function_calling_single(compat_server: _LiveMiddlewareServer) -> None:
    """GC-14: Single functionCall returned unchanged and functionResponse accepted."""
    decl = types.FunctionDeclaration(
        name="lookup_lot",
        description="Look up warehouse lot status.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={"city": types.Schema(type=types.Type.STRING)},
        ),
    )
    cfg = types.GenerateContentConfig(tools=[types.Tool(function_declarations=[decl])])
    with _make_client(compat_server.base_url) as client:
        turn1 = client.models.generate_content(
            model="gemini-4-carbon",
            contents="Check Austin lot status.",
            config=cfg,
        )
        assert turn1.function_calls is not None and len(turn1.function_calls) == 1
        fc = turn1.function_calls[0]
        assert fc.name == "lookup_lot"

        assert turn1.candidates is not None and turn1.candidates[0].content is not None
        turn2 = client.models.generate_content(
            model="gemini-4-carbon",
            contents=[
                types.Content(role="user", parts=[types.Part.from_text(text="Check Austin.")]),
                turn1.candidates[0].content,
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name="lookup_lot",
                            response={"status": "approved", "lot": "L-99"},
                        )
                    ],
                ),
            ],
            config=cfg,
        )
    assert turn2.text is not None and "L-99" in turn2.text


def test_gc15_parallel_function_calls(compat_server: _LiveMiddlewareServer) -> None:
    """GC-15: Parallel functionCall parts preserve exact order and IDs."""
    t1 = types.FunctionDeclaration(name="get_weather", description="Weather")
    t2 = types.FunctionDeclaration(name="get_time", description="Time")
    cfg = types.GenerateContentConfig(tools=[types.Tool(function_declarations=[t1, t2])])
    with _make_client(compat_server.base_url) as client:
        res = client.models.generate_content(
            model="gemini-4-carbon",
            contents="Run parallel weather and time checks.",
            config=cfg,
        )
    assert res.function_calls is not None and len(res.function_calls) == 2
    assert [c.name for c in res.function_calls] == ["get_weather", "get_time"]
    assert [c.id for c in res.function_calls] == ["call-parallel-1", "call-parallel-2"]


def test_gc16_automatic_function_calling(compat_server: _LiveMiddlewareServer) -> None:
    """GC-16: Python SDK automatic function calling completes full loop via middleware."""
    invoked: list[str] = []

    def get_weather(city: str) -> dict[str, str]:
        """Get forecast for a city."""
        invoked.append(city)
        return {"city": city, "forecast": "clear"}

    with _make_client(compat_server.base_url) as client:
        res = client.models.generate_content(
            model="gemini-4-carbon",
            contents="What is the weather in Austin?",
            config=types.GenerateContentConfig(tools=[get_weather]),
        )
    assert invoked == ["Austin"]
    assert res.text is not None and "clear" in res.text


def test_gc17_tool_config_modes(compat_server: _LiveMiddlewareServer) -> None:
    """GC-17: ToolConfig modes AUTO, ANY, and NONE pass through and behave consistently."""
    decl = types.FunctionDeclaration(name="get_status", description="Status lookup")
    tool = types.Tool(function_declarations=[decl])
    with _make_client(compat_server.base_url) as client:
        compat_server.upstream.recorded_requests.clear()
        for mode in (
            types.FunctionCallingConfigMode.AUTO,
            types.FunctionCallingConfigMode.ANY,
            types.FunctionCallingConfigMode.NONE,
        ):
            res = client.models.generate_content(
                model="gemini-4-carbon",
                contents=f"Run check in {mode.name} mode.",
                config=types.GenerateContentConfig(
                    tools=[tool],
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode=mode)
                    ),
                ),
            )
            if mode == types.FunctionCallingConfigMode.NONE:
                assert not res.function_calls
                assert res.text is not None
            else:
                assert res.function_calls and res.function_calls[0].name == "get_status"


def test_gc18_function_call_with_id_round_trip(compat_server: _LiveMiddlewareServer) -> None:
    """GC-18: FunctionCall and FunctionResponse id round-trips cleanly."""
    with httpx.Client() as raw_http:
        r2 = raw_http.post(
            f"{compat_server.base_url}/v1beta/models/gemini-4-carbon:generateContent",
            headers={"x-goog-api-key": COMPAT_TEST_KEY},
            json={
                "tools": [{"functionDeclarations": [{"name": "verify_lot"}]}],
                "contents": [
                    {"role": "user", "parts": [{"text": "Verify lot"}]},
                    {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {
                                    "id": "call-id-777",
                                    "name": "verify_lot",
                                    "args": {},
                                }
                            }
                        ],
                    },
                    {
                        "role": "function",
                        "parts": [
                            {
                                "functionResponse": {
                                    "id": "call-id-777",
                                    "name": "verify_lot",
                                    "response": {"ok": True},
                                }
                            }
                        ],
                    },
                ],
            },
        )
    assert r2.status_code == 200
    text = r2.json()["candidates"][0]["content"]["parts"][0]["text"]
    assert "call-id-777" in text


def test_gc19_inline_image_input(compat_server: _LiveMiddlewareServer) -> None:
    """GC-19: inlineData image bytes pass cleanly to upstream."""
    png_1x1 = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    with _make_client(compat_server.base_url) as client:
        res = client.models.generate_content(
            model="gemini-4-carbon",
            contents=[
                types.Part.from_text(text="Inspect label"),
                types.Part.from_bytes(data=png_1x1, mime_type="image/png"),
            ],
        )
    assert res.text is not None and "image/png" in res.text


def test_gc20_google_search_tool(compat_server: _LiveMiddlewareServer) -> None:
    """GC-20: Google Search groundingMetadata chunks & supports pass through."""
    with _make_client(compat_server.base_url) as client:
        res = client.models.generate_content(
            model="gemini-4-carbon",
            contents="Search policy spec.",
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
    assert res.candidates is not None
    gm = res.candidates[0].grounding_metadata
    assert gm is not None
    assert gm.grounding_chunks is not None and len(gm.grounding_chunks) == 1
    assert gm.grounding_supports is not None and len(gm.grounding_supports) == 1


def test_gc21_url_context_tool(compat_server: _LiveMiddlewareServer) -> None:
    """GC-21: URL context tool passes through and preserves urlContextMetadata."""
    with _make_client(compat_server.base_url) as client:
        res = client.models.generate_content(
            model="gemini-4-carbon",
            contents="Summarize https://example.org/doc",
            config=types.GenerateContentConfig(tools=[types.Tool(url_context=types.UrlContext())]),
        )
    assert res.text is not None and "URL context" in res.text


def test_gc22_code_execution_tool(compat_server: _LiveMiddlewareServer) -> None:
    """GC-22: executableCode and codeExecutionResult parts pass through."""
    with _make_client(compat_server.base_url) as client:
        res = client.models.generate_content(
            model="gemini-4-carbon",
            contents="Compute 6 * 7 in Python.",
            config=types.GenerateContentConfig(
                tools=[types.Tool(code_execution=types.ToolCodeExecution())]
            ),
        )
    assert res.candidates is not None and res.candidates[0].content is not None
    parts = res.candidates[0].content.parts
    assert parts is not None
    assert any(p.executable_code is not None for p in parts)
    assert any(p.code_execution_result is not None for p in parts)


def test_gc23_thinking_config(compat_server: _LiveMiddlewareServer) -> None:
    """GC-23: thinkingConfig forwards cleanly; thought parts preserved on pass-through."""
    with _make_client(compat_server.base_url) as client:
        res = client.models.generate_content(
            model="gemini-4-carbon",
            contents="Explain constraint step-by-step.",
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_budget=256,
                )
            ),
        )
    assert res.candidates is not None and res.candidates[0].content is not None
    parts = res.candidates[0].content.parts
    assert parts is not None and any(getattr(p, "thought", False) for p in parts)


def test_gc24_large_context(compat_server: _LiveMiddlewareServer) -> None:
    """GC-24: 500k-token payload passes within limits cleanly."""
    large_text = "warehouse policy rule verification " * 45_000
    with _make_client(compat_server.base_url) as client:
        res = client.models.generate_content(
            model="gemini-4-carbon",
            contents=large_text,
        )
    assert res.usage_metadata is not None
    assert (res.usage_metadata.prompt_token_count or 0) >= 500_000


def test_gc25_governed_stream_cancellation_records_receipt(
    compat_server: _LiveMiddlewareServer,
) -> None:
    """GC-25: Aborting a governed SSE stream mid-flight records a 'cancelled' receipt."""
    compat_server.upstream.delay_s = 1.2
    try:
        with (
            httpx.Client() as raw_http,
            raw_http.stream(
                "POST",
                f"{compat_server.base_url}/v1beta/models/dle-13axis-strict:streamGenerateContent",
                params={"alt": "sse"},
                headers={"x-goog-api-key": COMPAT_TEST_KEY},
                json={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": "Slow governed stream cancellation probe."}],
                        }
                    ]
                },
            ) as resp,
        ):
            assert resp.status_code == 200
            first_bytes = next(resp.iter_bytes())
            assert first_bytes == b"\n\n"
    finally:
        compat_server.upstream.delay_s = 0.0

    deadline = time.monotonic() + 2.0
    cancelled_rows: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        rows = compat_server.app.state.dle.receipt_repo.list_receipts_between(
            "2020-01-01T00:00:00Z",
            "2035-01-01T00:00:00Z",
        )
        cancelled_rows = [row for row in rows if row.get("release_mode") == "cancelled"]
        if cancelled_rows:
            break
        time.sleep(0.05)

    assert len(cancelled_rows) >= 1


def test_gc26_unknown_future_fields_and_rest_headers(
    compat_server: _LiveMiddlewareServer,
) -> None:
    """GC-26: Unknown request & response fields survive untouched; X-DLE headers present."""
    with _make_client(
        compat_server.base_url,
        extra_body={"futureExperimentalFlag": {"nested": "value-42"}},
    ) as client:
        compat_server.upstream.recorded_requests.clear()
        client.models.generate_content(
            model="gemini-4-carbon",
            contents="Future field test.",
        )
    forwarded = compat_server.upstream.recorded_requests[-1].payload
    assert forwarded["futureExperimentalFlag"] == {"nested": "value-42"}

    # Raw REST spot-check per route verifying X-DLE-API-Version & untouched response extension.
    with httpx.Client() as raw_http:
        r_models = raw_http.get(
            f"{compat_server.base_url}/v1beta/models",
            headers={"x-goog-api-key": COMPAT_TEST_KEY},
        )
        r_gen = raw_http.post(
            f"{compat_server.base_url}/v1beta/models/gemini-4-carbon:generateContent",
            headers={"x-goog-api-key": COMPAT_TEST_KEY},
            json={
                "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
                "futureExperimentalFlag": "raw-flag",
            },
        )
        r_cnt = raw_http.post(
            f"{compat_server.base_url}/v1beta/models/gemini-4-carbon:countTokens",
            headers={"x-goog-api-key": COMPAT_TEST_KEY},
            json={"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]},
        )

    assert r_models.headers["X-DLE-API-Version"] == "1.0"
    assert r_gen.headers["X-DLE-Release-Mode"] == "passthrough"
    assert r_gen.headers["X-DLE-API-Version"] == "1.0"
    assert r_gen.json()["futureResponseExtension"] == {"echoedFlag": "raw-flag"}
    assert r_cnt.headers["X-DLE-API-Version"] == "1.0"
