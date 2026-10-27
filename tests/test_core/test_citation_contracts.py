"""Synthetic, read-only citation artifact contracts; no provider calls."""

from __future__ import annotations

import copy

import pytest

from hyperresearch.core.citation_contracts import (
    CitationContractError,
    bind_findings,
    finding_id,
    merge_findings_shards,
    pair_id,
    parse_findings,
    parse_pairs,
    report_revision,
    source_input,
    validate_coverage,
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


@pytest.mark.parametrize("mutation", ["no-records", "unreviewed", "unresolved", "failed-review", "missing-evidence"])
def test_major_findings_require_successful_reviewed_resolution(citation_artifacts, mutation):
    _, findings, log, current = citation_artifacts
    findings["findings"][0]["severity"] = "major"
    if mutation == "no-records":
        log["resolutions"] = []
    elif mutation == "unreviewed":
        log.update({"resolutions": [], "reviewed_report_revision": None})
    elif mutation == "unresolved":
        log["resolutions"][0].update({"status": "unresolved", "review_verdict": "unresolved"})
    elif mutation == "failed-review":
        log["resolutions"][0]["review_verdict"] = "unresolved"
    else:
        log["resolutions"][0]["evidence"] = ""
    with pytest.raises(CitationContractError):
        validate_resolutions(parse_findings(findings), log, current)


def test_minor_only_application_stub_remains_diagnostic(citation_artifacts):
    _, findings, log, current = citation_artifacts
    findings["findings"][0]["severity"] = "minor"
    log.update({"resolutions": [], "reviewed_report_revision": None})
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


@pytest.fixture
def coverage_artifacts(seeded_vault):
    """Recorded-work fixture only; no claim that these records prove entailment."""
    from hyperresearch.core.citecheck import write_pairs_file

    report = seeded_vault.notes_dir / "coverage.md"
    report.write_text("\n".join(
        f"{prefix} discusses concurrent I/O [[python-async-patterns]]."
        for prefix in ("Introduction", "Context", "Background", "Overview", "Discussion")
    ), encoding="utf-8")
    pairs = write_pairs_file(seeded_vault, "coverage", report)
    findings = {
        "schema_version": 1, "report_revision": pairs["report_revision"],
        "selected_pair_ids": pairs["selected_pair_ids"].copy(), "findings": [],
        "results": [{
            "pair_id": pair["pair_id"], "verdict": "supported",
            "source_revision": pair["source_input"]["revision"],
            "source_excerpt": "Python's async/await syntax enables concurrent I/O.",
            "evidence": "Synthetic recorded-work fixture, not a model truth proof.",
        } for pair in pairs["sampled_for_llm"]],
    }
    return seeded_vault, pairs, findings


def _negative(pair, verdict="unsupported", severity="major"):
    return {"pair_id": pair["pair_id"], "finding_id": pair["finding_id"],
            "sentence": pair["sentence"], "cited_note_id": pair["note_id"],
            "correct_note_id": None, "severity": severity, "verdict": verdict,
            "evidence": "The cited body does not support this claim.",
            "suggested_fix": "Remove or narrow the claim."}


def test_sampled_selected_work_is_explicit_and_read_only(coverage_artifacts):
    vault, pairs, findings = coverage_artifacts
    before = copy.deepcopy((pairs, findings))
    coverage = validate_coverage(pairs, findings, vault)
    assert coverage == {"coverage_mode": "sampled", "selected": 3, "reviewed": 3,
                        "unreviewed": 2, "dangling": 0}
    assert (pairs, findings) == before


@pytest.mark.parametrize("mutation", [
    "missing-results", "duplicate", "unknown", "dropped", "stale-report", "stale-source",
    "missing-evidence", "frontmatter-excerpt", "empty-excerpt", "wrong-selected", "hidden-remainder",
    "false-comprehensive", "bad-rate", "bad-method", "changed-routing", "missing-negative",
    "unmatched-finding", "wrong-negative", "supported-finding", "extra-result", "sampled-drift",
    "false-summary", "missing-dangling-array",
])
def test_selected_coverage_rejects_invalid_records(coverage_artifacts, mutation):
    vault, pairs, findings = coverage_artifacts
    result = findings["results"][0]
    pair = next(p for p in pairs["pairs"] if p["pair_id"] == result["pair_id"])
    if mutation == "missing-results":
        del findings["results"]
    elif mutation == "duplicate":
        findings["results"].append(copy.deepcopy(result))
    elif mutation == "unknown":
        result["pair_id"] = "pair-v1:" + "0" * 64
    elif mutation == "dropped":
        findings["results"].pop()
    elif mutation == "stale-report":
        findings["report_revision"] = report_revision(b"Other report")
    elif mutation == "stale-source":
        result["source_revision"] = report_revision(b"Other source")
    elif mutation == "missing-evidence":
        result["evidence"] = ""
    elif mutation == "frontmatter-excerpt":
        result["source_excerpt"] = "Guide to async/await in Python"
    elif mutation == "empty-excerpt":
        result["source_excerpt"] = " "
    elif mutation == "wrong-selected":
        findings["selected_pair_ids"].pop()
    elif mutation == "hidden-remainder":
        pairs["unreviewed_pair_ids"] = []
    elif mutation == "false-comprehensive":
        pairs["coverage_mode"] = "comprehensive"
    elif mutation == "bad-rate":
        pairs["sampling"]["weak_sample_rate"] = float("nan")
    elif mutation == "bad-method":
        pairs["sampling"]["method"] = "trust-me"
    elif mutation == "changed-routing":
        pairs["pairs"][0]["strong"] = True
    elif mutation == "missing-negative":
        result["verdict"] = "unsupported"
    elif mutation == "unmatched-finding":
        findings["findings"] = [_negative(pairs["pairs"][0])]
    elif mutation == "wrong-negative":
        result["verdict"] = "unsupported"
        findings["findings"] = [_negative(pair, "wrong-source")]
    elif mutation == "supported-finding":
        findings["findings"] = [_negative(pair)]
    elif mutation == "extra-result":
        extra = copy.deepcopy(result)
        extra["pair_id"] = pairs["unreviewed_pair_ids"][0]
        findings["results"].append(extra)
    elif mutation == "sampled-drift":
        pairs["sampled_for_llm"] = []
    elif mutation == "false-summary":
        pairs["summary"]["unreviewed"] = 0
    elif mutation == "missing-dangling-array":
        del pairs["dangling"]
    with pytest.raises(CitationContractError):
        validate_coverage(pairs, findings, vault)


def test_source_body_revision_and_current_db_path_are_bound(coverage_artifacts):
    vault, pairs, findings = coverage_artifacts
    path = vault.root / pairs["pairs"][0]["source_input"]["path"]
    path.write_bytes(path.read_bytes() + b"\nChanged source.\n")
    with pytest.raises(CitationContractError, match="source_input is stale"):
        validate_coverage(pairs, findings, vault)


@pytest.mark.parametrize("verdict", ["supported", "partially-supported"])
def test_positive_passages_cannot_come_from_frontmatter(coverage_artifacts, verdict):
    vault, pairs, findings = coverage_artifacts
    result = findings["results"][0]
    result["verdict"] = verdict
    result["source_excerpt"] = "Guide to async/await in Python"  # summary metadata only
    if verdict == "partially-supported":
        pair = next(p for p in pairs["pairs"] if p["pair_id"] == result["pair_id"])
        findings["findings"] = [_negative(pair, verdict)]
    with pytest.raises(CitationContractError, match="literal source-body"):
        validate_coverage(pairs, findings, vault)


@pytest.mark.parametrize("raw", [
    b"---\nmetadata-only claim\n---\n",
    b"---\n- metadata-only claim\n---\n",
    b"---\nclaim: metadata-only claim\n",
    b"---\nclaim: [metadata-only claim\n---\n",
    b"---\nclaim: metadata-only claim\n---metadata-only claim\n",
    "---\u00a0\n- metadata-only claim\n---\n".encode(),
    b"---\v\n- metadata-only claim\n---\n",
    "---\u2003\nmetadata-only claim\n---\n".encode(),
    b"---\f\nclaim: metadata-only claim\n",
])
@pytest.mark.parametrize("verdict", ["supported", "partially-supported"])
def test_invalid_frontmatter_cannot_become_positive_body_evidence(seeded_vault, raw, verdict):
    from hyperresearch.core.citecheck import write_pairs_file

    vault = seeded_vault
    row = vault.db.execute("SELECT path FROM notes WHERE id = 'python-async-patterns'").fetchone()
    (vault.root / row["path"]).write_bytes(raw)
    report = vault.notes_dir / "metadata-coverage.md"
    report.write_text("The source makes a bounded claim [[python-async-patterns]].", encoding="utf-8")
    pairs = write_pairs_file(vault, "metadata-coverage", report, coverage_mode="comprehensive")
    pair = pairs["pairs"][0]
    result = {"pair_id": pair["pair_id"], "verdict": verdict,
              "source_revision": pair["source_input"]["revision"],
              "source_excerpt": "metadata-only claim", "evidence": "Attempted metadata-only positive."}
    findings = {"schema_version": 1, "report_revision": pairs["report_revision"],
                "selected_pair_ids": pairs["selected_pair_ids"], "results": [result],
                "findings": [] if verdict == "supported" else [_negative(pair, verdict)]}
    with pytest.raises(CitationContractError, match="cannot establish support"):
        validate_coverage(pairs, findings, vault)
    assert pair["source_input"]["revision"] == report_revision(raw)
    assert pair["source_input"]["body_status"] in {"empty", "unavailable"}
    # A safely read but invalid metadata envelope still permits an honest
    # negative result, followed by claim removal and ordinary resolution.
    result.update(verdict="unsupported", source_excerpt=None, evidence="No parsed source body is available.")
    findings["findings"] = [_negative(pair)]
    assert validate_coverage(pairs, findings, vault)["reviewed"] == 1


@pytest.mark.parametrize(("claim", "verdict"), [
    ("The source states 255 items", "unsupported"),
    ("The source states +255 items", "unsupported"),
    ("The source states \u2212255 items", "unsupported"),
    ("The source discusses concurrent I/O", "wrong-source"),
])
@pytest.mark.parametrize("severity", ["minor", "major"])
def test_declared_critical_result_policy_cannot_be_downgraded(seeded_vault, claim, verdict, severity):
    from hyperresearch.core.citecheck import write_pairs_file

    vault = seeded_vault
    report = vault.notes_dir / "severity.md"
    report.write_text(f"{claim} [[python-async-patterns]].", encoding="utf-8")
    pairs = write_pairs_file(vault, "severity", report, coverage_mode="comprehensive")
    pair = pairs["pairs"][0]
    findings = {"schema_version": 1, "report_revision": pairs["report_revision"],
                "selected_pair_ids": pairs["selected_pair_ids"], "findings": [_negative(pair, verdict, severity)],
                "results": [{"pair_id": pair["pair_id"], "verdict": verdict,
                             "source_revision": pair["source_input"]["revision"],
                             "source_excerpt": "Python's async/await syntax enables concurrent I/O.",
                             "evidence": "Synthetic negative result for structural severity validation."}]}
    with pytest.raises(CitationContractError, match="critical"):
        validate_coverage(pairs, findings, vault)
    findings["findings"][0]["severity"] = "critical"
    assert validate_coverage(pairs, findings, vault)["reviewed"] == 1


@pytest.mark.parametrize(("claim", "verdict"), [
    ("The source discusses concurrent I/O", "unsupported"),
    ("The source discusses an increase in concurrent I/O", "unsupported"),
    ("The source states 255 items", "partially-supported"),
])
def test_structural_severity_policy_preserves_nonnumeric_and_partial_findings(seeded_vault, claim, verdict):
    from hyperresearch.core.citecheck import write_pairs_file

    vault = seeded_vault
    report = vault.notes_dir / "noncritical.md"
    report.write_text(f"{claim} [[python-async-patterns]].", encoding="utf-8")
    pairs = write_pairs_file(vault, "noncritical", report, coverage_mode="comprehensive")
    pair = pairs["pairs"][0]
    findings = {"schema_version": 1, "report_revision": pairs["report_revision"],
                "selected_pair_ids": pairs["selected_pair_ids"], "findings": [_negative(pair, verdict, "major")],
                "results": [{"pair_id": pair["pair_id"], "verdict": verdict,
                             "source_revision": pair["source_input"]["revision"],
                             "source_excerpt": "Python's async/await syntax enables concurrent I/O.",
                             "evidence": "Recorded noncritical result with a literal source-body passage."}]}
    assert validate_coverage(pairs, findings, vault)["reviewed"] == 1


def test_comprehensive_selection_is_not_automatically_reviewed(seeded_vault):
    from hyperresearch.core.citecheck import write_pairs_file

    report = seeded_vault.notes_dir / "comprehensive.md"
    report.write_text("Python supports concurrent I/O [[python-async-patterns]].", encoding="utf-8")
    pairs = write_pairs_file(seeded_vault, "comprehensive", report, coverage_mode="comprehensive")
    assert len(pairs["selected_pair_ids"]) == 1 and pairs["unreviewed_pair_ids"] == []
    findings = {"schema_version": 1, "report_revision": pairs["report_revision"],
                "selected_pair_ids": pairs["selected_pair_ids"], "results": [], "findings": []}
    with pytest.raises(CitationContractError, match="dropped selected"):
        validate_coverage(pairs, findings, seeded_vault)


@pytest.mark.parametrize("verdict", ["partially-supported", "unsupported", "wrong-source"])
def test_each_negative_result_has_exact_matching_finding(coverage_artifacts, verdict):
    vault, pairs, findings = coverage_artifacts
    result = findings["results"][0]
    result["verdict"] = verdict
    pair = next(p for p in pairs["pairs"] if p["pair_id"] == result["pair_id"])
    findings["findings"] = [_negative(pair, verdict, "critical" if verdict == "wrong-source" else "major")]
    assert validate_coverage(pairs, findings, vault)["reviewed"] == 3


@pytest.mark.parametrize("path_kind", ["outside-root", "outside-notes", "symlink", "different-db-path"])
def test_source_paths_cannot_escape_or_override_current_db(coverage_artifacts, path_kind, tmp_path):
    vault, pairs, findings = coverage_artifacts
    original = vault.root / pairs["pairs"][0]["source_input"]["path"]
    if path_kind == "outside-root":
        path = tmp_path / "outside.md"
        path.write_bytes(original.read_bytes())
        relative = str(path)
    elif path_kind == "outside-notes":
        path = vault.root / "research" / "temp" / "outside.md"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(original.read_bytes())
        relative = path.relative_to(vault.root).as_posix()
    else:
        path = vault.notes_dir / "replacement.md"
        if path_kind == "symlink":
            try:
                path.symlink_to(original)
            except OSError:
                pytest.skip("OS does not permit symlink creation")
        else:
            path.write_bytes(original.read_bytes())
        relative = path.relative_to(vault.root).as_posix()
    vault.db.execute("UPDATE notes SET path = ? WHERE id = ?", (relative, "python-async-patterns"))
    with pytest.raises(CitationContractError):
        validate_coverage(pairs, findings, vault)


@pytest.mark.parametrize("body_kind", ["empty", "missing", "unreadable-encoding"])
def test_safe_unavailable_bodies_can_record_negatives_only(seeded_vault, body_kind):
    from hyperresearch.core.citecheck import write_pairs_file

    vault = seeded_vault
    row = vault.db.execute("SELECT path FROM notes WHERE id = 'python-async-patterns'").fetchone()
    path = vault.root / row["path"]
    if body_kind == "empty":
        path.write_text("---\ntitle: Empty\n---\n", encoding="utf-8")
    elif body_kind == "missing":
        # Relocate within the pytest vault; preserve a recoverable source fixture.
        path.rename(path.with_suffix(".saved"))
    else:
        path.write_bytes(b"\xff")
    report = vault.notes_dir / "negative.md"
    report.write_text("The source states 255 items [[python-async-patterns]].", encoding="utf-8")
    pairs = write_pairs_file(vault, "negative", report, coverage_mode="comprehensive")
    pair = pairs["pairs"][0]
    result = {"pair_id": pair["pair_id"], "verdict": "unsupported", "source_excerpt": None,
              "source_revision": pair["source_input"]["revision"], "evidence": "No readable source body exists."}
    findings = {"schema_version": 1, "report_revision": pairs["report_revision"],
                "selected_pair_ids": pairs["selected_pair_ids"], "results": [result],
                "findings": [_negative(pair, severity="critical")]}
    assert validate_coverage(pairs, findings, vault)["reviewed"] == 1
    result["verdict"] = "supported"
    findings["findings"] = []
    with pytest.raises(CitationContractError, match="cannot establish support"):
        validate_coverage(pairs, findings, vault)
    result["verdict"] = "unsupported"
    findings["findings"] = [_negative(pair, severity="critical")]
    path.write_text("The source now has a body.", encoding="utf-8")
    with pytest.raises(CitationContractError, match="stale"):
        validate_coverage(pairs, findings, vault)


def test_shards_preserve_supported_results_ids_and_evidence(coverage_artifacts):
    vault, pairs, findings = coverage_artifacts
    shards = []
    for result in reversed(findings["results"]):
        shard = copy.deepcopy(findings)
        shard["selected_pair_ids"] = [result["pair_id"]]
        shard["results"] = [result]
        shards.append(shard)
    merged = merge_findings_shards(pairs, shards, vault)
    assert merged["selected_pair_ids"] == findings["selected_pair_ids"]
    assert merged["results"] == list(reversed(findings["results"]))
    assert len(merged["results"]) == 3
    with pytest.raises(CitationContractError, match="duplicate"):
        merge_findings_shards(pairs, [*shards, shards[0]], vault)
    with pytest.raises(CitationContractError):
        merge_findings_shards(pairs, shards[:-1], vault)


@pytest.mark.parametrize("title,body", [
    ("Original Introduction", "This introduction defines asynchronous I/O as concurrent input and output."),
    ("Vendor Product", "Our widget imports one CSV file at a time."),
])
def test_bounded_original_body_passages_need_no_full_paper_rule(seeded_vault, title, body):
    from hyperresearch.core.citecheck import write_pairs_file
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    path = write_note(seeded_vault.notes_dir, title, body=body)
    execute_sync(seeded_vault, compute_sync_plan(seeded_vault))
    note_id = path.stem
    report = seeded_vault.notes_dir / "original.md"
    report.write_text(f"{body} [[{note_id}]]", encoding="utf-8")
    pairs = write_pairs_file(seeded_vault, "original", report, coverage_mode="comprehensive")
    pair = pairs["pairs"][0]
    findings = {"schema_version": 1, "report_revision": pairs["report_revision"],
                "selected_pair_ids": pairs["selected_pair_ids"], "findings": [], "results": [{
                    "pair_id": pair["pair_id"], "verdict": "supported", "source_excerpt": body,
                    "source_revision": pair["source_input"]["revision"],
                    "evidence": "The original source body states this bounded claim.",
                }]}
    assert validate_coverage(pairs, findings, seeded_vault)["unreviewed"] == 0


def test_source_snapshots_cache_each_unique_note(coverage_artifacts, monkeypatch):
    vault, pairs, findings = coverage_artifacts
    from pathlib import Path

    original = Path.read_bytes
    reads = []

    def read_bytes(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    validate_coverage(pairs, findings, vault)
    assert len(reads) == 1
    snapshot, body = source_input(vault, "python-async-patterns")
    assert snapshot["body_status"] == "available" and body
