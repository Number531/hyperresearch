"""Versioned identities and read-only validation for existing citation artifacts.

These contracts check recorded work, not semantic truth. Legacy findings can
be inspected without migration; missing identity is never invented for them.
Report revisions hash exact bytes (including BOMs and newline conventions).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

CONTRACT_VERSION = 1
_REVISION_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PAIR_RE = re.compile(r"pair-v1:([0-9a-f]{64})\Z")
_FINDING_RE = re.compile(r"finding-v1:[0-9a-f]{64}\Z")
_SEVERITIES = {"critical", "major", "minor"}
_FAILURE_VERDICTS = {"partially-supported", "unsupported", "wrong-source", "dangling"}
_REVIEW_VERDICTS = {"supported", "claim-removed", "unresolved"}


class CitationContractError(ValueError):
    """An artifact cannot establish the citation claim it records."""


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CitationContractError(f"{field} must be a nonempty string")
    return value


def _nullable_string(value: object, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _enum(value: object, allowed: set[str], field: str) -> str:
    value = _string(value, field)
    if value not in allowed:
        raise CitationContractError(f"{field} has unknown value {value!r}")
    return value


def _revision(value: object, field: str = "report_revision") -> str:
    if not isinstance(value, str) or not _REVISION_RE.fullmatch(value):
        raise CitationContractError(f"{field} must be a sha256 report revision")
    return value


def _version(payload: dict) -> None:
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != CONTRACT_VERSION:
        raise CitationContractError(f"schema_version must be {CONTRACT_VERSION}")


def _records(value: object, field: str) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise CitationContractError(f"{field} must be an array of objects")
    return value


def report_revision(report_bytes: bytes) -> str:
    """Return the revision of exact on-disk bytes, without text normalization."""
    return "sha256:" + hashlib.sha256(report_bytes).hexdigest()


def pair_id(revision: str, pair_index: int, sentence: str, note_id: str | None) -> str:
    """Identify one occurrence in the version-1 citation extraction order."""
    _revision(revision)
    if type(pair_index) is not int or pair_index < 0:
        raise CitationContractError("pair_index must be a nonnegative integer")
    _string(sentence, "sentence")
    _nullable_string(note_id, "note_id")
    encoded = json.dumps(
        [CONTRACT_VERSION, revision, pair_index, sentence, note_id],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return "pair-v1:" + hashlib.sha256(encoded).hexdigest()


def finding_id(identity: str) -> str:
    """One finding identity per pair, copied by producers from the pairs file."""
    if not isinstance(identity, str) or not (match := _PAIR_RE.fullmatch(identity)):
        raise CitationContractError("pair_id must be a version-1 pair identity")
    return "finding-v1:" + match.group(1)


@dataclass(frozen=True)
class FindingsDocument:
    findings: tuple[dict, ...]
    report_revision: str | None
    legacy: bool


@dataclass(frozen=True)
class PairsDocument:
    pairs: tuple[dict, ...]
    report_revision: str


def parse_pairs(payload: object) -> PairsDocument:
    """Validate the original extraction manifest without reading or rewriting it."""
    if not isinstance(payload, dict):
        raise CitationContractError("pairs artifact must be an object")
    _version(payload)
    revision = _revision(payload.get("report_revision"))
    pairs = _records(payload.get("pairs"), "pairs")
    seen: set[str] = set()
    indices: set[int] = set()
    for pair in pairs:
        index = pair.get("pair_index")
        if "note_id" not in pair:
            raise CitationContractError("pair note_id is required (null for dangling)")
        expected = pair_id(revision, index, pair.get("sentence"), pair["note_id"])
        if pair.get("pair_id") != expected or pair.get("finding_id") != finding_id(expected):
            raise CitationContractError("pair identity does not match its original revision/content")
        if expected in seen or index in indices:
            raise CitationContractError("duplicate pair identity/index")
        seen.add(expected)
        indices.add(index)
    return PairsDocument(tuple(pairs), revision)


def parse_findings(payload: object) -> FindingsDocument:
    """Accept explicit legacy shapes for diagnostics, and enforce version-1 fields.

    Empty legacy lists are explicit zero findings, not proof that review ran.
    Nonempty legacy records cannot prove resolution without versioned identity.
    Unknown extension keys are retained; known fields never accept wrong types.
    """
    if isinstance(payload, list):
        records, legacy, revision = payload, True, None
    elif isinstance(payload, dict):
        if "findings" not in payload:
            raise CitationContractError("findings array is required")
        legacy = "schema_version" not in payload
        if not legacy:
            _version(payload)
            revision = _revision(payload.get("report_revision"))
        else:
            revision = None
            if "report_revision" in payload:
                _revision(payload["report_revision"])
        records = payload["findings"]
    else:
        raise CitationContractError("findings must be an object or legacy array")

    findings = _records(records, "findings")
    seen_findings: set[str] = set()
    seen_pairs: set[str] = set()
    for item in findings:
        _enum(item.get("severity"), _SEVERITIES, "severity")
        _enum(item.get("verdict"), _FAILURE_VERDICTS, "verdict")
        for field in ("sentence", "evidence", "suggested_fix"):
            if not legacy or field in item:
                _string(item.get(field), field)
        for field in ("cited_note_id", "correct_note_id"):
            if not legacy and field not in item:
                raise CitationContractError(f"{field} is required (may be null)")
            if field in item:
                _nullable_string(item[field], field)
        if not legacy or "pair_id" in item or "finding_id" in item:
            identity = item.get("pair_id")
            expected = finding_id(identity)
            if item.get("finding_id") != expected:
                raise CitationContractError("finding_id does not match pair_id")
            if identity in seen_pairs or expected in seen_findings:
                raise CitationContractError("duplicate finding/pair identity")
            seen_pairs.add(identity)
            seen_findings.add(expected)
    return FindingsDocument(tuple(findings), revision, legacy)


def bind_findings(findings: FindingsDocument, pairs: PairsDocument) -> None:
    """Bind versioned findings to the original extraction, before patching."""
    if findings.legacy:
        raise CitationContractError("legacy findings have no verified original revision/identity")
    if findings.report_revision != pairs.report_revision:
        raise CitationContractError("findings report_revision differs from original pairs revision")
    by_id = {pair["pair_id"]: pair for pair in pairs.pairs}
    for item in findings.findings:
        pair = by_id.get(item["pair_id"])
        if pair is None:
            raise CitationContractError("finding references unknown original pair_id")
        if (item["finding_id"] != pair["finding_id"]
                or item["sentence"] != pair["sentence"]
                or item["cited_note_id"] != pair["note_id"]):
            raise CitationContractError("finding does not match original pair sentence/note/identity")


def validate_resolutions(
    findings: FindingsDocument, payload: object, current_report_revision: str,
) -> None:
    """Require explicit reviewed outcomes for every critical, never log presence.

    The findings revision names the original audit input. The reviewed revision
    names the post-patch report, which may legitimately have different bytes.
    This receipt cannot prove independent producer work or semantic truth.
    """
    if findings.legacy:
        raise CitationContractError("legacy findings cannot establish reviewed resolution")
    if not isinstance(payload, dict):
        raise CitationContractError("citation patch log must be a versioned object")
    _version(payload)
    if _revision(payload.get("findings_report_revision"), "findings_report_revision") != findings.report_revision:
        raise CitationContractError("resolution findings_report_revision is stale/unrelated")
    records = _records(payload.get("resolutions"), "resolutions")
    known = {item["finding_id"]: item for item in findings.findings}
    criticals = {identity for identity, item in known.items() if item["severity"] == "critical"}
    # Noncritical-only patch passes use this canonical application stub and
    # need no additional review. Any recorded outcome or claimed review still
    # receives strict revision/identity validation below.
    if not criticals and not records and payload.get("reviewed_report_revision") is None:
        return
    reviewed = _revision(payload.get("reviewed_report_revision"), "reviewed_report_revision")
    if reviewed != _revision(current_report_revision):
        raise CitationContractError("resolution reviewed_report_revision is stale for current report bytes")
    resolved: set[str] = set()
    seen: set[str] = set()
    for record in records:
        identity = _string(record.get("finding_id"), "resolution finding_id")
        if not _FINDING_RE.fullmatch(identity) or identity not in known:
            raise CitationContractError("resolution references unknown finding_id")
        if identity in seen:
            raise CitationContractError("duplicate resolution finding_id")
        seen.add(identity)
        status = _enum(record.get("status"), {"resolved", "unresolved"}, "resolution status")
        verdict = _enum(record.get("review_verdict"), _REVIEW_VERDICTS, "review_verdict")
        _string(record.get("evidence"), "resolution evidence")
        if status == "resolved":
            if verdict not in {"supported", "claim-removed"}:
                raise CitationContractError("resolved finding requires a successful reviewed outcome")
            resolved.add(identity)
    missing = criticals - resolved
    if missing:
        raise CitationContractError(f"{len(missing)} critical finding(s) lack reviewed resolution")
