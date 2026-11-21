# Operations runbook and AI incident response plan (G25)

**Document ID:** DLE-OPS-001 · **Version:** 0.1.0 · **Status:** Draft · **Owner:** Release manager · **Date:** 2026-11-20

## 1. Severity

| Sev | Definition | Response target |
| --- | --- | --- |
| 1 | An unsupported or unauthorized answer was released, a receipt can be forged, or data left by an unapproved path | Start within 1 h; stop releases (switch to strict-hold) |
| 2 | A step, role or layer skipped; Gemini compatibility broken; drift unmonitored | Start within 4 h |
| 3 | Degraded latency or cost; noisy holds | Next business day |

Incident IDs: `INC-<yyyy>-<nnn>`. Every incident gets a timeline, impact, root cause, fix and follow-up tickets, written up within 5 working days (blameless format).

## 2. Playbooks

### PB-01 · Drift latch tripped
1. Confirm in `/healthz` and `ops.db.drift_state` (latch reason).
2. Check for a `modelVersion` change, registry release or source-policy change in the last 7 days.
3. If none: sample 20 recent held and released runs for human review.
4. Recalibrate on fresh graded data (O1); load the artifact; reset with `/admin/drift/reset` (two-step, logged).

### PB-02 · Model version changed
Calibration latches automatically. Run the fixture suite against the new version; if it passes, recalibrate; if not, pin the previous version if Google still serves it, or stay in hold and escalate.

### PB-03 · Gemini outage or throttling
Answers hold with NOTICE-HOLD-06; nothing to release. Watch error rate; if over 1 h, notify client app owners. Do not switch models without a calibration plan.

### PB-04 · Suspected prompt injection
Symptoms: role outputs off-mandate, odd objections, unusual tool calls. Pull the receipts; identify the passage or function response carrying the payload; quarantine the source (retire it); add the pattern to P13 and the injection test set; re-run affected sessions.

### PB-05 · Confabulated answer reached a user
Sev 1. Find the receipt; check which check should have caught it (extractor recall, NLI, authority check, gate). Add the case as a fixture. Notify the client owner with the receipt. If systematic, switch affected profiles to strict-hold until fixed.

### PB-06 · Context or data leak
Sev 1. Identify what left and to where from `egress_log`; revoke keys involved; confirm no logging of content; notify per contract. Fix and add a test.

### PB-07 · Signing key compromise
Revoke the key in `signing_keys` with the compromise time; rotate; receipts signed after the compromise and not anchored earlier are treated as unverified (paper §16d); notify verifiers.

## 3. Routine checks (weekly)

Hold, advisory and release rates by tier; p95 latency per step; cost per tier against budget; drift `C_t` trend; failed authority checks by source; egress log shows only allowed hosts.
