"""Pure validation of recorded corpus qualification and atomic evidence counts.

The caller supplies freshly collected contained bodies and already validated
whole-report assertions. Identity hints prevent deterministic mirror inflation;
originality, relevance, adequacy and paraphrase identity remain human/model
judgments. No database, filesystem, provider or model work occurs here.
"""

from __future__ import annotations

import re
import unicodedata

from hyperresearch.core.citation_contracts import CitationContractError

_ORIGINAL = {"original-full", "original-excerpt"}
_CAPTURES = _ORIGINAL | {"original-abstract", "metadata-only", "secondary", "unknown"}
_SCOPES = {"original-document", "independent-measurement", "bounded-abstract", "secondary-attribution"}


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CitationContractError(f"corpus {field} must be a nonempty string")
    return value


def _records(value: object, field: str) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise CitationContractError(f"corpus {field} must be an array of objects")
    return value


def _normalized(text: str, citations: set[str]) -> str:
    # Whole-report assertion spans retain citation markers. Those occurrences
    # cannot distinguish the same proposition, but meaningful numbers remain.
    text = re.sub(r"(?<!\[)\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\])",
                  lambda match: " " if all(f"[{number}]" in citations for number in re.split(r"\s*,\s*", match[1])) else match[0], text)
    for citation in citations:
        text = text.replace(citation, " ")
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _groups(ids: list[str], identities: dict[str, list[tuple[str, str]]]) -> dict[str, str]:
    """Connected components retain transitive work/mirror/hint ties."""
    parent = {identity: identity for identity in ids}

    def root(identity):
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity

    seen = {}
    for identity in ids:
        for key in identities[identity]:
            if key in seen:
                parent[root(identity)] = root(seen[key])
            else:
                seen[key] = identity
    return {identity: root(identity) for identity in ids}


def validate_corpus_review(pairs_payload: dict, semantic_review: dict, review: object,
                           sources: dict[str, tuple[dict, str | None]]) -> dict:
    """Enforce exact current qualification, scoped support and separate floors."""
    corpus = pairs_payload.get("corpus_inputs")
    if not isinstance(corpus, dict) or type(corpus.get("schema_version")) is not int or corpus["schema_version"] != 1:
        raise CitationContractError("corpus_inputs requires version 1")
    requirements = corpus.get("requirements")
    if (not isinstance(requirements, dict) or not isinstance(requirements.get("gear"), str)
            or any(type(requirements.get(key)) is not int or requirements[key] < 0 for key in ("source_min", "claims_min"))):
        raise CitationContractError("corpus evidence requirements require a gear and nonnegative integer minima")
    if not isinstance(review, dict) or type(review.get("schema_version")) is not int or review["schema_version"] != 1:
        raise CitationContractError("corpus_review requires version 1 recorded qualification")
    if (review.get("report_revision") != pairs_payload["report_revision"]
            or review.get("corpus_input_digest") != corpus.get("input_digest")):
        raise CitationContractError("corpus review report/input binding is stale")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict):
        raise CitationContractError("corpus reviewer provenance is required")
    _text(reviewer.get("identity"), "reviewer identity")
    _text(reviewer.get("provenance_note"), "reviewer provenance note")
    members = _records(corpus.get("members"), "members")
    qualifications = _records(review.get("qualifications"), "qualifications")
    ids = [_text(member.get("note_id"), "member note_id") for member in members]
    if len(set(ids)) != len(ids) or [item.get("note_id") for item in qualifications] != ids:
        raise CitationContractError("corpus qualifications must cover each current member exactly once in input order")
    by_note, identities, qualifying = {}, {}, set()
    for member, recorded in zip(members, qualifications, strict=True):
        note_id = member["note_id"]
        if note_id not in sources or member.get("source_input") != sources[note_id][0]:
            raise CitationContractError("corpus source snapshot differs from the current contained source")
        snapshot, body = sources[note_id]
        if recorded.get("source_revision") != snapshot["revision"]:
            raise CitationContractError("corpus qualification source revision is stale")
        work = _text(recorded.get("work_id"), "reviewed work identity")
        mirror = _text(recorded.get("mirror_group"), "reviewed mirror group")
        _text(recorded.get("reason"), "qualification reason")
        capture = recorded.get("capture_kind")
        if (capture not in _CAPTURES or recorded.get("originality") not in {"original", "secondary", "unknown"}
                or recorded.get("relevance") not in {"relevant", "not-relevant", "unknown"}
                or recorded.get("substance") not in {"adequate", "inadequate", "unknown"}):
            raise CitationContractError("corpus qualification requires explicit capture, originality, relevance and substance judgments")
        independence = recorded.get("independence")
        if not isinstance(independence, dict) or independence.get("outcome") not in {"independent", "first-party", "derivative", "unknown"}:
            raise CitationContractError("corpus qualification requires explicit independence scope")
        _text(independence.get("reason"), "independence reason")
        _text(independence.get("scope"), "independence scope")
        available = snapshot["body_status"] == "available" and body is not None
        excerpt = recorded.get("source_excerpt")
        if available:
            if _text(excerpt, "qualification body passage") not in body:
                raise CitationContractError("corpus qualification passage is absent from current parsed body")
        elif excerpt is not None:
            raise CitationContractError("corpus unavailable/empty body cannot supply a passage")
        adequate = available and recorded["relevance"] == "relevant" and recorded["substance"] == "adequate"
        original = adequate and capture in _ORIGINAL and recorded["originality"] == "original" and not member.get("is_final_report")
        if original:
            qualifying.add(note_id)
        by_note[note_id] = recorded, adequate and not member.get("is_final_report")
        hints = member.get("identity_hints")
        if not isinstance(hints, dict):
            raise CitationContractError("corpus member identity hints are required")
        if any(value is not None and not isinstance(value, str) for value in hints.values()):
            raise CitationContractError("corpus identity hints must be strings or null")
        identities[note_id] = [("work", work), ("mirror", mirror)] + [
            (key, value) for key in ("doi", "canonical_url", "body_digest") if (value := hints.get(key))
        ]
    groups = _groups(ids, identities)
    unique = {groups[note_id] for note_id in qualifying}
    independent = {group for group in unique if all(
        by_note[note_id][0]["independence"]["outcome"] == "independent"
        for note_id in ids if groups[note_id] == group)}
    assertions = [assertion for unit in semantic_review["units"] for assertion in unit["assertions"]
                  if assertion["disposition"] == "supported" and (assertion["kind"] == "empirical"
                      or (assertion["kind"] == "derived" and assertion.get("derivation", {}).get("source_dependent") is True))
                  and assertion.get("evidence")]
    propositions = _records(review.get("propositions"), "propositions")
    assertion_ids = [assertion["assertion_id"] for assertion in assertions]
    if [item.get("assertion_id") for item in propositions] != assertion_ids or len(set(assertion_ids)) != len(assertion_ids):
        raise CitationContractError("corpus proposition mapping must cover current supported body-evidenced atomic assertion identities exactly once")
    supported, proposition_identities = [], {}
    citations = {pair["citation"] for pair in pairs_payload["pairs"] if isinstance(pair.get("citation"), str) and pair["citation"]}
    for assertion, proposition in zip(assertions, propositions, strict=True):
        identity = assertion["assertion_id"]
        key = _text(proposition.get("proposition_key"), "proposition key")
        scope = proposition.get("evidence_scope")
        if scope not in _SCOPES:
            raise CitationContractError("corpus proposition requires explicit eligible evidence scope")
        _text(proposition.get("reason"), "proposition support/identity reason")
        eligible = False
        for passage in assertion["evidence"]:
            note_id = passage["note_id"]
            if note_id not in by_note:
                raise CitationContractError("corpus assertion source is outside the current corpus")
            qualification, adequate = by_note[note_id]
            snapshot, body = sources[note_id]
            if (passage.get("source_revision") != snapshot["revision"] or body is None
                    or not isinstance(passage.get("source_excerpt"), str) or not passage["source_excerpt"].strip()
                    or passage["source_excerpt"] not in body):
                raise CitationContractError("corpus assertion passage/revision is stale or absent")
            capture = qualification["capture_kind"]
            original = qualification["originality"] == "original" and capture in _ORIGINAL
            eligible |= adequate and (
                (scope == "original-document" and original)
                or (scope == "independent-measurement" and original and qualification["independence"]["outcome"] == "independent")
                or (scope == "bounded-abstract" and capture == "original-abstract" and qualification["originality"] == "original")
                or (scope == "secondary-attribution" and capture == "secondary" and qualification["originality"] == "secondary"))
        if not eligible and assertion["material"]:
            raise CitationContractError("material assertion lacks eligible source support for its recorded evidence scope")
        if eligible:
            supported.append(identity)
            proposition_identities[identity] = [("key", key), ("text", _normalized(assertion["text"], citations))]
    atomic_count = len(set(_groups(supported, proposition_identities).values()))
    rows = _records(corpus.get("raw_claim_rows"), "raw claim rows")
    raw_claims = {(_text(row.get("note_id"), "claim note_id"), _text(row.get("claim_hash"), "claim hash")) for row in rows}
    if any(note_id not in by_note for note_id, _ in raw_claims):
        raise CitationContractError("raw claim rows must belong to corpus note identities")
    if len(unique) < requirements["source_min"] or atomic_count < requirements["claims_min"]:
        raise CitationContractError(f"qualified evidence minimum not met: {len(unique)}/{requirements['source_min']} unique original works; "
                                    f"{atomic_count}/{requirements['claims_min']} supported atomic units")
    return {"raw_notes": len(members), "citation_pairs": len(pairs_payload["pairs"]), "raw_db_claims": len(raw_claims),
            "qualified_unique_works": len(unique), "independent_works": len(independent), "supported_atomic_units": atomic_count,
            "requirements": requirements, "judgment_status": "recorded-review-not-truth-proof"}
