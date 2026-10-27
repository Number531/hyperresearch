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
from pathlib import Path

import yaml

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
    """Require reviewed outcomes for every critical/major, never log presence.

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
    blocking = {identity for identity, item in known.items() if item["severity"] in {"critical", "major"}}
    # Minor-only patch passes use this canonical application stub and
    # need no additional review. Any recorded outcome or claimed review still
    # receives strict revision/identity validation below.
    if not blocking and not records and payload.get("reviewed_report_revision") is None:
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
    missing = blocking - resolved
    if missing:
        raise CitationContractError(f"{len(missing)} critical/major finding(s) lack reviewed resolution")


def source_input(vault, note_id: str, cache: dict | None = None) -> tuple[dict, str | None]:
    """Snapshot a current DB-mapped, contained note and its parsed source body.

    Paths from artifacts are never used to open files. Invalid paths are hard
    errors; only safe contained read/parse failures become unavailable bodies.
    Cache per unique note within one extraction/validation, never across runs.
    """
    if cache is not None and note_id in cache:
        return cache[note_id]
    row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        raise CitationContractError("source note_id has no current DB path")
    relative = Path(_string(row["path"], "source DB path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise CitationContractError("source path must be contained in vault notes directory")
    root, notes_root = vault.root.resolve(), vault.notes_dir.resolve()
    path = root / relative
    try:
        notes_root.relative_to(root)
        path.resolve().relative_to(root)
        path.resolve().relative_to(notes_root)
    except (ValueError, OSError, RuntimeError) as exc:
        raise CitationContractError("source path escapes vault root/notes directory") from exc
    component = root
    for part in relative.parts:
        component /= part
        if component.is_symlink():
            raise CitationContractError("source path contains a symlink")
    snapshot = {"path": relative.as_posix(), "revision": None, "body_status": "unavailable"}
    body = None
    try:
        raw = path.read_bytes()
    except OSError:
        pass
    else:
        snapshot["revision"] = report_revision(raw)
        from hyperresearch.core.frontmatter import FRONTMATTER_RE, parse_frontmatter

        try:
            text = raw.decode("utf-8-sig")
            # The shared parser deliberately returns the original text for
            # non-mapping YAML, and treats unclosed frontmatter as plain text.
            # Those diagnostic fallbacks must never qualify metadata as a
            # citation body. Keep its boundary/parser, with a scoped guard.
            frontmatter = FRONTMATTER_RE.match(text)
            if frontmatter is not None:
                closing_line = text[frontmatter.end(1) + 1:].splitlines()[0]
                if closing_line.strip() != "---":
                    raise ValueError("malformed source frontmatter delimiter")
                metadata = yaml.safe_load(frontmatter.group(1))
                if metadata is not None and not isinstance(metadata, dict):
                    raise ValueError("source frontmatter must be a mapping")
            elif re.match(r"^---\s*(?:\n|\Z)", text):
                raise ValueError("unclosed source frontmatter")
            _, body = parse_frontmatter(text)
        except (UnicodeError, ValueError, yaml.YAMLError):
            body = None
        else:
            snapshot["body_status"] = "available" if body.strip() else "empty"
    result = snapshot, body
    if cache is not None:
        cache[note_id] = result
    return result


def _identities(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise CitationContractError(f"{field} must be an array of pair IDs")
    if any(not isinstance(item, str) or not _PAIR_RE.fullmatch(item) for item in value):
        raise CitationContractError(f"{field} contains an invalid pair_id")
    if len(set(value)) != len(value):
        raise CitationContractError(f"duplicate {field}")
    return value


def validate_coverage(pairs_payload: object, findings_payload: object, vault, *, source_cache: dict | None = None) -> dict:
    """Reconcile exact selected results, negative findings, and source inputs.

    This validates recorded selected work and literal body passages, not
    semantic entailment, original-source qualification, or producer independence.
    The original report may have been patched; final-byte ordering is separate.
    """
    pairs = parse_pairs(pairs_payload)
    findings = parse_findings(findings_payload)
    bind_findings(findings, pairs)
    # Require results explicitly even when the correct selected set is empty.
    results = _records(findings_payload.get("results"), "results")
    mode = _enum(pairs_payload.get("coverage_mode"), {"sampled", "comprehensive"}, "coverage_mode")
    sampling = pairs_payload.get("sampling")
    if not isinstance(sampling, dict) or sampling.get("method") != "deterministic-floor-v1":
        raise CitationContractError("sampling requires deterministic-floor-v1 method")
    rate = sampling.get("weak_sample_rate")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        raise CitationContractError("weak_sample_rate must be a number")
    from hyperresearch.core.citecheck import sample_needs_llm, sentence_routing

    routed = []
    for index, pair in enumerate(pairs.pairs):
        if pair["pair_index"] != index:
            raise CitationContractError("pairs must retain contiguous original extraction order")
        numbers, strong = sentence_routing(pair["sentence"])
        expected_verdict = "dangling" if pair["note_id"] is None else "needs-llm"
        if (type(pair.get("strong")) is not bool or pair["strong"] != strong
                or pair.get("numbers") != numbers or pair.get("verdict") != expected_verdict):
            raise CitationContractError("pair routing differs from its original sentence/citation")
        routed.append(pair)
    expected = [pair["pair_id"] for pair in sample_needs_llm(routed, rate)]
    if mode == "comprehensive" and rate != 1:
        raise CitationContractError("comprehensive coverage requires weak_sample_rate 1")
    selected = _identities(pairs_payload.get("selected_pair_ids"), "selected_pair_ids")
    if selected != expected:
        raise CitationContractError("selected_pair_ids differ from declared sampling")
    selected_set = set(selected)
    remainder = [pair["pair_id"] for pair in routed
                 if pair["note_id"] is not None and pair["pair_id"] not in selected_set]
    if _identities(pairs_payload.get("unreviewed_pair_ids"), "unreviewed_pair_ids") != remainder:
        raise CitationContractError("unreviewed_pair_ids differ from actual unreviewed remainder")
    if mode == "comprehensive" and remainder:
        raise CitationContractError("comprehensive coverage has unreviewed pairs")
    sampled = _records(pairs_payload.get("sampled_for_llm"), "sampled_for_llm")
    if sampled != [pair for pair in routed if pair["pair_id"] in selected_set]:
        raise CitationContractError("sampled_for_llm differs from exact selected pairs")
    dangling = [pair for pair in routed if pair["note_id"] is None]
    if _records(pairs_payload.get("dangling"), "dangling") != dangling:
        raise CitationContractError("dangling array differs from every extracted dangling occurrence")
    summary = pairs_payload.get("summary")
    counts = {"total": len(routed), "dangling": len(dangling),
              "needs_llm": len(routed) - len(dangling),
              "selected": len(selected), "unreviewed": len(remainder)}
    if not isinstance(summary, dict) or any(
        type(summary.get(key)) is not int or summary[key] != count for key, count in counts.items()
    ):
        raise CitationContractError("summary counts differ from actual selected/unreviewed coverage")
    if _identities(findings_payload.get("selected_pair_ids"), "results selected_pair_ids") != selected:
        raise CitationContractError("results selected_pair_ids do not cover exact selected set")
    by_id = {pair["pair_id"]: pair for pair in routed}
    findings_by_pair = {item["pair_id"]: item for item in findings.findings}
    source_cache = {} if source_cache is None else source_cache
    for pair in routed:
        if pair["note_id"] is None:
            item = findings_by_pair.get(pair["pair_id"])
            if item is None or item["verdict"] != "dangling" or item["severity"] != "critical":
                raise CitationContractError("every dangling occurrence requires its own critical finding")
        else:
            current, _ = source_input(vault, pair["note_id"], source_cache)
            if pair.get("source_input") != current:
                raise CitationContractError("source_input is stale or differs from current DB-mapped note path/body")
    seen: set[str] = set()
    failures: set[str] = set()
    for result in results:
        identity = _string(result.get("pair_id"), "result pair_id")
        if identity not in selected_set:
            raise CitationContractError("result references unknown/unselected pair_id")
        if identity in seen:
            raise CitationContractError("duplicate result pair_id")
        seen.add(identity)
        verdict = _enum(result.get("verdict"), {"supported", "partially-supported", "unsupported", "wrong-source"}, "result verdict")
        _string(result.get("evidence"), "result evidence")
        pair = by_id[identity]
        snapshot, body = source_input(vault, pair["note_id"], source_cache)
        if "source_revision" not in result or result["source_revision"] != snapshot["revision"]:
            raise CitationContractError("result source_revision is stale/unrelated")
        excerpt = result.get("source_excerpt")
        if snapshot["body_status"] == "available":
            if _string(excerpt, "result source_excerpt") not in body:
                raise CitationContractError("result source_excerpt is not a literal source-body passage")
        elif verdict in {"supported", "partially-supported"}:
            raise CitationContractError("empty/unavailable source body cannot establish support")
        elif excerpt is not None:
            raise CitationContractError("empty/unavailable body requires null/absent source_excerpt")
        item = findings_by_pair.get(identity)
        if verdict == "supported":
            if item is not None:
                raise CitationContractError("supported result cannot also have a finding")
        else:
            failures.add(identity)
            if item is None or item["verdict"] != verdict:
                raise CitationContractError("negative result requires matching same-verdict finding")
            if (verdict == "wrong-source" or (verdict == "unsupported" and pair["numbers"])) and item["severity"] != "critical":
                raise CitationContractError("wrong-source and unsupported numeric results require critical findings")
    if seen != selected_set:
        raise CitationContractError("results dropped selected pair_id(s)")
    expected_findings = failures | {pair["pair_id"] for pair in routed if pair["note_id"] is None}
    if set(findings_by_pair) != expected_findings:
        raise CitationContractError("findings include unselected/unmatched negative records")
    return {"coverage_mode": mode, "selected": len(selected), "reviewed": len(seen),
            "unreviewed": len(remainder), "dangling": len(expected_findings - failures)}


def merge_findings_shards(pairs_payload: object, shards: list[object], vault) -> dict:
    """Retain all disjoint shard IDs/results/evidence, then validate their union.

    Include the mandatory dangling findings in one shard (which may have an
    empty selected list). Never merge only findings and discard supported work.
    """
    pairs = parse_pairs(pairs_payload)
    if not isinstance(shards, list):
        raise CitationContractError("shards must be an array of findings envelopes")
    merged = {"schema_version": CONTRACT_VERSION, "report_revision": pairs.report_revision,
              "selected_pair_ids": [], "results": [], "findings": []}
    seen: set[str] = set()
    semantic_owners = 0
    for shard in shards:
        parsed = parse_findings(shard)
        bind_findings(parsed, pairs)
        ids = _identities(shard.get("selected_pair_ids"), "shard selected_pair_ids")
        if seen & set(ids):
            raise CitationContractError("duplicate selected pair_id across shards")
        seen.update(ids)
        records = _records(shard.get("results"), "shard results")
        result_ids = _identities([item.get("pair_id") for item in records], "shard result pair_ids")
        if set(result_ids) != set(ids):
            raise CitationContractError("shard results differ from its selected_pair_ids")
        merged["selected_pair_ids"].extend(ids)
        merged["results"].extend(records)
        merged["findings"].extend(parsed.findings)
        if "semantic_review" in shard:
            semantic_owners += 1
            if semantic_owners > 1:
                raise CitationContractError("exactly one shard may own the complete semantic_review")
            merged["semantic_review"] = shard["semantic_review"]
    # Shards may finish in any order; use the extraction's canonical ID order.
    merged["selected_pair_ids"] = [identity for identity in pairs_payload.get("selected_pair_ids", []) if identity in seen]
    if set(merged["selected_pair_ids"]) != seen:
        raise CitationContractError("shard references unknown/unselected pair_id")
    validate_coverage(pairs_payload, merged, vault)
    return merged
