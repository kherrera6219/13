# Third-party license inventory (G26)

**Document ID:** DLE-LGL-001 · **Version:** 0.1.0 · **Status:** Draft · **Date:** 2026-11-20

Licenses below are as commonly published for each project and must be confirmed from the SBOM (`cyclonedx-py`) and each package's own metadata at every release. The CI license check fails on any copyleft license in a runtime dependency unless approved here.

| Component | Use | License (to confirm) | Obligation |
| --- | --- | --- | --- |
| FastAPI, Starlette | Web framework | MIT / BSD-3-Clause | Keep notices |
| Uvicorn | ASGI server | BSD-3-Clause | Keep notices |
| sse-starlette | SSE | BSD-3-Clause | Keep notices |
| Pydantic | Models | MIT | Keep notices |
| httpx | HTTP client | BSD-3-Clause | Keep notices |
| google-genai | Gemini SDK | Apache-2.0 | Keep notices; NOTICE file |
| jsonschema | Validation | MIT | Keep notices |
| rfc8785 | JCS | Apache-2.0 | Keep notices |
| cryptography | Ed25519 | Apache-2.0 or BSD-3-Clause | Keep notices |
| NumPy, SciPy | PPR math | BSD-3-Clause | Keep notices |
| ONNX Runtime | NLI inference | MIT | Keep notices |
| NLI model weights (DeBERTa-v3 class) | Entailment | Check the specific checkpoint's license | Record checkpoint and license before pinning |
| sqlite-vec | Vector search | Apache-2.0 / MIT | Keep notices |
| SQLite | Storage | Public domain | None |
| structlog | Logging | Apache-2.0 / MIT | Keep notices |
| PyYAML | Config | MIT | Keep notices |
| React, Vite | Chat UI | MIT | Keep notices |
| @google/genai | UI SDK | Apache-2.0 | Keep notices |
| Storybook | UI catalog (dev only) | MIT | None at runtime |

**Services.** Use of the Gemini API is governed by Google's API terms; confirm data-use terms for the paid tier before handling customer data, and record the review date here.
