"""Pluggable Merkle receipt anchoring providers (``H15``, paper §16c/§16d).

Implements FR-RCPT-01..03 and ``contracts/receipt.schema.json`` conditional
``anchoring_profile`` -> ``verification_level`` rules across:
  - ``local_worm_merkle`` -> ``locally_sealed``
  - ``customer_hosted_log`` -> ``customer_anchored``
  - ``external_transparency_log`` -> ``externally_anchored``
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from dle.config.loader import canonicalize_jcs
from dle.errors import AnchorPendingError

AnchoringProfile = Literal[
    "local_worm_merkle",
    "customer_hosted_log",
    "external_transparency_log",
]
VerificationLevel = Literal[
    "locally_sealed",
    "customer_anchored",
    "externally_anchored",
]

VERIFICATION_LEVEL_BY_PROFILE: dict[AnchoringProfile, VerificationLevel] = {
    "local_worm_merkle": "locally_sealed",
    "customer_hosted_log": "customer_anchored",
    "external_transparency_log": "externally_anchored",
}

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AnchorResult:
    """Verified anchoring outcome recorded onto a sealed 3.8.0 receipt envelope."""

    anchoring_profile: AnchoringProfile
    verification_level: VerificationLevel
    log_id: str
    inclusion_proof_ref: str
    verified_checkpoint_sha256: str
    anchor_ref: str


class AnchorProvider(Protocol):
    """Protocol for local WORM, customer-hosted, and external transparency-log anchors."""

    @property
    def profile(self) -> AnchoringProfile:
        """Declared receipt anchoring profile identifier."""
        ...

    def anchor_checkpoint(
        self,
        *,
        chain_id: str,
        chain_seq: int,
        checkpoint_id: int,
        receipt_id: str,
        digest_sha256: str,
        merkle_root: str,
        sealed_utc: str,
    ) -> AnchorResult:
        """Anchor a Merkle root / receipt digest and return verified envelope metadata."""
        ...


class LocalWormMerkleAnchor:
    """Default SQLite-backed local WORM Merkle tree anchoring provider."""

    @property
    def profile(self) -> AnchoringProfile:
        """Return ``local_worm_merkle``."""
        return "local_worm_merkle"

    def anchor_checkpoint(
        self,
        *,
        chain_id: str,
        chain_seq: int,
        checkpoint_id: int,
        receipt_id: str,
        digest_sha256: str,
        merkle_root: str,
        sealed_utc: str,
    ) -> AnchorResult:
        """Record local WORM Merkle checkpoint metadata."""
        _ = (receipt_id, digest_sha256, sealed_utc)
        log_id = f"local-worm-merkle:{chain_id}"
        return AnchorResult(
            anchoring_profile="local_worm_merkle",
            verification_level="locally_sealed",
            log_id=log_id,
            inclusion_proof_ref=f"checkpoint:{checkpoint_id}#seq:{chain_seq}",
            verified_checkpoint_sha256=merkle_root,
            anchor_ref=f"{log_id}:seq:{chain_seq}",
        )


class CustomerHostedLogAnchor:
    """Customer-boundary append-only JSONL checkpoint log provider (``customer_anchored``)."""

    def __init__(self, *, log_path: Path, log_name: str = "customer-audit") -> None:
        """Bind provider to an append-only JSONL file inside the customer boundary."""
        self._log_path = log_path
        self._log_name = log_name.strip() or "customer-audit"
        self._lock = threading.RLock()

    @property
    def profile(self) -> AnchoringProfile:
        """Return ``customer_hosted_log``."""
        return "customer_hosted_log"

    def anchor_checkpoint(
        self,
        *,
        chain_id: str,
        chain_seq: int,
        checkpoint_id: int,
        receipt_id: str,
        digest_sha256: str,
        merkle_root: str,
        sealed_utc: str,
    ) -> AnchorResult:
        """Append canonical checkpoint record to the customer log and confirm inclusion."""
        with self._lock:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            existing_lines = (
                self._log_path.read_text(encoding="utf-8").splitlines()
                if self._log_path.is_file()
                else []
            )
            entry_index = len(existing_lines) + 1
            entry_body: dict[str, object] = {
                "entry_index": entry_index,
                "chain_id": chain_id,
                "chain_seq": chain_seq,
                "checkpoint_id": checkpoint_id,
                "receipt_id": receipt_id,
                "digest_sha256": digest_sha256,
                "merkle_root": merkle_root,
                "sealed_utc": sealed_utc,
            }
            entry_body["entry_sha256"] = hashlib.sha256(canonicalize_jcs(entry_body)).hexdigest()
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry_body, sort_keys=True) + "\n")

        log_id = f"customer-hosted-log:{self._log_name}"
        proof_ref = f"customer-log:{self._log_name}#entry:{entry_index}"
        return AnchorResult(
            anchoring_profile="customer_hosted_log",
            verification_level="customer_anchored",
            log_id=log_id,
            inclusion_proof_ref=proof_ref,
            verified_checkpoint_sha256=merkle_root,
            anchor_ref=proof_ref,
        )


class ExternalTransparencyLogAnchor:
    """External transparency-log anchor enforcing confirmed inclusion before declaration."""

    def __init__(
        self,
        *,
        external_log_id: str,
        submitter: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> None:
        """Initialize with external log identifier and allowlisted submitter callable."""
        clean_id = external_log_id.strip()
        if not clean_id:
            raise ValueError("external_log_id must be non-empty")
        self._external_log_id = clean_id
        self._submitter = submitter

    @property
    def profile(self) -> AnchoringProfile:
        """Return ``external_transparency_log``."""
        return "external_transparency_log"

    def anchor_checkpoint(
        self,
        *,
        chain_id: str,
        chain_seq: int,
        checkpoint_id: int,
        receipt_id: str,
        digest_sha256: str,
        merkle_root: str,
        sealed_utc: str,
    ) -> AnchorResult:
        """Submit checkpoint externally; raise ``AnchorPendingError`` if unconfirmed."""
        request_payload: dict[str, object] = {
            "log_id": self._external_log_id,
            "chain_id": chain_id,
            "chain_seq": chain_seq,
            "checkpoint_id": checkpoint_id,
            "receipt_id": receipt_id,
            "digest_sha256": digest_sha256,
            "merkle_root": merkle_root,
            "sealed_utc": sealed_utc,
        }
        try:
            resp = self._submitter(request_payload)
        except Exception as exc:
            raise AnchorPendingError(
                f"external anchoring failed for receipt {receipt_id}: {type(exc).__name__}"
            ) from exc

        if not isinstance(resp, Mapping) or resp.get("confirmed") is not True:
            raise AnchorPendingError(
                f"external log {self._external_log_id!r} did not confirm inclusion for {receipt_id}"
            )

        proof_ref = resp.get("inclusion_proof_ref")
        ckpt_sha = resp.get("checkpoint_sha256")
        if not isinstance(proof_ref, str) or not proof_ref.strip():
            raise AnchorPendingError(
                f"external log {self._external_log_id!r} omitted inclusion_proof_ref"
            )
        if not isinstance(ckpt_sha, str) or not _HEX64_RE.match(ckpt_sha.lower()):
            raise AnchorPendingError(
                f"external log {self._external_log_id!r} returned invalid checkpoint_sha256"
            )
        if ckpt_sha.lower() != merkle_root.lower():
            raise AnchorPendingError(
                f"external log checkpoint {ckpt_sha[:12]} mismatched Merkle root {merkle_root[:12]}"
            )

        return AnchorResult(
            anchoring_profile="external_transparency_log",
            verification_level="externally_anchored",
            log_id=self._external_log_id,
            inclusion_proof_ref=proof_ref.strip(),
            verified_checkpoint_sha256=ckpt_sha.lower(),
            anchor_ref=proof_ref.strip(),
        )


__all__ = [
    "VERIFICATION_LEVEL_BY_PROFILE",
    "AnchorProvider",
    "AnchorResult",
    "AnchoringProfile",
    "CustomerHostedLogAnchor",
    "ExternalTransparencyLogAnchor",
    "LocalWormMerkleAnchor",
    "VerificationLevel",
]
