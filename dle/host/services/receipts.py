"""Ed25519 key lifecycle, JCS signing, WORM Merkle checkpoints, and receipt export (``H15``).

Implements FR-RCPT-01..03, FR-API-08, IR-05, and US-09..11 over ``receipts.db``.
All sealed receipts validate against ``contracts/receipt.schema.json`` (3.8.0) before
insertion into append-only SQLite tables.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import stat
import threading
import uuid
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from dle.config.loader import canonicalize_jcs
from dle.errors import ContractValidationError, DleError
from dle.store.repositories import ReceiptRepository

_DEFAULT_RECEIPT_SCHEMA = Path(__file__).resolve().parents[3] / "contracts" / "receipt.schema.json"
_ZERO_ROOT = "0" * 64


def _hash_leaf(leaf_hex: str) -> bytes:
    return hashlib.sha256(b"\x00" + bytes.fromhex(leaf_hex)).digest()


def _hash_node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def compute_merkle_root(leaf_hashes: Sequence[str]) -> str:
    """Compute domain-separated SHA-256 Merkle root over 64-hex receipt hashes."""
    if not leaf_hashes:
        return _ZERO_ROOT
    layer = [_hash_leaf(h) for h in leaf_hashes]
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        next_layer: list[bytes] = []
        for idx in range(0, len(layer), 2):
            next_layer.append(_hash_node(layer[idx], layer[idx + 1]))
        layer = next_layer
    return layer[0].hex()


def build_merkle_proof(leaf_hashes: Sequence[str], index: int) -> list[dict[str, str]]:
    """Build an inclusion proof of ``{position, hash}`` steps for ``leaf_hashes[index]``."""
    if index < 0 or index >= len(leaf_hashes):
        raise IndexError(f"Merkle leaf index {index} out of range for {len(leaf_hashes)} leaves")
    proof: list[dict[str, str]] = []
    layer = [_hash_leaf(h) for h in leaf_hashes]
    pos = index
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        sibling_idx = pos ^ 1
        sibling_side = "right" if pos % 2 == 0 else "left"
        proof.append({"position": sibling_side, "hash": layer[sibling_idx].hex()})
        next_layer: list[bytes] = []
        for idx in range(0, len(layer), 2):
            next_layer.append(_hash_node(layer[idx], layer[idx + 1]))
        layer = next_layer
        pos //= 2
    return proof


def verify_merkle_proof(
    leaf_hash: str,
    proof: Sequence[Mapping[str, str]],
    root: str,
) -> bool:
    """Verify domain-separated SHA-256 Merkle inclusion proof against ``root``."""
    try:
        current = _hash_leaf(leaf_hash)
        for step in proof:
            sib = bytes.fromhex(step["hash"])
            pos = step["position"]
            if pos == "right":
                current = _hash_node(current, sib)
            elif pos == "left":
                current = _hash_node(sib, current)
            else:
                return False
        return current.hex() == root.lower()
    except (KeyError, ValueError):
        return False


class Ed25519KeyManager:
    """Manages Ed25519 signing keys backed by ``receipts.db`` and optional PEM storage."""

    def __init__(self, repo: ReceiptRepository, *, keys_dir: Path | None = None) -> None:
        """Load active key from DB/disk or mint an initial Ed25519 keypair."""
        self._repo = repo
        self._keys_dir = keys_dir
        if self._keys_dir is not None:
            self._keys_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._private_keys: dict[str, Ed25519PrivateKey] = {}
        self._active_key_id: str | None = None
        self._bootstrap_initial_key()

    def _bootstrap_initial_key(self) -> None:
        active = self._repo.get_active_signing_key()
        if active is not None and self._keys_dir is not None:
            key_id = str(active["key_id"])
            pem_path = self._keys_dir / f"{key_id}.pem"
            if pem_path.is_file():
                loaded = load_pem_private_key(pem_path.read_bytes(), password=None)
                if isinstance(loaded, Ed25519PrivateKey):
                    self._private_keys[key_id] = loaded
                    self._active_key_id = key_id
                    return
        self.rotate_key()

    def rotate_key(self) -> dict[str, str]:
        """Retire prior active key (keeping public key verifiable) and mint a new Ed25519 key."""
        with self._lock:
            now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if self._active_key_id is not None:
                self._repo.retire_signing_key(self._active_key_id, valid_to_utc=now_utc)
            elif (prev := self._repo.get_active_signing_key()) is not None:
                self._repo.retire_signing_key(str(prev["key_id"]), valid_to_utc=now_utc)

            priv = Ed25519PrivateKey.generate()
            pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            pub_b64 = base64.b64encode(pub_raw).decode("ascii")
            key_id = f"ed25519-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
            self._repo.register_signing_key(
                key_id=key_id,
                public_key_b64=pub_b64,
                valid_from_utc=now_utc,
            )
            self._private_keys[key_id] = priv
            self._active_key_id = key_id

            if self._keys_dir is not None:
                pem_path = self._keys_dir / f"{key_id}.pem"
                pem_bytes = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
                pem_path.write_bytes(pem_bytes)
                if os.name == "posix":
                    pem_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            return {"keyId": key_id, "validFrom": now_utc, "publicKeyB64": pub_b64}

    @property
    def active_key_id(self) -> str:
        """Current active signing ``key_id``."""
        if self._active_key_id is None:
            raise DleError("no active Ed25519 signing key initialized", code="DLE-E1401")
        return self._active_key_id

    def sign_jcs(self, canonical_bytes: bytes) -> tuple[str, str]:
        """Sign RFC 8785 JCS bytes with the active key, returning ``(key_id, signature_b64)``."""
        with self._lock:
            kid = self.active_key_id
            priv = self._private_keys[kid]
            sig = priv.sign(canonical_bytes)
            return kid, base64.b64encode(sig).decode("ascii")

    def get_public_key_b64(self, key_id: str) -> str | None:
        """Return base64 raw Ed25519 public key for active or retired ``key_id``."""
        row = self._repo.get_signing_key(key_id)
        return str(row["public_key_b64"]) if row is not None else None


class ReceiptSealer:
    """Seals, persists, retrieves, and exports signed schema-3.8.0 Merkle receipts (`H15`)."""

    def __init__(
        self,
        repo: ReceiptRepository,
        key_manager: Ed25519KeyManager,
        *,
        receipt_schema_path: Path | None = None,
    ) -> None:
        """Initialize sealer with ``ReceiptRepository``, key manager, and receipt JSON schema."""
        self._repo = repo
        self._keys = key_manager
        schema_target = receipt_schema_path or _DEFAULT_RECEIPT_SCHEMA
        schema = json.loads(schema_target.read_text(encoding="utf-8"))
        self._validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.FormatChecker(),
        )
        self._lock = threading.RLock()

    def _validate_receipt(self, receipt: Mapping[str, object]) -> None:
        errors = sorted(self._validator.iter_errors(receipt), key=lambda e: list(e.absolute_path))
        if errors:
            first = errors[0]
            ptr = "/" + "/".join(str(p) for p in first.absolute_path)
            raise ContractValidationError(
                f"receipt validation failed: {first.message}",
                file_path="contracts/receipt.schema.json",
                pointer=ptr,
            )

    def seal_receipt(
        self,
        *,
        payload: Mapping[str, object],
        api_release_mode: str,
        chain_id: str = "main",
    ) -> dict[str, object]:
        """Canonicalize (RFC 8785 JCS), Ed25519-sign, Merkle-checkpoint, and persist receipt."""
        with self._lock:
            last_seq, prev_hash = self._repo.last_chain_tip(chain_id)
            chain_seq = last_seq + 1
            body = copy.deepcopy({str(k): v for k, v in payload.items()})
            body["chain_id"] = chain_id
            body["previous_hash"] = prev_hash

            jcs_bytes = canonicalize_jcs(body)
            digest_sha256 = hashlib.sha256(jcs_bytes).hexdigest()
            key_id, signature_b64 = self._keys.sign_jcs(jcs_bytes)

            existing = self._repo.list_chain_receipts(chain_id)
            leaf_hashes = [str(r["receipt_sha256"]) for r in existing] + [digest_sha256]
            merkle_root = compute_merkle_root(leaf_hashes)

            first_receipt = str(existing[0]["receipt_id"]) if existing else str(body["run_id"])
            last_receipt = str(body["run_id"])
            sealed_utc = str(body["utc"])
            log_id = f"local-worm-merkle:{chain_id}"

            provisional_envelope: dict[str, object] = {
                "digest_sha256": digest_sha256,
                "key_id": key_id,
                "algorithm": "Ed25519",
                "signature_b64": signature_b64,
                "log_id": log_id,
                "inclusion_proof_ref": f"checkpoint:next#seq:{chain_seq}",
                "verified_checkpoint_sha256": merkle_root,
                "anchoring_profile": "local_worm_merkle",
                "verification_level": "locally_sealed",
            }
            self._validate_receipt({"payload": body, "envelope": provisional_envelope})

            fn_records = body["function_invocations"]
            if not isinstance(fn_records, list):
                raise ContractValidationError(
                    "function_invocations must be a list",
                    file_path="contracts/receipt.schema.json",
                    pointer="/payload/function_invocations",
                )

            ckpt_id = len(self._repo.list_merkle_checkpoints()) + 1
            envelope = {
                **provisional_envelope,
                "inclusion_proof_ref": f"checkpoint:{ckpt_id}#seq:{chain_seq}",
            }

            self._repo.insert_receipt(
                receipt_id=str(body["run_id"]),
                chain_id=chain_id,
                chain_seq=chain_seq,
                previous_hash=prev_hash,
                receipt_sha256=digest_sha256,
                response_sha256=str(body["response_sha256"]),
                release_mode=api_release_mode,
                profile=str(body["profile"]),
                key_id=key_id,
                receipt_jcs=jcs_bytes.decode("utf-8"),
                signature_b64=signature_b64,
                anchoring_profile="local_worm_merkle",
                sealed_utc=sealed_utc,
                function_records=[dict(r) for r in fn_records if isinstance(r, Mapping)],
            )
            self._repo.insert_merkle_checkpoint(
                root_sha256=merkle_root,
                first_receipt=first_receipt,
                last_receipt=last_receipt,
                anchored_utc=sealed_utc,
                anchor_ref=f"{log_id}:seq:{chain_seq}",
            )
            sealed: dict[str, object] = {"payload": body, "envelope": envelope}
            self._validate_receipt(sealed)
            return sealed

    def get_receipt(self, receipt_id: str) -> dict[str, object] | None:
        """Reconstruct a full signed 3.8.0 receipt JSON object from ``receipts.db``."""
        row = self._repo.get_receipt(receipt_id)
        if row is None:
            return None
        return self._reconstruct_row(row)

    def _reconstruct_row(self, row: Mapping[str, object]) -> dict[str, object]:
        chain_id = str(row["chain_id"])
        chain_seq = int(str(row["chain_seq"]))
        checkpoints = self._repo.list_merkle_checkpoints()
        ckpt = (
            checkpoints[chain_seq - 1]
            if 1 <= chain_seq <= len(checkpoints)
            else (checkpoints[-1] if checkpoints else None)
        )
        root_sha = str(ckpt["root_sha256"]) if ckpt is not None else str(row["receipt_sha256"])
        ckpt_id = int(str(ckpt["checkpoint_id"])) if ckpt is not None else 1
        return {
            "payload": json.loads(str(row["receipt_jcs"])),
            "envelope": {
                "digest_sha256": str(row["receipt_sha256"]),
                "key_id": str(row["key_id"]),
                "algorithm": "Ed25519",
                "signature_b64": str(row["signature_b64"]),
                "log_id": f"local-worm-merkle:{chain_id}",
                "inclusion_proof_ref": f"checkpoint:{ckpt_id}#seq:{chain_seq}",
                "verified_checkpoint_sha256": root_sha,
                "anchoring_profile": str(row["anchoring_profile"]),
                "verification_level": "locally_sealed",
            },
        }

    def export_bundle(
        self,
        from_utc: str,
        to_utc: str,
        *,
        exported_by: str,
    ) -> bytes:
        """Build an offline-verifiable ZIP bundle containing receipts, keys, and Merkle proofs."""
        rows = self._repo.list_receipts_between(from_utc, to_utc)
        public_keys = {
            str(k["key_id"]): str(k["public_key_b64"]) for k in self._repo.list_signing_keys()
        }
        checkpoints = self._repo.list_merkle_checkpoints()
        chain_caches: dict[str, list[str]] = {}
        manifest_items: list[dict[str, object]] = []

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for row in rows:
                chain_id = str(row["chain_id"])
                chain_seq = int(str(row["chain_seq"]))
                if chain_id not in chain_caches:
                    chain_caches[chain_id] = [
                        str(item["receipt_sha256"])
                        for item in self._repo.list_chain_receipts(chain_id)
                    ]
                full_chain = chain_caches[chain_id]
                prefix_leaves = full_chain[:chain_seq]
                proof = build_merkle_proof(prefix_leaves, chain_seq - 1)
                receipt_obj = self._reconstruct_row(row)
                rid = str(row["receipt_id"])
                zf.writestr(f"receipts/{rid}.json", json.dumps(receipt_obj, indent=2))
                zf.writestr(f"proofs/{rid}.proof.json", json.dumps(proof, indent=2))
                manifest_items.append(
                    {
                        "receipt_id": rid,
                        "chain_id": chain_id,
                        "chain_seq": chain_seq,
                        "key_id": str(row["key_id"]),
                    }
                )

            manifest = {
                "from": from_utc,
                "to": to_utc,
                "exportedBy": exported_by,
                "receipts": manifest_items,
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            zf.writestr("public_keys.json", json.dumps(public_keys, indent=2))
            zf.writestr("checkpoints.json", json.dumps(checkpoints, indent=2))

        return buf.getvalue()


def verify_ed25519_signature(
    *,
    canonical_payload_bytes: bytes,
    signature_b64: str,
    public_key_b64: str,
) -> bool:
    """Verify an Ed25519 signature over RFC 8785 JCS bytes with a base64 raw public key."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        pub.verify(base64.b64decode(signature_b64), canonical_payload_bytes)
        return True
    except Exception:
        return False


__all__ = [
    "Ed25519KeyManager",
    "ReceiptSealer",
    "build_merkle_proof",
    "compute_merkle_root",
    "verify_ed25519_signature",
    "verify_merkle_proof",
]
