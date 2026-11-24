"""Reference data loader and code validator for Quad Persona fields (``H8``).

Implements DLE-SPC-004 §5 and FR-QP-02: parses ``config/reference/manifest.yaml``,
loads staged CIP 2020, CIP-SOC, and O*NET reference tables when present, verifies
SHA-256 checksums, logs structured warnings and marks runs non-certifiable when
reference catalogs are absent, and validates CIP2020 / SOC2018 / ONET-SOC codes.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from dle.config.loader import canonicalize_jcs
from dle.errors import ConfigError
from dle.observability import get_logger, sha256_text

CIP_CODE_RE = re.compile(r"^\d{2}(?:\.\d{2}(?:\d{2})?)?$")
SOC_CODE_RE = re.compile(r"^\d{2}-\d{4}(?:\.\d{2})?$")


@dataclass(frozen=True)
class ReferenceSourceEntry:
    """Single source definition parsed from ``config/reference/manifest.yaml``."""

    source_id: str
    title: str
    publisher: str
    url: str
    used_for: tuple[str, ...]
    file: str
    sha256: str | None


@dataclass(frozen=True)
class ReferenceCatalog:
    """Validated in-memory index of reference occupation and education taxonomies."""

    version: str
    manifest_sha256: str
    sources: tuple[ReferenceSourceEntry, ...]
    cip_codes: frozenset[str]
    soc_codes: frozenset[str]
    onet_codes: frozenset[str]
    cip_to_soc: Mapping[str, tuple[str, ...]]
    soc_related: Mapping[str, tuple[str, ...]]
    cip_titles: Mapping[str, str]
    soc_titles: Mapping[str, str]
    present_sources: tuple[str, ...]
    missing_sources: tuple[str, ...]
    certified_eligible: bool
    file_digests: Mapping[str, str]

    def validate_code(self, scheme: str, code: str) -> tuple[bool, str | None]:
        """Validate ``code`` syntax and loaded reference membership for ``scheme``."""
        clean = code.strip()
        if scheme == "CIP2020":
            if not CIP_CODE_RE.match(clean):
                return False, f"CIP2020 code {clean!r} does not match taxonomy pattern"
            if "cip2020" in self.present_sources and clean not in self.cip_codes:
                return False, f"CIP2020 code {clean!r} not found in loaded cip2020 reference"
            return True, None

        if scheme in ("SOC2018", "ONET-SOC"):
            if not SOC_CODE_RE.match(clean):
                return False, f"{scheme} code {clean!r} does not match taxonomy pattern"
            if scheme == "SOC2018":
                loaded = "cip2020_soc2018" in self.present_sources or (
                    "onet_soc" in self.present_sources
                )
                pool = self.soc_codes | self.onet_codes
                if loaded and clean not in pool:
                    return False, f"SOC2018 code {clean!r} not found in loaded reference tables"
            elif "onet_soc" in self.present_sources and clean not in self.onet_codes:
                return False, f"ONET-SOC code {clean!r} not found in loaded onet_soc reference"
            return True, None

        return True, None


def compute_file_sha256(path: Path) -> str:
    """Compute hex SHA-256 digest of ``path`` using 64 KiB buffered reads."""
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65_536):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_reference_manifest(manifest_path: Path) -> tuple[str, tuple[ReferenceSourceEntry, ...]]:
    """Parse and validate ``config/reference/manifest.yaml``."""
    if not manifest_path.is_file():
        raise ConfigError(f"reference manifest not found: {manifest_path}")
    loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ConfigError(f"reference manifest root must be a mapping: {manifest_path}")
    version = str(loaded.get("version", "1.0.0"))
    raw_sources = loaded.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ConfigError(f"reference manifest missing non-empty 'sources': {manifest_path}")

    entries: list[ReferenceSourceEntry] = []
    for idx, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            raise ConfigError(f"reference manifest source[{idx}] must be a mapping")
        sid = str(item.get("id", "")).strip()
        file_name = str(item.get("file", "")).strip()
        if not sid or not file_name:
            raise ConfigError(f"reference manifest source[{idx}] requires non-empty id and file")
        raw_sha = item.get("sha256")
        sha_val: str | None = None
        if raw_sha is not None and str(raw_sha).strip():
            sha_val = str(raw_sha).strip().lower()
            if len(sha_val) != 64 or any(c not in "0123456789abcdef" for c in sha_val):
                raise ConfigError(f"reference source {sid!r} has invalid sha256 pin {sha_val!r}")
        raw_used = item.get("used_for", [])
        used_for = tuple(str(u).strip() for u in raw_used) if isinstance(raw_used, list) else ()
        entries.append(
            ReferenceSourceEntry(
                source_id=sid,
                title=str(item.get("title", sid)),
                publisher=str(item.get("publisher", "")),
                url=str(item.get("url", "")),
                used_for=used_for,
                file=file_name,
                sha256=sha_val,
            )
        )
    return version, tuple(entries)


def _resolve_source_file(base_dir: Path, declared_file: str) -> Path | None:
    candidate = base_dir / declared_file
    if candidate.is_file():
        return candidate
    if candidate.suffix.lower() == ".xlsx":
        for alt_ext in (".csv", ".tsv", ".json"):
            alt = candidate.with_suffix(alt_ext)
            if alt.is_file():
                return alt
    return None


def _normalize_row(row: Mapping[str, object]) -> dict[str, str]:
    return {str(k).strip().lower(): str(v).strip() for k, v in row.items() if v is not None}


def _read_tabular_rows(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, list):
            return [_normalize_row(r) for r in parsed if isinstance(r, Mapping)]
        return []
    if suffix in (".csv", ".tsv"):
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            return [_normalize_row(r) for r in reader]
    return []


def _first_nonempty(row: Mapping[str, str], keys: Sequence[str]) -> str:
    for key in keys:
        val = row.get(key, "").strip()
        if val:
            return val
    return ""


def load_reference_catalog(
    manifest_path: Path,
    ref_dir: Path | None = None,
) -> ReferenceCatalog:
    """Load staged reference taxonomies, verify SHA-256 pins, and warn when absent."""
    log = get_logger("dle.host.services.reference")
    version, sources = parse_reference_manifest(manifest_path)
    search_dir = ref_dir if ref_dir is not None else manifest_path.parent

    cip_codes: set[str] = set()
    soc_codes: set[str] = set()
    onet_codes: set[str] = set()
    cip_to_soc_mut: dict[str, list[str]] = {}
    soc_related_mut: dict[str, list[str]] = {}
    cip_titles: dict[str, str] = {}
    soc_titles: dict[str, str] = {}
    present_sources: list[str] = []
    missing_sources: list[str] = []
    file_digests: dict[str, str] = {}

    for entry in sources:
        found = _resolve_source_file(search_dir, entry.file)
        if found is None:
            missing_sources.append(entry.source_id)
            continue

        actual_sha = compute_file_sha256(found)
        if entry.sha256 is not None and actual_sha != entry.sha256:
            raise ConfigError(
                f"reference file checksum mismatch for {entry.source_id!r} ({found.name}): "
                f"expected {entry.sha256}, got {actual_sha}"
            )
        file_digests[entry.source_id] = actual_sha
        present_sources.append(entry.source_id)

        rows = _read_tabular_rows(found)
        for row in rows:
            cip = _first_nonempty(row, ("cip_code", "cip2020", "cipcode", "cip", "code"))
            soc = _first_nonempty(
                row,
                ("soc_code", "soc2018", "soccode", "soc", "o*net-soc code", "onet_code"),
            )
            title = _first_nonempty(row, ("title", "cip_title", "soc_title", "occupation"))
            related_raw = _first_nonempty(
                row, ("related_soc", "related_codes", "related_occupations", "related")
            )

            if entry.source_id == "cip2020":
                if CIP_CODE_RE.match(cip):
                    cip_codes.add(cip)
                    if title:
                        cip_titles[cip] = title
            elif entry.source_id == "cip2020_soc2018":
                if CIP_CODE_RE.match(cip):
                    cip_codes.add(cip)
                    if SOC_CODE_RE.match(soc):
                        bucket = cip_to_soc_mut.setdefault(cip, [])
                        if soc not in bucket:
                            bucket.append(soc)
                if SOC_CODE_RE.match(soc):
                    soc_codes.add(soc)
                    if title and soc not in soc_titles:
                        soc_titles[soc] = title
            elif entry.source_id == "onet_soc":
                onet_val = _first_nonempty(row, ("onet_code", "o*net-soc code", "soc_code", "code"))
                if SOC_CODE_RE.match(onet_val):
                    onet_codes.add(onet_val)
                    base_soc = onet_val.split(".", 1)[0]
                    soc_codes.add(base_soc)
                    if title:
                        soc_titles[onet_val] = title
                        soc_titles.setdefault(base_soc, title)
                    if related_raw:
                        rel_items = [
                            tok.strip()
                            for tok in re.split(r"[;|,]", related_raw)
                            if SOC_CODE_RE.match(tok.strip())
                        ]
                        if rel_items:
                            soc_related_mut[onet_val] = list(dict.fromkeys(rel_items))

    if missing_sources:
        log.warning(
            "reference.catalog_absent",
            manifest_path=str(manifest_path),
            missing_sources=missing_sources,
            certified_eligible=False,
        )

    certified = len(missing_sources) == 0 and all(s.source_id in file_digests for s in sources)
    manifest_digest = sha256_text(
        canonicalize_jcs(
            {
                "version": version,
                "sources": [s.source_id for s in sources],
                "digests": file_digests,
            }
        ).decode("utf-8")
    )
    return ReferenceCatalog(
        version=version,
        manifest_sha256=manifest_digest,
        sources=sources,
        cip_codes=frozenset(cip_codes),
        soc_codes=frozenset(soc_codes),
        onet_codes=frozenset(onet_codes),
        cip_to_soc={k: tuple(v) for k, v in cip_to_soc_mut.items()},
        soc_related={k: tuple(v) for k, v in soc_related_mut.items()},
        cip_titles=cip_titles,
        soc_titles=soc_titles,
        present_sources=tuple(present_sources),
        missing_sources=tuple(missing_sources),
        certified_eligible=certified,
        file_digests=file_digests,
    )


__all__ = [
    "CIP_CODE_RE",
    "SOC_CODE_RE",
    "ReferenceCatalog",
    "ReferenceSourceEntry",
    "compute_file_sha256",
    "load_reference_catalog",
    "parse_reference_manifest",
]
