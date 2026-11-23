"""Offline receipt and export-bundle verifier CLI (`H15`, FR-RCPT-02, US-09).

Usage:
    python -m dle.tools.verify_receipt <receipt.json|bundle.zip> [--public-key-b64 <b64>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import jsonschema

from dle.config.loader import canonicalize_jcs
from dle.host.services.receipts import verify_ed25519_signature, verify_merkle_proof
from dle.observability import sha256_text

_DEFAULT_RECEIPT_SCHEMA = Path(__file__).resolve().parents[2] / "contracts" / "receipt.schema.json"
_HOLD_ALLOWED = frozenset({"DVSS-K04", "DVSS-K11", "DVSS-K12"})


def verify_signed_receipt(
    receipt: Mapping[str, object],
    *,
    public_key_b64: str,
    expected_response_text: str | None = None,
    merkle_proof: Sequence[Mapping[str, str]] | None = None,
    schema_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """Verify schema 3.8.0, RFC 8785 JCS hash, Ed25519 signature, holds, and Merkle proof."""
    errors: list[str] = []
    target_schema = schema_path or _DEFAULT_RECEIPT_SCHEMA
    schema = json.loads(target_schema.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    for err in sorted(validator.iter_errors(receipt), key=lambda e: list(e.absolute_path)):
        ptr = "/" + "/".join(str(p) for p in err.absolute_path)
        errors.append(f"schema error at {ptr}: {err.message}")
    if errors:
        return False, errors

    payload = receipt["payload"]
    envelope = receipt["envelope"]
    if not isinstance(payload, Mapping) or not isinstance(envelope, Mapping):
        return False, ["receipt must contain object 'payload' and 'envelope'"]

    jcs_bytes = canonicalize_jcs(payload)
    actual_digest = hashlib.sha256(jcs_bytes).hexdigest()
    expected_digest = str(envelope["digest_sha256"])
    if actual_digest != expected_digest:
        errors.append(
            f"JCS digest mismatch: computed {actual_digest}, envelope recorded {expected_digest}"
        )

    if not verify_ed25519_signature(
        canonical_payload_bytes=jcs_bytes,
        signature_b64=str(envelope["signature_b64"]),
        public_key_b64=public_key_b64,
    ):
        errors.append("Ed25519 signature verification failed")

    fn_invocations = payload.get("function_invocations", [])
    if isinstance(fn_invocations, list):
        for idx, rec in enumerate(fn_invocations):
            if (
                isinstance(rec, Mapping)
                and rec.get("outcome") == "hold"
                and str(rec.get("dvss_id")) not in _HOLD_ALLOWED
            ):
                errors.append(
                    f"illegal hold outcome in function_invocations[{idx}] for {rec.get('dvss_id')}"
                )

    if expected_response_text is not None:
        resp_sha = sha256_text(expected_response_text)
        if resp_sha != str(payload["response_sha256"]):
            errors.append(
                f"response_sha256 mismatch: expected {payload['response_sha256']}, got {resp_sha}"
            )

    if merkle_proof is not None:
        root_sha = str(envelope["verified_checkpoint_sha256"])
        if not verify_merkle_proof(expected_digest, merkle_proof, root_sha):
            errors.append(f"Merkle inclusion proof failed against root {root_sha}")

    return len(errors) == 0, errors


def verify_bundle_zip(
    zip_path: Path,
    *,
    schema_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """Verify every receipt, Ed25519 signature, chain link, and Merkle proof in a ZIP export."""
    all_errors: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        public_keys = json.loads(zf.read("public_keys.json"))
        prev_by_chain: dict[str, str] = {}

        for item in manifest.get("receipts", []):
            rid = str(item["receipt_id"])
            kid = str(item["key_id"])
            chain_id = str(item["chain_id"])
            receipt = json.loads(zf.read(f"receipts/{rid}.json"))
            proof = json.loads(zf.read(f"proofs/{rid}.proof.json"))
            pub_b64 = public_keys.get(kid)
            if not isinstance(pub_b64, str) or not pub_b64:
                all_errors.append(f"receipt {rid}: missing public key {kid!r}")
                continue
            ok, errs = verify_signed_receipt(
                receipt,
                public_key_b64=pub_b64,
                merkle_proof=proof,
                schema_path=schema_path,
            )
            if not ok:
                all_errors.extend(f"receipt {rid}: {e}" for e in errs)

            expected_prev = prev_by_chain.get(chain_id)
            actual_prev = str(receipt["payload"]["previous_hash"])
            if expected_prev is not None and actual_prev != expected_prev:
                all_errors.append(
                    f"receipt {rid}: broken hash chain ({actual_prev} != {expected_prev})"
                )
            prev_by_chain[chain_id] = str(receipt["envelope"]["digest_sha256"])

    return len(all_errors) == 0, all_errors


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint verifying a receipt JSON file or exported receipt ZIP bundle."""
    parser = argparse.ArgumentParser(description="Verify DLE signed receipt JSON or ZIP bundle")
    parser.add_argument("target", type=Path, help="Path to receipt JSON or ZIP bundle")
    parser.add_argument("--public-key-b64", dest="pub_b64", default="", help="Ed25519 public key")
    args = parser.parse_args(list(argv) if argv is not None else None)

    target: Path = args.target
    if not target.exists():
        print(f"File not found: {target}", file=sys.stderr)
        return 1

    if target.suffix.lower() == ".zip":
        ok, errs = verify_bundle_zip(target)
    else:
        if not args.pub_b64:
            print(
                "--public-key-b64 is required when verifying a standalone JSON receipt",
                file=sys.stderr,
            )
            return 1
        data = json.loads(target.read_text(encoding="utf-8"))
        ok, errs = verify_signed_receipt(data, public_key_b64=args.pub_b64)

    if ok:
        print(f"VERIFIED: {target}")
        return 0
    for err in errs:
        print(f"ERROR: {err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
