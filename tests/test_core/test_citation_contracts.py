"""Synthetic, read-only citation artifact contracts; no provider calls."""

from __future__ import annotations

import copy

import pytest

from hyperresearch.core.citation_contracts import (
    CitationContractError,
    bind_findings,
    finding_id,
    pair_id,
    parse_findings,
    parse_pairs,
    report_revision,
    validate_resolutions,
)


@pytest.fixture
def citation_artifacts():
    revision = report_revision(b"Original report.\r\n")
    pair = {"pair_index": 0, "sentence": "Original report.", "note_id": "source"}
    pair["pair_id"] = pair_id(revision, 0, pair["sentence"], pair["note_id"])
    pair["finding_id"] = finding_id(pair["pair_id"])
    pairs = {"schema_version": 1, "report_revision": revision, "pairs": [pair]}
    finding = {
        "finding_id": pair["finding_id"], "pair_id": pair["pair_id"],
        "severity": "critical", "verdict": "unsupported", "sentence": pair["sentence"],
        "cited_note_id": pair["note_id"], "correct_note_id": None,
        "evidence": "The source lacks this claim.", "suggested_fix": "Remove the claim.",
    }
    findings = {"schema_version": 1, "report_revision": revision, "findings": [finding]}
    reviewed = report_revision(b"Patched report.\n")
    log = {
        "schema_version": 1, "findings_report_revision": revision,
        "reviewed_report_revision": reviewed,
        "resolutions": [{
            "finding_id": finding["finding_id"], "status": "resolved",
            "review_verdict": "claim-removed", "evidence": "Reread patched report; claim removed.",
        }],
    }
    return pairs, findings, log, reviewed


def test_exact_byte_revisions_and_occurrence_identities():
    revision = report_revision(b"Report.\n")
    assert revision != report_revision(b"Report.\r\n")
    assert revision != report_revision(b"\xef\xbb\xbfReport.\n")
    identity = pair_id(revision, 0, "Report.", "source")
    assert identity == pair_id(revision, 0, "Report.", "source")
    assert identity != pair_id(revision, 1, "Report.", "source")
    assert identity != pair_id(revision, 0, "Report.", None)
    assert identity != pair_id(report_revision(b"Changed."), 0, "Report.", "source")
    assert finding_id(identity).startswith("finding-v1:")


@pytest.mark.parametrize("payload", [[], {"findings": []}])
def test_explicit_empty_legacy_findings_are_read_only_diagnostics(payload):
    before = copy.deepcopy(payload)
    parsed = parse_findings(payload)
    assert parsed.legacy and parsed.findings == () and parsed.report_revision is None
    assert payload == before


def test_legacy_nonempty_is_parsed_but_cannot_prove_resolution(citation_artifacts):
    _, _, log, current = citation_artifacts
    legacy = parse_findings([{"severity": "critical", "verdict": "unsupported"}])
    assert legacy.legacy
    with pytest.raises(CitationContractError, match="legacy"):
        validate_resolutions(legacy, log, current)


@pytest.mark.parametrize("payload", [
    {}, None, "[]", 7, True, {"findings": None}, {"findings": {}}, [None], [[]],
    [{"severity": "critical"}], [{"verdict": "unsupported"}],
    [{"severity": ["critical"], "verdict": "unsupported"}],
    [{"severity": "critical", "verdict": {}}],
    [{"severity": "major", "verdict": "supported"}],
    [{"severity": "major", "verdict": "unsupported", "sentence": 3}],
    [{"severity": "major", "verdict": "unsupported", "cited_note_id": []}],
    {"schema_version": True, "findings": []}, {"schema_version": 2, "findings": []},
    {"schema_version": 1, "findings": []},
])
def test_malformed_findings_fail_with_contract_error(payload):
    with pytest.raises(CitationContractError):
        parse_findings(payload)


def test_valid_original_binding_and_postpatch_review(citation_artifacts):
    pairs, findings, log, current = citation_artifacts
    original = copy.deepcopy((pairs, findings, log))
    parsed = parse_findings(findings)
    bind_findings(parsed, parse_pairs(pairs))
    assert current != parsed.report_revision  # patching legitimately changes the report
    validate_resolutions(parsed, log, current)
    assert (pairs, findings, log) == original


def test_zero_findings_binds_original_revision_without_claiming_work(citation_artifacts):
    pairs, findings, _, _ = citation_artifacts
    findings["findings"] = []
    bind_findings(parse_findings(findings), parse_pairs(pairs))
    findings["report_revision"] = report_revision(b"Different original report")
    with pytest.raises(CitationContractError, match="original pairs revision"):
        bind_findings(parse_findings(findings), parse_pairs(pairs))


@pytest.mark.parametrize(("field", "value"), [
    ("sentence", "An unrelated sentence."), ("cited_note_id", "other-source"),
    ("pair_id", "pair-v1:" + "0" * 64),
])
def test_unrelated_findings_do_not_bind(citation_artifacts, field, value):
    pairs, findings, _, _ = citation_artifacts
    item = findings["findings"][0]
    item[field] = value
    if field == "pair_id":
        item["finding_id"] = finding_id(value)
    with pytest.raises(CitationContractError):
        bind_findings(parse_findings(findings), parse_pairs(pairs))


@pytest.mark.parametrize(("field", "value"), [
    ("severity", None), ("verdict", []), ("sentence", ""), ("evidence", {}),
    ("suggested_fix", None), ("cited_note_id", 1), ("correct_note_id", False),
    ("finding_id", "unrelated"), ("pair_id", "unrelated"),
])
def test_invalid_v1_finding_fields(citation_artifacts, field, value):
    _, findings, _, _ = citation_artifacts
    findings["findings"][0][field] = value
    with pytest.raises(CitationContractError):
        parse_findings(findings)


def test_duplicate_findings_and_original_pairs_fail(citation_artifacts):
    pairs, findings, _, _ = citation_artifacts
    findings["findings"] *= 2
    with pytest.raises(CitationContractError, match="duplicate"):
        parse_findings(findings)
    pairs["pairs"] *= 2
    with pytest.raises(CitationContractError, match="duplicate"):
        parse_pairs(pairs)


@pytest.mark.parametrize(("field", "value"), [
    ("pair_index", True), ("pair_index", -1), ("sentence", "Changed."),
    ("note_id", []), ("pair_id", "wrong"), ("finding_id", "wrong"),
])
def test_pairs_identity_must_match_original_content(citation_artifacts, field, value):
    pairs, _, _, _ = citation_artifacts
    pairs["pairs"][0][field] = value
    with pytest.raises(CitationContractError):
        parse_pairs(pairs)


@pytest.mark.parametrize("payload", [[], {}, {"schema_version": 1, "pairs": []}])
def test_malformed_pairs_manifest(payload):
    with pytest.raises(CitationContractError):
        parse_pairs(payload)


@pytest.mark.parametrize("mutation", [
    "empty-log", "missing-resolution", "duplicate", "unknown", "stale-findings",
    "stale-review", "applied-only", "unresolved", "failed-review", "missing-evidence",
    "wrong-record-type", "wrong-array-type", "bad-version",
])
def test_critical_resolution_rejects_missing_unrelated_or_unreviewed(citation_artifacts, mutation):
    _, findings, log, current = citation_artifacts
    if mutation == "empty-log":
        log = []
    elif mutation == "missing-resolution":
        log["resolutions"] = []
    elif mutation == "duplicate":
        log["resolutions"] *= 2
    elif mutation == "unknown":
        log["resolutions"][0]["finding_id"] = "finding-v1:" + "0" * 64
    elif mutation == "stale-findings":
        log["findings_report_revision"] = current
    elif mutation == "stale-review":
        log["reviewed_report_revision"] = findings["report_revision"]
    elif mutation == "applied-only":
        log["applied"] = [findings["findings"][0]["finding_id"]]
        del log["resolutions"]
    elif mutation == "unresolved":
        log["resolutions"][0]["status"] = "unresolved"
        log["resolutions"][0]["review_verdict"] = "unresolved"
    elif mutation == "failed-review":
        log["resolutions"][0]["review_verdict"] = "unresolved"
    elif mutation == "missing-evidence":
        log["resolutions"][0]["evidence"] = ""
    elif mutation == "wrong-record-type":
        log["resolutions"] = [None]
    elif mutation == "wrong-array-type":
        log["resolutions"] = {}
    elif mutation == "bad-version":
        log["schema_version"] = True
    with pytest.raises(CitationContractError):
        validate_resolutions(parse_findings(findings), log, current)


def test_known_noncritical_resolution_is_allowed(citation_artifacts):
    _, findings, log, current = citation_artifacts
    findings["findings"][0]["severity"] = "major"
    validate_resolutions(parse_findings(findings), log, current)


def test_every_critical_needs_its_own_review(citation_artifacts):
    pairs, findings, log, current = citation_artifacts
    second_pair = copy.deepcopy(pairs["pairs"][0])
    second_pair["pair_index"] = 1
    second_pair["pair_id"] = pair_id(pairs["report_revision"], 1, second_pair["sentence"], second_pair["note_id"])
    second_pair["finding_id"] = finding_id(second_pair["pair_id"])
    pairs["pairs"].append(second_pair)
    second_finding = copy.deepcopy(findings["findings"][0])
    second_finding.update(pair_id=second_pair["pair_id"], finding_id=second_pair["finding_id"])
    findings["findings"].append(second_finding)
    parsed = parse_findings(findings)
    bind_findings(parsed, parse_pairs(pairs))
    with pytest.raises(CitationContractError, match="1 critical"):
        validate_resolutions(parsed, log, current)
    second_resolution = copy.deepcopy(log["resolutions"][0])
    second_resolution["finding_id"] = second_finding["finding_id"]
    log["resolutions"].append(second_resolution)
    validate_resolutions(parsed, log, current)
