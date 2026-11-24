# Pre-Registered Evaluation Study Report (`O3`, `DLE-EVL-003`)

- **Study Date:** 2026-11-24
- **Protocol Commit:** `f09d6eb`
- **Execution Mode:** `offline_deterministic_ci_stub` (in-process `FakeModel` + `DeterministicLexicalNliScorer`; the live cloud Gemini study remains an operational milestone)
- **Sealed Held-Out Registry SHA-256:** `d4fb38bf1cb359f6b7396316148030b665f2ea6c8e71a2a54087d64b7c1b09a5` (`150` eval + `100` challenge verified)
- **Policy Digest:** `ac5795382c582655346083f88168a4be4cdfd63b01963d7e9aa67fec5d887692`
- **Calibration Artifact:** `cal-phase6-v1` (alpha=0.05, threshold=0.29, mu_0=0.275692, lambda=3.3624)

## 1. Hypotheses & Pre-Registered Endpoints Summary

| ID | Target / Comparison | Observed Result | 95% Bound / CI | Status |
| --- | --- | --- | --- | --- |
| H1 · Addressing | `strict` vs `unaddressed` (n=150) | loss diff `0.0`, cov diff `0.0` | loss CI `[0.0, 0.0]` | `no_directional_difference` |
| H2 · Roles | `strict` vs `single_reviewer` (n=150) | loss diff `0.0`, cost diff USD `0.001676` | loss CI `[0.0, 0.0]` | `no_directional_difference` |
| H3 · Gate | `strict` on held-out test (n=150) | accepted loss sum `0.0` (`0` err), cov `0.42` | 1-sided 95% upper `0.019773` | `supported` |
| H4 · Routing | Tier-3 recall on challenge (n=100) | `40/100` (`recall=0.4`, `60` misses) | 1-sided 95% lower `0.317526` | `below_threshold` |
| M1 · Extractor | 200 labeled drafts (`266` claims) | claim recall `1.0`, binding `1.0` | 1-sided 95% lower `0.988801` | `supported` |
| M2 · Catalog | `kernel_plus_policy` vs `kernel_only` (n=150) | loss diff `0.0`, cov diff `0.0` | loss CI `[0.0, 0.0]` | `no_directional_difference` |

## 2. Study Arms & Verify-and-Gate Baseline (150 Held-Out Test Queries)

| Arm | Accepted / N | Coverage | Accepted Loss Sum | 95% Upper Bound | Mean Rubric Loss | Over-Abstention |
| --- | --- | --- | --- | --- | --- | --- |
| `strict` | 63/150 | 0.42 | 0.0 | 0.019773 | 0.36 | 0.461538 |
| `unaddressed` | 63/150 | 0.42 | 0.0 | 0.019773 | 0.36 | 0.461538 |
| `single_reviewer` | 63/150 | 0.42 | 0.0 | 0.019773 | 0.36 | 0.461538 |
| `kernel_only` | 63/150 | 0.42 | 0.0 | 0.019773 | 0.36 | 0.461538 |
| `kernel_plus_policy` | 63/150 | 0.42 | 0.0 | 0.019773 | 0.36 | 0.461538 |
| `verify_and_gate_baseline` | 63/150 | 0.42 | 0.0 | 0.019773 | 0.36 | 0.461538 |

## 3. Additional Diagnostics (`study_protocol.md`)

- **Blind Grader Agreement (`strict` arm):** Cohen's kappa = 0.930284
- **Strict Hold & Release Notices:** `{"NOTICE-HOLD-02": 19, "NOTICE-HOLD-03": 60, "NOTICE-HOLD-04": 8, "NOTICE-REL-01": 63}`
- **H4 Challenge Router Confusion Matrix:** `{"expected_tier_3_routed_tier_1": 20, "expected_tier_3_routed_tier_2": 40, "expected_tier_3_routed_tier_3": 40}`
- **Per-Tier Cost & Latency (`strict`):** `{"tier_2": {"count": 112, "mean_cost_usd": 0.003177, "mean_duration_ms": 47.989}, "tier_3": {"count": 38, "mean_cost_usd": 0.004091, "mean_duration_ms": 46.346}}`
- **Kernel / Policy Invocation Counts (`kernel_plus_policy`):** `{"DVSS-K01:ok": 150, "DVSS-K02:ok": 150, "DVSS-K03:ok": 150, "DVSS-K04:hold": 79, "DVSS-K04:ok": 71, "DVSS-K05:ok": 150, "DVSS-K06:ok": 150, "DVSS-K07:ok": 150, "DVSS-K08:ok": 150, "DVSS-K09:ok": 150, "DVSS-K10:ok": 150, "DVSS-K11:hold": 87, "DVSS-K11:ok": 63, "DVSS-K12:ok": 150, "DVSS-P01:skipped": 150, "DVSS-P02:skipped": 150, "DVSS-P03:skipped": 150, "DVSS-P06:skipped": 150, "DVSS-P07:ok": 150, "DVSS-P08:ok": 150, "DVSS-P09:skipped": 150, "DVSS-P10:skipped": 150, "DVSS-P11:skipped": 150}`

## 4. Deviations & Scientific Disclosure

- Executed deterministically offline against `FakeModel` + `DeterministicLexicalNliScorer`. Stub role packets are uniform, so arm differences reflect pipeline structure (addressing, gate, catalog) rather than model reasoning quality. These results validate the harness and statistics; they are not evidence about live Gemini behaviour.
- Blind dual-grader disagreement is simulated deterministically (seeded), so kappa measures the simulation, not human graders.
