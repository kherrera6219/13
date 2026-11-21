# Security policy

## Reporting a vulnerability

Email **security@lucentry.example** (replace with the monitored address before publication) with a description, affected version, reproduction steps and impact. Please do not open public issues for security reports. Encrypt with our PGP key if available.

We follow coordinated vulnerability disclosure (ISO/IEC 29147 and 30111):

| Step | Target |
| --- | --- |
| Acknowledge receipt | 2 working days |
| Triage and severity | 5 working days |
| Fix: critical / high | 30 days |
| Fix: medium / low | 90 days / next release |
| Public advisory | With the fix, crediting the reporter unless they prefer otherwise |

## Supported versions

| Version | Security fixes |
| --- | --- |
| Latest minor of the current major | Yes |
| Previous major | 12 months after the next major's release |

## Scope

In scope: the middleware service, its API, receipts, installer and container image. Out of scope: Google's Gemini API, client applications, and deployments that disable documented hardening (see `docs/guides/admin_and_hardening_guide.md`).

## Safe harbor

Good-faith research that avoids privacy violations, data destruction and service disruption, and gives us reasonable time to fix, will not be pursued legally.
