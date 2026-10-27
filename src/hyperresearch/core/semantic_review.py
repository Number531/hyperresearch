"""Pure, versioned validation of recorded whole-report semantic judgments.

Coverage, identity and literal passages are deterministic. Atomization,
nonassertive classification, entailment and method adequacy remain reviewer
judgments; this module does not establish truth or independent execution.
"""

from __future__ import annotations

import hashlib
import json
import re

from hyperresearch.core.citation_contracts import CitationContractError

SEMANTIC_VERSION = 1
METHOD_DIMENSIONS = (
    "signs", "units", "denominators", "study_universe", "horizon",
    "api_vs_format", "measured_vs_reported", "costs_eligibility_pit",
    "method_feasibility", "counterhypothesis",
)
_OUTCOMES = {"satisfactory", "not-applicable", "concern", "unknown"}
_DISPOSITIONS = {"supported", "partially-supported", "unsupported", "unknown"}
_PRESENTATIONS = {
    "empirical": {"evidence-backed"}, "derived": {"derived"},
    "proposal": {"proposed"}, "design-parameter": {"design-parameter"},
    "capture-gap": {"bounded-capture-gap"},
}


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CitationContractError(f"semantic {name} must be a nonempty string")
    return value


def _records(value: object, name: str) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise CitationContractError(f"semantic {name} must be an array of objects")
    return value


def assertion_id(revision: str, unit_id: str, start: int, end: int, text: str) -> str:
    """Bind an assertion occurrence to the exact whole-report revision and span."""
    return "assertion-v1:" + _digest([SEMANTIC_VERSION, revision, unit_id, start, end, text])[7:]


def build_inventory(report_text: str, revision: str, pairs: list[dict]) -> dict:
    """Inventory every nonblank physical line, including reference-section tails.

    Contiguous nonblank blocks and the active heading path preserve tables,
    lists, quotes, qualifiers and citation context. Offsets are Unicode character
    offsets in the UTF-8-sig decoded report; revision still hashes exact bytes.
    No heading, source list, code block or other content is presumed nonassertive.
    """
    lines = []
    offset = 0
    for line in report_text.splitlines(keepends=True):
        raw = line.rstrip("\r\n")
        start = offset + len(raw) - len(raw.lstrip())
        end = offset + len(raw.rstrip())
        if start < end:
            lines.append({"start": start, "end": end, "text": report_text[start:end]})
        offset += len(line)
    # A block is the complete contiguous nonblank line group, never a guessed
    # sentence. Blank boundaries are read from the original characters.
    groups = []
    for line in lines:
        if not groups or re.search(r"\n[ \t\r]*\n", report_text[groups[-1][-1]["end"]:line["start"]]):
            groups.append([])
        groups[-1].append(line)
    units = []
    headings: list[tuple[int, str]] = []
    for group in groups:
        block_start, block_end = group[0]["start"], group[-1]["end"]
        context_pairs = [pair["pair_id"] for pair in pairs
                         if isinstance(pair.get("report_span"), dict)
                         and pair["report_span"]["start"] < block_end
                         and pair["report_span"]["end"] > block_start]
        for line in group:
            heading = re.match(r"^(#{1,6})\s+", line["text"])
            if heading:
                level = len(heading[1])
                headings = [item for item in headings if item[0] < level]
                headings.append((level, line["text"]))
            kind = ("heading" if heading else "table" if line["text"].startswith("|") else
                    "quote" if line["text"].startswith(">") else
                    "list" if re.match(r"^(?:[-*+]\s|\d+[.)]\s)", line["text"]) else "prose")
            content = {"index": len(units), "start": line["start"], "end": line["end"],
                       "text": line["text"], "kind": kind,
                       "context": {"heading_path": [item[1] for item in headings],
                                   "block_start": block_start, "block_end": block_end,
                                   "block_text": report_text[block_start:block_end],
                                   "pair_ids": context_pairs}}
            content["unit_id"] = "unit-v1:" + _digest([revision, content])[7:]
            units.append(content)
    content = {"schema_version": SEMANTIC_VERSION, "report_revision": revision, "units": units}
    return {**content, "inventory_digest": _digest(content)}


def _judgment(value: object, name: str) -> str:
    if (not isinstance(value, dict) or not isinstance(value.get("outcome"), str)
            or value["outcome"] not in _OUTCOMES):
        raise CitationContractError(f"semantic {name} requires an explicit scoped outcome")
    _text(value.get("reason"), f"{name} reason")
    return value["outcome"]


def validate_review(
    report_text: str, revision: str, pairs_payload: dict, review: object,
    sources: dict[str, tuple[dict, str | None]],
) -> dict:
    """Validate complete, current recorded review against caller-supplied bodies.

    The caller obtains bodies through source_input, never artifact paths. Only
    actual citations in the assertion's contiguous report block can be evidence.
    This pure seam performs no filesystem, database, network or model access.
    """
    inventory = build_inventory(report_text, revision, pairs_payload["pairs"])
    if pairs_payload.get("semantic_inventory") != inventory:
        raise CitationContractError("semantic inventory differs from the complete current report")
    if not isinstance(review, dict) or type(review.get("schema_version")) is not int or review["schema_version"] != SEMANTIC_VERSION:
        raise CitationContractError("semantic_review requires version 1 whole-report review")
    if (review.get("report_revision") != revision or
            review.get("inventory_digest") != inventory["inventory_digest"] or
            review.get("finalization_input_digest") != pairs_payload["finalization_inputs"]["input_digest"]):
        raise CitationContractError("semantic review report/context/task binding is stale")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("scope") != "whole-report":
        raise CitationContractError("semantic reviewer must own the whole report")
    _text(reviewer.get("identity"), "reviewer identity")
    _text(reviewer.get("provenance_note"), "reviewer provenance note")
    blockers = []
    task_fit = _judgment(review.get("task_fit"), "whole-report task fit")
    if task_fit == "not-applicable":
        raise CitationContractError("semantic whole-report task fit always applies")
    if task_fit in {"concern", "unknown"}:
        blockers.append("whole-report task fit")
    method = review.get("method_review")
    if not isinstance(method, dict) or set(method) != set(METHOD_DIMENSIONS):
        raise CitationContractError("semantic method_review must address every versioned dimension")
    for dimension in METHOD_DIMENSIONS:
        if _judgment(method[dimension], dimension) in {"concern", "unknown"}:
            blockers.append(dimension)
    units = _records(review.get("units"), "unit reviews")
    if [item.get("unit_id") for item in units] != [item["unit_id"] for item in inventory["units"]]:
        raise CitationContractError("semantic unit reviews dropped, duplicated or reordered inventory units")
    by_pair = {pair["pair_id"]: pair for pair in pairs_payload["pairs"]}
    seen_assertions = set()
    assertions_count = 0
    for unit, recorded in zip(inventory["units"], units, strict=True):
        _text(recorded.get("atomization_reason"), "unit atomization/classification reason")
        assertions = _records(recorded.get("assertions"), "assertions")
        nonassertive = _records(recorded.get("nonassertive_spans"), "nonassertive spans")
        spans = []
        for segment in assertions + nonassertive:
            start, end = segment.get("start"), segment.get("end")
            if (type(start) is not int or type(end) is not int or
                    not unit["start"] <= start < end <= unit["end"] or
                    segment.get("text") != report_text[start:end]):
                raise CitationContractError("semantic assertion/classification must be an exact report span")
            spans.append((start, end))
        spans.sort()
        cursor = unit["start"]
        for start, end in spans:
            if start < cursor or report_text[cursor:start].strip():
                raise CitationContractError("semantic spans overlap/duplicate or drop unit text")
            cursor = end
        if report_text[cursor:unit["end"]].strip():
            raise CitationContractError("semantic spans drop uncovered unit text")
        for segment in nonassertive:
            _text(segment.get("reason"), "nonassertive classification reason")
        for assertion in assertions:
            assertions_count += 1
            identity = assertion_id(revision, unit["unit_id"], assertion["start"], assertion["end"], assertion["text"])
            if assertion.get("assertion_id") != identity or identity in seen_assertions:
                raise CitationContractError("semantic assertion identity is stale or duplicated")
            seen_assertions.add(identity)
            kind, disposition = assertion.get("kind"), assertion.get("disposition")
            presentation = assertion.get("presentation")
            if (not isinstance(kind, str) or kind not in _PRESENTATIONS or
                    not isinstance(presentation, str) or presentation not in _PRESENTATIONS[kind] or
                    not isinstance(disposition, str) or disposition not in _DISPOSITIONS or
                    type(assertion.get("material")) is not bool):
                raise CitationContractError("semantic assertion requires explicit kind, presentation, materiality and disposition")
            for field in ("reasoning", "task_fit", "scope", "method_scope"):
                _text(assertion.get(field), f"assertion {field}")
            if assertion["material"] and disposition != "supported":
                blockers.append(identity)
            checks = assertion.get("method_checks")
            if not isinstance(checks, dict) or not set(checks) <= set(METHOD_DIMENSIONS):
                raise CitationContractError("semantic assertion method_checks contain unknown dimensions")
            for dimension, check in checks.items():
                if (_judgment(check, f"assertion {dimension}") in {"concern", "unknown"}
                        and assertion["material"]):
                    blockers.append(identity)
            evidence = _records(assertion.get("evidence"), "assertion evidence")
            seen_evidence = set()
            for passage in evidence:
                pair = by_pair.get(_text(passage.get("pair_id"), "evidence pair_id"))
                if pair is None or pair["pair_id"] not in unit["context"]["pair_ids"] or pair["note_id"] is None:
                    raise CitationContractError("semantic evidence is not bound to a local report citation")
                note_id = pair["note_id"]
                snapshot, body = sources[note_id]
                if (passage.get("note_id") != note_id or passage.get("source_revision") != snapshot["revision"]
                        or pair.get("source_input") != snapshot):
                    raise CitationContractError("semantic evidence source/citation revision is stale or misbound")
                excerpt = _text(passage.get("source_excerpt"), "assertion source excerpt")
                if snapshot["body_status"] != "available" or body is None or excerpt not in body:
                    raise CitationContractError("semantic evidence must be a literal current source-body passage")
                _text(passage.get("reasoning"), "assertion-specific passage reasoning")
                evidence_identity = (pair["pair_id"], excerpt)
                if evidence_identity in seen_evidence:
                    raise CitationContractError("duplicate semantic evidence passage")
                seen_evidence.add(evidence_identity)
            if kind == "empirical" and disposition in {"supported", "partially-supported"} and not evidence:
                raise CitationContractError("semantic empirical assertion requires cited source-body evidence")
            if kind == "derived":
                derivation = assertion.get("derivation")
                if not isinstance(derivation, dict) or type(derivation.get("source_dependent")) is not bool:
                    raise CitationContractError("semantic derivation requires explicit premise dependence")
                _text(derivation.get("premises"), "derivation premises")
                _text(derivation.get("calculation"), "derivation calculation")
                if derivation["source_dependent"] and not evidence:
                    raise CitationContractError("semantic source-dependent derivation requires cited premises")
            if kind in {"proposal", "design-parameter", "capture-gap"}:
                _text(assertion.get("nonempirical_basis"), "bounded nonempirical basis")
    if blockers:
        raise CitationContractError(f"semantic review has {len(set(blockers))} blocking material/task/method judgment(s)")
    return {"units_reviewed": len(units), "assertions_reviewed": assertions_count,
            "judgment_status": "recorded-review-not-truth-proof"}
