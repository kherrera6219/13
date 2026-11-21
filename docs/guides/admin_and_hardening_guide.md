# Administrator and hardening guide (G22)

**Document ID:** DLE-GDE-002 · **Version:** 0.1.0 · **Status:** Draft · **Audience:** administrators (persona P4, journey J4)

## 1. Install

| Item | Requirement |
| --- | --- |
| OS | Windows 11, Windows Server 2022, or Linux (x86-64) |
| Runtime | Python 3.12 (bundled in the installer or container image, per decision D1) |
| CPU / RAM / disk | 4 cores, 16 GB RAM, 20 GB free (NLI model, stores, receipts) |
| Network | Outbound HTTPS to `generativelanguage.googleapis.com:443` only |

Run the service under a dedicated, non-admin service account. Data directory: `C:\ProgramData\DLE` or `/var/lib/dle`, ACL limited to that account.

## 2. First-run configuration

1. Store the Gemini API key: `dle admin set-secret gemini_api_key` (Windows DPAPI machine scope, or the Linux keyring / file with mode 0600).
2. Create client keys: `dle admin create-client-key --name <app>`; give each app its own key.
3. Generate the signing key: `dle admin rotate-key` (Ed25519). Publish the public key to whoever verifies receipts.
4. Choose the anchoring profile in `config/receipts.yaml`: `local_worm_merkle` (default), `customer_hosted_log`, or `external_transparency_log` (adds a second allowed egress host).
5. Register sources: `POST /admin/sources` or the admin UI. Set each source's authority class honestly; it drives the score.
6. Load the calibration artifact for the shipped model pin. Until one is loaded, strict mode holds everything.

## 3. Hardening checklist

- [ ] Bind stays `127.0.0.1`. For LAN access set `allow_lan: true`, enable TLS with your certificate, and firewall to known clients.
- [ ] Host firewall: deny all outbound except the Gemini host (and the transparency log, if used).
- [ ] Service account has no admin rights and no interactive logon.
- [ ] Data directory ACL: service account full control; administrators read; no others.
- [ ] Debug content capture (`log_content: true`) is off.
- [ ] Session expiry set (default 24 h); receipt retention set to your records policy (default 7 years).
- [ ] Backups of `registry.db`, `receipts.db` and `keys/` scheduled to a protected location; restore tested.
- [ ] Health check `GET /healthz` monitored; alerts wired (§5).
- [ ] Function flags: consequential functions listed in `config/function_flags.yaml`.

## 4. Routine operations

| Task | How | When |
| --- | --- | --- |
| Rotate signing key | `POST /admin/keys/rotate` | Yearly or on suspicion |
| Rotate client keys | `dle admin create-client-key`, then revoke old | On staff or app change |
| Registry release | `offline/registry_release` → review → activate | On content change |
| Recalibrate | Run O1 on fresh graded data; load artifact; reset latch | After a model or registry change, or a drift alarm |
| Export receipts | `POST /admin/receipts/export` | On audit request |
| Update | Install signed release; check SBOM and changelog | Each release |

## 5. Alerts and what to do

| Alert | Meaning | First action |
| --- | --- | --- |
| Drift latch tripped | Score distribution moved; strict mode now holds | Check `modelVersion` changes and hold rate; see runbook PB-01 |
| `modelVersion` changed | Google updated the model | Calibration latched; recalibrate (PB-02) |
| Gemini error rate > 5% | Upstream trouble | Answers hold automatically; check Google status (PB-03) |
| Hold rate 2× baseline | Sources missing or drift | Check source registration and recent registry releases |

## 6. Uninstall

Stop the service; export receipts if needed; delete the data directory (stores, keys, logs); remove the service account; remove firewall rules. Keys deleted here make past receipts unverifiable unless the public keys were published.
