"""Phase-5 tests: cite-check, verification lints, independence, telemetry, verify."""

from __future__ import annotations

import json

import pytest

from hyperresearch.core.citecheck import (
    extract_pairs,
    parse_sources_section,
    sample_needs_llm,
    triage_pairs,
)
from hyperresearch.core.independence import canonical_url, compute_independence
from hyperresearch.core.runs import init_run, run_report_data, set_step, verify_run


@pytest.fixture(autouse=True)
def _legacy_diagnostic_fixtures(request, monkeypatch):
    """The pre-finalization structural fixtures intentionally carry no current approval.

    Preserve their focused file-rule/schema assertions as read-only legacy diagnostics;
    complete current-version runs are exercised separately below.
    """
    legacy = request.cls and request.cls.__name__ in {
        "TestCJKLengthCheck", "TestClassifiedTierArtifacts", "TestTelemetryAndVerify",
    }
    if request.function.__name__ == "test_run_report_rollup":
        legacy = False
    if legacy:
        original = init_run

        def legacy_init(vault, tag, **kwargs):
            manifest = original(vault, tag, **kwargs)
            manifest.pop("finalization_version", None)
            (vault.run_dir(tag) / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
            return manifest

        monkeypatch.setattr(__import__(__name__, fromlist=["init_run"]), "init_run", legacy_init)


def _historical_review_step(vault, tag):
    """Author a synthetic stored step, then convert it to diagnostic-only history."""
    path = vault.run_dir(tag) / "run.json"
    manifest = json.loads(path.read_text())
    manifest["steps"]["14.5"] = {"status": "done"}
    manifest.pop("finalization_version", None)
    path.write_text(json.dumps(manifest))


def _assert_legacy_unverified(result):
    assert result["passed"] is False
    assert result["diagnostic_only"] is True
    by_name = {item["name"]: item for item in result["checks"]}
    for rule in ("quote-integrity", "retracted-citations"):
        assert by_name[rule]["ok"] is False
        assert "unavailable/unverified" in by_name[rule]["detail"]


def _write_supported_audit(vault, tag, report, *, final=False, rate=1.0):
    from hyperresearch.core.citation_contracts import source_input
    from hyperresearch.core.citecheck import write_pairs_file

    pairs = write_pairs_file(vault, tag, report, sample_rate=rate, final=final,
                             coverage_mode="sampled" if rate < 1 else "comprehensive")
    payload = {"schema_version": 1, "report_revision": pairs["report_revision"],
               "selected_pair_ids": pairs["selected_pair_ids"], "findings": [], "results": []}
    for pair in pairs["sampled_for_llm"]:
        snapshot, body = source_input(vault, pair["note_id"])
        payload["results"].append({"pair_id": pair["pair_id"], "verdict": "supported",
                                   "source_revision": snapshot["revision"], "source_excerpt": body.strip()[:80],
                                   "evidence": "Synthetic recorded literal-body review."})
    if final:
        payload["semantic_review"] = _synthetic_semantic_review(vault, pairs)
    name = "final-cite-check-findings.json" if final else "cite-check-findings.json"
    (vault.run_dir(tag) / name).write_text(json.dumps(payload), encoding="utf-8")
    return pairs, payload


def _synthetic_semantic_review(vault, pairs):
    """Explicit judgments for these synthetic structural fixtures only.

    This helper is not production inference. Cited fixture lines are declared
    one synthetic assertion; uncited headings/filler are explicitly classified
    nonassertive. Adversarial semantic tests author their own classifications.
    """
    from hyperresearch.core.citation_contracts import source_input
    from hyperresearch.core.semantic_review import METHOD_DIMENSIONS, assertion_id

    by_id = {pair["pair_id"]: pair for pair in pairs["pairs"]}
    review = {"schema_version": 1, "report_revision": pairs["report_revision"],
              "inventory_digest": pairs["semantic_inventory"]["inventory_digest"],
              "finalization_input_digest": pairs["finalization_inputs"]["input_digest"],
              "reviewer": {"identity": "synthetic-fixture-author", "scope": "whole-report",
                           "provenance_note": "Test-authored judgments; no independent model execution claimed."},
              "task_fit": {"outcome": "satisfactory", "reason": "Fixture report exercises the synthetic query's structural acceptance path."},
              "method_review": {dimension: {"outcome": "not-applicable",
                  "reason": f"Synthetic concurrent-I/O fixture supplies no external {dimension} measurement or method claim."}
                  for dimension in METHOD_DIMENSIONS}, "units": []}
    cache = {}
    for unit in pairs["semantic_inventory"]["units"]:
        record = {"unit_id": unit["unit_id"], "atomization_reason":
                  "The fixture author supplies each cited line as one synthetic premise; other lines are structural headings or filler.",
                  "assertions": [], "nonassertive_spans": []}
        local = [by_id[identity] for identity in unit["context"]["pair_ids"] if by_id[identity]["note_id"]]
        local = [pair for pair in local if pair["report_span"]["start"] >= unit["start"]
                 and pair["report_span"]["end"] <= unit["end"]] or local[:1]
        span = {key: unit[key] for key in ("start", "end", "text")}
        if local and unit["kind"] != "heading":
            evidence = []
            for pair in local:
                snapshot, body = source_input(vault, pair["note_id"], cache)
                evidence.append({"pair_id": pair["pair_id"], "note_id": pair["note_id"],
                                 "source_revision": snapshot["revision"], "source_excerpt": body.strip()[:80],
                                 "reasoning": "Synthetic body describes the concurrent input/output premise in this fixture line."})
            record["assertions"] = [{**span, "assertion_id": assertion_id(pairs["report_revision"], unit["unit_id"], **span),
                "kind": "empirical", "presentation": "evidence-backed", "material": True, "disposition": "supported",
                "reasoning": "Fixture-author judgment of the supplied concurrent-I/O statement, not a model truth proof.",
                "task_fit": "This supplied premise is the content the synthetic query asks to report.",
                "scope": "Only this synthetic source description; no comparative or quantitative inference.",
                "method_scope": "No numerical or benchmark inference is made in this fixture premise.",
                "method_checks": {}, "evidence": evidence}]
        else:
            record["nonassertive_spans"] = [{**span, "reason":
                "Synthetic structural heading or repeated filler used for report length/format tests; no external assertion is supplied."}]
        review["units"].append(record)
    return review


def _complete_light(vault, tag, report):
    """Shipped light outputs plus genuine stage transitions and selected results."""
    run = vault.run_dir(tag)
    for name in ("query.md", "scaffold.md", "temp/coverage-matrix.md"):
        path = run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic bounded research input.", encoding="utf-8")
    decomposition = json.loads((run / "prompt-decomposition.json").read_text())
    decomposition["pipeline_tier"] = "light"
    (run / "prompt-decomposition.json").write_text(json.dumps(decomposition), encoding="utf-8")
    (run / "polish-log.json").write_text('{"applied": [], "escalations": []}', encoding="utf-8")
    (run / "readability-recommendations.json").write_text("[]", encoding="utf-8")
    (run / "readability-decisions.json").write_text(json.dumps({"total_recommendations": 0,
        "applied": [], "skipped": [], "edit_failures": [], "net_char_delta_actual": 0}), encoding="utf-8")
    for step in ("1", "2", "10", "15", "16"):
        set_step(vault, tag, step, "done")
    _write_supported_audit(vault, tag, report, final=True)


def _complete_profile(vault, tag, profile="full"):
    """Synthetic shipped producer artifacts; no live sources or model calls."""
    from hyperresearch.core.runs import record_event

    init_run(vault, tag, profile=profile, query="Synthetic query", session_id="final-session")
    run = vault.run_dir(tag)
    report = vault.notes_dir / f"final_report_{tag}.md"
    report.write_text("## Findings\n" + "Source describes concurrent input and output [[python-async-patterns]].\n" * 80)
    text_outputs = ["scaffold.md", "temp/coverage-matrix.md", "comparisons.md", "temp/corpus-critic-results.md",
                    "temp/evidence-digest.md", "temp/synthesis-plan.md", "temp/synthesis-outline.md", "temp/synthesis-pass1.md",
                    "temp/post-critic-fetch-log.md"]
    json_outputs = {"temp/contradiction-graph.json": [], "temp/consensus-claims.json": [], "loci.json": {"loci": []},
                    "temp/source-tensions.json": {"tensions": []}, "corpus-critic-gaps.json": {"gaps": []}}
    for name in text_outputs:
        path = run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic completed stage output.")
    for name, payload in json_outputs.items():
        (run / name).write_text(json.dumps(payload))
    (run / "prompt-decomposition.json").write_text(json.dumps({"pipeline_tier": profile,
        "sub_questions": ["Chapter one question", "Chapter two question"],
        "response_format": "short", "required_section_headings": ["## Findings"]}))
    for role in ("dialectic", "depth", "width", "instruction"):
        (run / f"critic-findings-{role}.json").write_text('{"findings": []}')
    (run / "patch-log.json").write_text(json.dumps({"total_findings": 0, "applied": [], "skipped": [],
        "conflicts": [], "orchestrator_escalated": []}))
    (run / "polish-log.json").write_text('{"applied": [], "escalations": []}')
    (run / "readability-recommendations.json").write_text('{"recommendations": [], "summary": {"total_recommendations": 0}}')
    (run / "readability-decisions.json").write_text(json.dumps({"total_recommendations": 0, "applied": [],
        "skipped": [], "edit_failures": [], "net_char_delta_actual": 0}))
    set_step(vault, tag, "1", "done")
    if profile == "dissertation":
        plan = {"chapters": [{"id": cid, "title": cid,
            "atomic_items": [["Chapter one question", "Chapter two question"][index]] + (["## Findings"] if index == 0 else []),
            "atomic_item_refs": [f"/sub_questions/{index}"] + (["/required_section_headings/0"] if index == 0 else []),
            "depends_on": []} for index, cid in enumerate(("ch1", "ch2"))]}
        (run / "chapter-plan.json").write_text(json.dumps(plan))
        for cid in ("ch1", "ch2"):
            record_event(vault, tag, {"type": "chapter-plan", "chapter": cid, "title": cid})
            chapter = run / "chapters" / cid
            (chapter / "temp").mkdir(parents=True)
            for name in ("comparisons.md", "temp/corpus-critic-results.md", "temp/evidence-digest.md", "draft.md"):
                (chapter / name).write_text("Synthetic chapter output.")
            for name, payload in json_outputs.items():
                (chapter / name).write_text(json.dumps(payload))
        set_step(vault, tag, "1.5", "done")
        # Independent chapters interleave freely; no total timestamp serialization.
        for stage in range(2, 11):
            for cid in ("ch1", "ch2"):
                set_step(vault, tag, str(stage), "done", chapter=cid)
        set_step(vault, tag, "6", "done")
        for stage in range(11, 15):
            set_step(vault, tag, str(stage), "done")
    elif profile != "light":
        for angle in "abc":
            (run / "temp" / f"draft-{angle}.md").write_text("Synthetic independent draft.")
        for stage in range(2, 15):
            set_step(vault, tag, str(stage), "done")
    else:
        for stage in ("2", "10"):
            set_step(vault, tag, stage, "done")
    if profile != "light":
        _write_supported_audit(vault, tag, report)
        set_step(vault, tag, "14.5", "done")
    set_step(vault, tag, "15", "done")
    set_step(vault, tag, "16", "done")
    _write_supported_audit(vault, tag, report, final=True)
    return report


class TestP1WholeReportAcceptance:
    """Synthetic recorded judgments; these are not a semantic accuracy test."""

    def test_sampled_final_cannot_approve(self, cited_vault):
        from hyperresearch.core.runs import finish_run

        tag = "p1-sampled-final"
        report = _complete_profile(cited_vault, tag, "light")
        _write_supported_audit(cited_vault, tag, report, final=True, rate=0.25)
        assert not finish_run(cited_vault, tag)["verify"]["passed"]

    def test_absent_whole_report_review_cannot_approve(self, cited_vault):
        from hyperresearch.core.runs import finish_run

        tag = "p1-no-whole-review"
        _complete_profile(cited_vault, tag, "light")
        path = cited_vault.run_dir(tag) / "final-cite-check-findings.json"
        payload = json.loads(path.read_text())
        payload.pop("semantic_review", None)
        path.write_text(json.dumps(payload))
        assert not finish_run(cited_vault, tag)["verify"]["passed"]

    @pytest.mark.parametrize("final", [False, True])
    def test_legacy_extraction_refuses_before_sync_or_database(self, tmp_vault, monkeypatch, final):
        from typer.testing import CliRunner

        from hyperresearch.cli import app
        from hyperresearch.core.runs import manifest_path
        from hyperresearch.core.vault import Vault

        tag = "p1-legacy-extract"
        init_run(tmp_vault, tag)
        path = manifest_path(tmp_vault, tag)
        manifest = json.loads(path.read_text())
        manifest["finalization_version"] = 1
        path.write_text(json.dumps(manifest))
        (tmp_vault.notes_dir / f"final_report_{tag}.md").write_text("Legacy report.")
        before = {p: p.read_bytes() for p in tmp_vault.root.rglob("*") if p.is_file()}
        calls = []

        def forbidden_sync(vault):
            calls.append("sync")
            raise AssertionError("legacy extraction may not sync")

        def forbidden_database(vault):
            calls.append("db")
            raise AssertionError("legacy extraction may not open database")

        monkeypatch.setattr(Vault, "auto_sync", forbidden_sync)
        monkeypatch.setattr(Vault, "db", property(forbidden_database))
        monkeypatch.chdir(tmp_vault.root)
        arguments = ["citecheck", "extract", tag, "--json"] + (["--final"] if final else [])
        result = CliRunner().invoke(app, arguments)
        assert result.exit_code == 1
        assert calls == []
        assert "diagnostic" in result.stdout.lower()
        assert {p: p.read_bytes() for p in tmp_vault.root.rglob("*") if p.is_file()} == before


class TestP0AcceptanceContract:
    """Recorded review/state contracts, not an evaluation of reviewer truth."""

    def test_fresh_run_uses_version_two(self, tmp_vault):
        assert init_run(tmp_vault, "new-policy")["finalization_version"] == 2

    @pytest.mark.parametrize("severity", ["critical", "major"])
    def test_initial_blocking_findings_need_reviewed_success(self, cited_vault, severity):
        from hyperresearch.core.citation_contracts import report_revision
        from hyperresearch.core.runs import RunError

        tag = f"initial-{severity}-p0"
        report = _complete_profile(cited_vault, tag)
        run = cited_vault.run_dir(tag)
        set_step(cited_vault, tag, "14.5", "running")
        pairs, payload = _write_supported_audit(cited_vault, tag, report)
        pair = pairs["sampled_for_llm"][0]
        payload["results"][0]["verdict"] = "partially-supported"
        payload["findings"] = [{"pair_id": pair["pair_id"], "finding_id": pair["finding_id"],
            "sentence": pair["sentence"], "cited_note_id": pair["note_id"], "correct_note_id": None,
            "verdict": "partially-supported", "severity": severity,
            "evidence": "Recorded scope mismatch.", "suggested_fix": "Remove the claim."}]
        (run / "cite-check-findings.json").write_text(json.dumps(payload))
        with pytest.raises(RunError):
            set_step(cited_vault, tag, "14.5", "done")
        log = {"schema_version": 1, "findings_report_revision": pairs["report_revision"],
               "reviewed_report_revision": None, "resolutions": [], "applied": [{"finding_id": pair["finding_id"]}]}
        path = run / "cite-check-patch-log.json"
        path.write_text(json.dumps(log))
        with pytest.raises(RunError):
            set_step(cited_vault, tag, "14.5", "done")
        report.write_text(report.read_text().replace(pair["sentence"], "", 1))
        log.update({"reviewed_report_revision": report_revision(report.read_bytes()), "resolutions": [{
            "finding_id": pair["finding_id"], "status": "resolved", "review_verdict": "claim-removed",
            "evidence": "Recorded reread of the corrected report; assigned occurrence removed."}]})
        path.write_text(json.dumps(log))
        assert set_step(cited_vault, tag, "14.5", "done")["steps"]["14.5"]["completion"]

    @pytest.mark.parametrize("severity", ["critical", "major"])
    def test_current_final_blocking_findings_require_repair_and_reextraction(self, cited_vault, severity):
        from hyperresearch.core.runs import finish_run

        tag = f"final-{severity}-p0"
        report = _complete_profile(cited_vault, tag, "light")
        run = cited_vault.run_dir(tag)
        pairs, payload = _write_supported_audit(cited_vault, tag, report, final=True)
        pair = pairs["sampled_for_llm"][0]
        payload["results"][0]["verdict"] = "partially-supported"
        payload["findings"] = [{"pair_id": pair["pair_id"], "finding_id": pair["finding_id"],
            "sentence": pair["sentence"], "cited_note_id": pair["note_id"], "correct_note_id": None,
            "verdict": "partially-supported", "severity": severity,
            "evidence": "Recorded scope mismatch.", "suggested_fix": "Remove the claim."}]
        (run / "final-cite-check-findings.json").write_text(json.dumps(payload))
        (run / "final-cite-check-patch-log.json").write_text(json.dumps({"schema_version": 1,
            "findings_report_revision": pairs["report_revision"], "reviewed_report_revision": pairs["report_revision"],
            "resolutions": [{"finding_id": pair["finding_id"], "status": "resolved", "review_verdict": "supported",
                             "evidence": "A same-byte log cannot erase the current negative review."}]}))
        result = finish_run(cited_vault, tag)
        assert not result["verify"]["passed"]
        assert "correction" in next(check["detail"] for check in result["verify"]["checks"] if check["name"] == "finalization")
        report.write_text(report.read_text().replace(pair["sentence"], "", 1))
        set_step(cited_vault, tag, "16", "running")
        set_step(cited_vault, tag, "16", "done")
        assert not finish_run(cited_vault, tag)["verify"]["passed"]
        _write_supported_audit(cited_vault, tag, report, final=True)
        assert finish_run(cited_vault, tag)["verify"]["passed"]

    def test_late_tier_downgrade_cannot_change_frozen_route(self, cited_vault):
        from hyperresearch.core.runs import RunError, finish_run, load_manifest, run_resume_position

        tag = "late-downgrade-p0"
        _complete_profile(cited_vault, tag)
        run = cited_vault.run_dir(tag)
        decomp = json.loads((run / "prompt-decomposition.json").read_text())
        decomp["pipeline_tier"] = "light"
        (run / "prompt-decomposition.json").write_text(json.dumps(decomp))
        manifest = load_manifest(cited_vault, tag)
        assert "14.5" in manifest["resolved_profile_steps"]
        set_step(cited_vault, tag, "12", "running")
        assert run_resume_position(cited_vault, load_manifest(cited_vault, tag))["next_step"] == "12"
        with pytest.raises(RunError, match="tier"):
            set_step(cited_vault, tag, "1", "done")
        result = finish_run(cited_vault, tag)
        assert not result["verify"]["passed"]
        assert any("tier" in check["detail"] for check in result["verify"]["checks"] if not check["ok"])

    @pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "nonstring", "empty", "changed-value", "missing-entity-field"])
    def test_chapter_atomic_items_are_exact_once_decomposition_references(self, tmp_vault, mutation):
        from hyperresearch.core.runs import RunError, _chapter_plan, load_manifest, record_event

        tag = "partition-p0"
        init_run(tmp_vault, tag, profile="dissertation")
        run = tmp_vault.run_dir(tag)
        decomposition = {"pipeline_tier": "dissertation", "sub_questions": ["Same text", "Same text"],
            "entities": [{"name": "Entity", "required_fields": ["mechanism"]}],
            "required_formats": ["table"], "required_section_headings": ["## Findings"]}
        (run / "prompt-decomposition.json").write_text(json.dumps(decomposition))
        refs = ["/sub_questions/0", "/sub_questions/1", "/entities/0/name", "/entities/0/required_fields/0",
                "/required_formats/0", "/required_section_headings/0"]
        values = ["Same text", "Same text", "Entity", "mechanism", "table", "## Findings"]
        chapters = [{"id": "ch1", "title": "One", "atomic_items": values[:2], "atomic_item_refs": refs[:2], "depends_on": []},
                    {"id": "ch2", "title": "Two", "atomic_items": values[2:], "atomic_item_refs": refs[2:], "depends_on": []}]
        for chapter in chapters:
            record_event(tmp_vault, tag, {"type": "chapter-plan", "chapter": chapter["id"], "title": chapter["title"]})
        path = run / "chapter-plan.json"
        path.write_text(json.dumps({"chapters": chapters}))
        assert _chapter_plan(tmp_vault, load_manifest(tmp_vault, tag)) == chapters
        if mutation == "missing":
            chapters[0]["atomic_items"].pop()
            chapters[0]["atomic_item_refs"].pop()
        elif mutation == "duplicate":
            chapters[1]["atomic_items"].append(values[0])
            chapters[1]["atomic_item_refs"].append(refs[0])
        elif mutation == "unknown":
            chapters[0]["atomic_item_refs"][0] = "/sub_questions/9"
        elif mutation == "nonstring":
            chapters[0]["atomic_item_refs"][0] = {"item": refs[0]}
        elif mutation == "empty":
            chapters[0]["atomic_items"] = []
            chapters[0]["atomic_item_refs"] = []
        elif mutation == "changed-value":
            chapters[0]["atomic_items"][0] = "Altered question"
        else:
            chapters[1]["atomic_items"].pop(1)
            chapters[1]["atomic_item_refs"].pop(1)
        path.write_text(json.dumps({"chapters": chapters}))
        with pytest.raises(RunError, match="atomic"):
            _chapter_plan(tmp_vault, load_manifest(tmp_vault, tag))

    def test_one_chapter_partition_is_valid(self, tmp_vault):
        from hyperresearch.core.runs import _chapter_plan, load_manifest, record_event

        tag = "one-chapter-p0"
        init_run(tmp_vault, tag, profile="dissertation")
        run = tmp_vault.run_dir(tag)
        (run / "prompt-decomposition.json").write_text(json.dumps({"pipeline_tier": "dissertation", "sub_questions": ["One question"]}))
        chapter = {"id": "ch1", "title": "One", "atomic_items": ["One question"],
                   "atomic_item_refs": ["/sub_questions/0"], "depends_on": []}
        record_event(tmp_vault, tag, {"type": "chapter-plan", "chapter": "ch1", "title": "One"})
        (run / "chapter-plan.json").write_text(json.dumps({"chapters": [chapter]}))
        assert _chapter_plan(tmp_vault, load_manifest(tmp_vault, tag)) == [chapter]

    def test_chapter_atomic_item_json_types_are_preserved(self, tmp_vault):
        from hyperresearch.core.runs import RunError, _chapter_plan, load_manifest, record_event

        tag = "chapter-json-types-p0"
        init_run(tmp_vault, tag, profile="dissertation")
        run = tmp_vault.run_dir(tag)
        period = {"period": "FY 2025", "duration": 1}
        (run / "prompt-decomposition.json").write_text(json.dumps({"pipeline_tier": "dissertation", "time_periods": [period]}))
        chapter = {"id": "ch1", "title": "One", "atomic_items": [period],
                   "atomic_item_refs": ["/time_periods/0"], "depends_on": []}
        record_event(tmp_vault, tag, {"type": "chapter-plan", "chapter": "ch1", "title": "One"})
        path = run / "chapter-plan.json"
        path.write_text(json.dumps({"chapters": [chapter]}))
        assert _chapter_plan(tmp_vault, load_manifest(tmp_vault, tag)) == [chapter]
        chapter["atomic_items"][0]["duration"] = True  # Python considers True == 1; JSON distinguishes them.
        path.write_text(json.dumps({"chapters": [chapter]}))
        with pytest.raises(RunError, match="atomic"):
            _chapter_plan(tmp_vault, load_manifest(tmp_vault, tag))


@pytest.fixture
def cited_vault(seeded_vault):
    """Seeded vault + claims + a source row so citations resolve."""
    from hyperresearch.core.claims import ingest_claims_dir

    temp = seeded_vault.root / "research" / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    (temp / "claims-python-async-patterns.json").write_text(json.dumps([
        {"claim": "Async improves throughput by 10x for network-bound workloads",
         "quoted_support": "async/await syntax enables concurrent I/O with a 10x gain",
         "numbers": ["10x"], "confidence": "high", "evidence_type": "empirical"},
    ]), encoding="utf-8")
    ingest_claims_dir(seeded_vault, vault_tag="cc-run")
    seeded_vault.db.execute(
        "INSERT OR IGNORE INTO sources (url, note_id, domain, fetched_at, provider, content_hash) "
        "VALUES ('https://example.com/async', 'python-async-patterns', 'example.com', '2026-01-01', 'test', 'x')"
    )
    seeded_vault.db.commit()
    return seeded_vault


class TestCiteCheckExtraction:
    def test_unmapped_numbered_occurrences_are_never_dropped(self, cited_vault):
        report = "Unknown [99]. Mixed [7, 99]. Repeated [99, 99].\n## Sources\n[7] Python Async Patterns. https://example.com/async\n"
        pairs = extract_pairs(report, cited_vault.db)
        assert len(pairs) == 5
        assert sum(p["note_id"] is None for p in pairs) == 4
        assert len({p["pair_id"] for p in pairs}) == 5

    def test_mechanical_match_is_only_a_candidate(self, cited_vault):
        pairs = extract_pairs("Async improves throughput by 10x [[python-async-patterns]].", cited_vault.db)
        triaged = triage_pairs(pairs, cited_vault.db)
        assert pairs[0]["verdict"] == "needs-llm"
        assert triaged["evidence_candidates"] == 1
        assert sample_needs_llm(pairs) == pairs

    def test_missing_selected_results_cannot_establish_coverage(self, cited_vault):
        from hyperresearch.core.citation_contracts import CitationContractError, validate_coverage
        from hyperresearch.core.citecheck import write_pairs_file

        report = cited_vault.notes_dir / "coverage.md"
        report.write_text("Async gives 10x throughput [[python-async-patterns]].", encoding="utf-8")
        pairs = write_pairs_file(cited_vault, "coverage-red", report)
        with pytest.raises(CitationContractError, match="results"):
            validate_coverage(pairs, {"schema_version": 1, "report_revision": pairs["report_revision"], "findings": []}, cited_vault)

    @pytest.mark.parametrize(("claim", "source", "tokens"), [
        ("The difference is +255", "The difference is -255", ["+255"]),
        ("The difference is \u2212255", "The difference is +255", ["\u2212255"]),
        ("The cost is 5bp", "The cost is 5%", ["5"]),
        ("Correlation is .93", "F1 is .93", [".93"]),
    ])
    def test_numeric_sign_unit_and_metric_matches_never_establish_support(self, cited_vault, claim, source, tokens):
        cited_vault.db.execute("UPDATE claims SET claim = ?, quoted_support = ?, numbers = ?", (source, source, json.dumps(tokens)))
        pairs = extract_pairs(f"{claim} [[python-async-patterns]].", cited_vault.db)
        triage_pairs(pairs, cited_vault.db)
        assert pairs[0]["numbers"] == tokens
        assert pairs[0]["verdict"] == "needs-llm"
        assert sample_needs_llm(pairs, 0) == pairs  # strong is selected, not reviewed

    def test_six_word_overlap_is_only_a_routing_hint(self, cited_vault):
        text = "Async syntax enables concurrent input and output"
        cited_vault.db.execute("UPDATE claims SET claim = ?, quoted_support = '', numbers = '[]'", (text,))
        pairs = extract_pairs(f"{text} [[python-async-patterns]].", cited_vault.db)
        triage_pairs(pairs, cited_vault.db)
        assert pairs[0]["routing_hints"] == ["word-overlap-candidate"]
        assert pairs[0]["verdict"] == "needs-llm"

    def test_mixed_styles_keep_occurrence_order_and_markers_are_not_quantities(self, cited_vault):
        pairs = extract_pairs("Intro [[python-async-patterns]] then unknown [99] and [[rust-ownership]].", cited_vault.db)
        assert [p["note_id"] for p in pairs] == ["python-async-patterns", None, "rust-ownership"]
        assert all(not p["strong"] and p["numbers"] == [] for p in pairs)

    def test_wikilink_pairs(self, cited_vault):
        report = "Async gives a 10x gain [[python-async-patterns]]. Rust is safe [[rust-ownership]]."
        pairs = extract_pairs(report, cited_vault.db)
        assert len(pairs) == 2
        assert pairs[0]["note_id"] == "python-async-patterns"
        assert pairs[0]["numbers"] == ["10"] or "10x" in pairs[0]["sentence"]

    def test_pairs_file_binds_exact_report_bytes_and_repeated_occurrences(self, cited_vault):
        from hyperresearch.core.citation_contracts import parse_pairs, report_revision
        from hyperresearch.core.citecheck import write_pairs_file

        report = cited_vault.notes_dir / "final_report_bytes.md"
        raw = b"\xef\xbb\xbfEvidence [[python-async-patterns]].\r\nEvidence [[python-async-patterns]].\r\n"
        report.write_bytes(raw)
        out = write_pairs_file(cited_vault, "bytes-contract", report)
        parsed = parse_pairs(out)
        assert parsed.report_revision == report_revision(raw)
        assert len(parsed.pairs) == 2
        assert parsed.pairs[0]["pair_id"] != parsed.pairs[1]["pair_id"]
        assert [p["pair_index"] for p in parsed.pairs] == [0, 1]
        persisted = json.loads((cited_vault.run_dir("bytes-contract") / "cite-check-pairs.json").read_text())
        assert persisted == out

    def test_numbered_pairs_resolve_via_sources_section(self, cited_vault):
        report = (
            "Throughput improves 10x [1].\n\n"
            "## Sources\n[1] Python Async Patterns. https://example.com/async\n"
        )
        mapping = parse_sources_section(report, cited_vault.db)
        assert mapping["1"] == "python-async-patterns"
        pairs = extract_pairs(report, cited_vault.db)
        assert len(pairs) == 1
        assert pairs[0]["note_id"] == "python-async-patterns"

    def test_grouped_citation_pairs_split_per_source(self, cited_vault):
        report = (
            "Throughput improves 10x under load [1, 2].\n\n"
            "## Sources\n[1] Python Async Patterns. https://example.com/async\n"
            "[2] Unrelated Study. https://example.com/other\n"
        )
        pairs = extract_pairs(report, cited_vault.db)
        assert len(pairs) == 2
        assert pairs[0]["note_id"] == "python-async-patterns"
        assert pairs[1]["note_id"] is None

    def test_dangling_citation_detected(self, cited_vault):
        report = "A bold claim [[no-such-note]]."
        pairs = extract_pairs(report, cited_vault.db)
        assert pairs[0]["note_id"] is None
        triaged = triage_pairs(pairs, cited_vault.db)
        assert triaged["dangling"] == 1

    def test_triage_retains_number_candidate_for_llm(self, cited_vault):
        pairs = extract_pairs(
            "Async improves throughput by 10x [[python-async-patterns]].", cited_vault.db
        )
        triaged = triage_pairs(pairs, cited_vault.db)
        assert triaged["evidence_candidates"] == 1
        assert triaged["needs_llm"] == 1

    def test_triage_flags_unsupported_for_llm(self, cited_vault):
        pairs = extract_pairs(
            "Async cures all database contention problems entirely [[python-async-patterns]].",
            cited_vault.db,
        )
        triaged = triage_pairs(pairs, cited_vault.db)
        assert triaged["needs_llm"] == 1

    def test_sampling_keeps_all_strong(self):
        pairs = [
            {"verdict": "needs-llm", "strong": True, "sentence": f"s{i}", "numbers": ["5"]}
            for i in range(5)
        ] + [
            {"verdict": "needs-llm", "strong": False, "sentence": f"w{i}", "numbers": []}
            for i in range(10)
        ]
        sampled = sample_needs_llm(pairs, sample_rate=0.5)
        strong = [p for p in sampled if p["strong"]]
        weak = [p for p in sampled if not p["strong"]]
        assert len(strong) == 5      # 100% of number-bearing
        assert len(weak) == 5        # every 2nd weak pair

    @pytest.mark.parametrize(("rate", "expected"), [(0.6, 6), (0.3, 3), (1.0, 10), (0.0, 0)])
    def test_sampling_hits_the_configured_rate(self, rate, expected):
        # round(1 / 0.6) is 2, so the every-k-th rule sampled 0.6 as 50%.
        pairs = [
            {"verdict": "needs-llm", "strong": False, "sentence": f"w{i}", "numbers": []}
            for i in range(10)
        ]
        assert len(sample_needs_llm(pairs, sample_rate=rate)) == expected

    def test_citecheck_cli(self, cited_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(cited_vault, "cc-run")
        report = cited_vault.root / "research" / "notes" / "final_report_cc-run.md"
        report.write_text(
            "Async improves throughput by 10x [[python-async-patterns]]. "
            "Also a dangling one [[ghost-note]].",
            encoding="utf-8",
        )
        monkeypatch.chdir(cited_vault.root)
        runner = CliRunner()
        r = runner.invoke(app, ["citecheck", "extract", "cc-run", "--json"])
        assert r.exit_code == 0
        data = json.loads(r.stdout)["data"]
        assert data["summary"]["evidence_candidates"] == 1
        assert data["dangling"] == 1
        assert (cited_vault.run_dir("cc-run") / "cite-check-pairs.json").exists()


class TestQuoteSpanExtraction:
    """Regression tests for quote span pairing (no min-length in the regex)."""

    def _extract_spans(self, text: str) -> list[str]:
        from hyperresearch.cli.lint import _QUOTE_SPAN_RE, _report_body_only

        body = _report_body_only(text)
        return [m.group(1) for m in _QUOTE_SPAN_RE.finditer(body)]

    def test_short_quotes_extracted_individually(self):
        text = (
            'Metrics include "TVL", "Low Security", "reasonable use", '
            '"6x Exits", and "registered entity" in the analysis.'
        )
        assert self._extract_spans(text) == [
            "TVL",
            "Low Security",
            "reasonable use",
            "6x Exits",
            "registered entity",
        ]

    def test_short_quote_before_long_quote_does_not_desync(self):
        text = (
            'The report discusses "Low Security" instruments.\n'
            'The source states "this is a sufficiently long quoted passage from the source".'
        )
        spans = self._extract_spans(text)
        assert spans == [
            "Low Security",
            "this is a sufficiently long quoted passage from the source",
        ]
        assert len(spans) == 2
        giant = "Low Security" + text.split('"Low Security"', 1)[1].split('"', 1)[0]
        assert giant not in spans[0]
        assert " instruments" not in spans[0]

    def test_curly_quotes_and_straight_quotes(self):
        text = 'Curly “quoted phrase” and straight "another phrase" here.'
        assert self._extract_spans(text) == ["quoted phrase", "another phrase"]

    def test_adjacent_quoted_phrases(self):
        text = 'Terms "TVL" "Low Security" appear back to back.'
        assert self._extract_spans(text) == ["TVL", "Low Security"]

    def test_punctuation_after_closing_quote(self):
        text = 'The label "Low Security", is used throughout.'
        assert self._extract_spans(text) == ["Low Security"]

    def test_apostrophe_inside_quote(self):
        text = 'As noted, "Python\'s async/await syntax enables concurrent I/O" today.'
        assert self._extract_spans(text) == ["Python's async/await syntax enables concurrent I/O"]

    def test_citation_markers_stripped_before_extraction(self):
        text = 'Evidence shows "Low Security" risk [[rust-ownership]].'
        assert self._extract_spans(text) == ["Low Security"]


class TestVerificationLints:
    def _lint(self, vault, rule, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        monkeypatch.chdir(vault.root)
        r = CliRunner().invoke(app, ["lint", "--rule", rule, "--json"])
        return json.loads(r.stdout)

    def test_quote_integrity_catches_fabrication(self, seeded_vault, monkeypatch):
        report = seeded_vault.root / "research" / "notes" / "final_report_q.md"
        report.write_text(
            'The paper concludes that "quantum entanglement reverses causality in every measurable frame of reference".',
            encoding="utf-8",
        )
        payload = self._lint(seeded_vault, "quote-integrity", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "quote-integrity"]
        assert len(issues) == 1
        assert issues[0]["severity"] == "error"

    def test_quote_integrity_passes_real_quote(self, seeded_vault, monkeypatch):
        report = seeded_vault.root / "research" / "notes" / "final_report_q.md"
        # This sentence exists verbatim in the seeded python-async-patterns note
        report.write_text(
            'As the note says, "Python\'s async/await syntax enables concurrent I/O" today.',
            encoding="utf-8",
        )
        payload = self._lint(seeded_vault, "quote-integrity", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "quote-integrity"]
        assert issues == []

    def test_quote_integrity_skips_short_quotes_without_false_positive(
        self, seeded_vault, monkeypatch
    ):
        report = seeded_vault.root / "research" / "notes" / "final_report_q.md"
        report.write_text(
            'The analysis covers "TVL", "Low Security", "reasonable use", '
            '"6x Exits", and "registered entity" throughout the report body. '
            "Intervening prose that would be swallowed by a desynchronized matcher "
            "when it crosses twenty characters of unquoted text in the document.",
            encoding="utf-8",
        )
        payload = self._lint(seeded_vault, "quote-integrity", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "quote-integrity"]
        assert issues == []

    def test_quote_integrity_short_quote_before_long_fabrication(
        self, seeded_vault, monkeypatch
    ):
        report = seeded_vault.root / "research" / "notes" / "final_report_q.md"
        report.write_text(
            'The report discusses "Low Security" instruments with intervening prose '
            "that must not be treated as part of a quoted span.\n"
            'The paper concludes that "quantum entanglement reverses causality in every measurable frame of reference".',
            encoding="utf-8",
        )
        payload = self._lint(seeded_vault, "quote-integrity", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "quote-integrity"]
        assert len(issues) == 1
        assert "quantum entanglement" in issues[0]["message"]
        assert "Low Security" not in issues[0]["message"]

    def test_numeric_consistency_flags_untraceable(self, cited_vault, monkeypatch):
        report = cited_vault.root / "research" / "notes" / "final_report_n.md"
        report.write_text("Revenue grew 47.3% while costs fell 1,234,567 dollars.", encoding="utf-8")
        payload = self._lint(cited_vault, "numeric-consistency", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "numeric-consistency"]
        assert len(issues) == 2
        assert all(i["severity"] == "warning" for i in issues)

    def test_retracted_citation_blocks_unless_marked(self, seeded_vault, monkeypatch):
        conn = seeded_vault.db
        conn.execute("UPDATE notes SET is_retracted = 1 WHERE id = 'rust-ownership'")
        conn.commit()
        report = seeded_vault.root / "research" / "notes" / "final_report_r.md"
        report.write_text("Rust guarantees safety [[rust-ownership]].", encoding="utf-8")
        payload = self._lint(seeded_vault, "retracted-citations", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "retracted-citations"]
        assert len(issues) == 1 and issues[0]["severity"] == "error"

        # Acknowledged retraction passes
        report.write_text(
            "One early study claimed safety guarantees [[rust-ownership]] (retracted 2025).",
            encoding="utf-8",
        )
        payload = self._lint(seeded_vault, "retracted-citations", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "retracted-citations"]
        assert issues == []


class TestIndependence:
    def test_canonical_url(self):
        assert canonical_url("https://www.Example.com/a/?utm_source=x") == canonical_url("http://example.com/a")

    def test_wire_cluster_discounts_members(self, tmp_vault):
        from hyperresearch.core.note import write_note
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        pr = "NEW YORK, PRNewswire — MegaCorp announces quantum widget breakthrough today."
        for i, (title, when) in enumerate([("MegaCorp Breakthrough", "2026-01-01"),
                                           ("MegaCorp Announces Widget", "2026-01-02"),
                                           ("Quantum Widget from MegaCorp", "2026-01-03")]):
            write_note(
                tmp_vault.notes_dir, title, body=pr + f" Outlet {i} adds a sentence.",
                source=f"https://outlet{i}.com/story", tags=["ind-run"],
                extra_frontmatter={"created": when + "T00:00:00+00:00"},
            )
        write_note(
            tmp_vault.notes_dir, "Independent Analysis",
            body="A genuinely independent, differently-worded long analysis of quantum widgets and their many limitations in practice.",
            source="https://analyst.com/deep-dive", tags=["ind-run"],
        )
        plan = compute_sync_plan(tmp_vault, force=True)
        execute_sync(tmp_vault, plan)

        result = compute_independence(tmp_vault, tag="ind-run")
        assert len(result["clusters"]) == 1
        cluster = result["clusters"][0]
        assert cluster["size"] == 3
        assert "wire" in cluster["kind"]

        scores = {r["id"]: r["independence"] for r in tmp_vault.db.execute(
            "SELECT id, independence FROM notes WHERE independence IS NOT NULL"
        )}
        assert scores[cluster["root"]] == 1.0
        assert scores["independent-analysis"] == 1.0
        for member in cluster["members"]:
            assert scores[member] == pytest.approx(1 / 3, abs=0.001)

    def test_same_canonical_url_clusters(self, tmp_vault):
        from hyperresearch.core.note import write_note
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        write_note(tmp_vault.notes_dir, "Copy A", body="Some words here for the body.",
                   source="https://www.site.com/story?utm_source=feed")
        write_note(tmp_vault.notes_dir, "Copy B", body="Entirely different words in this body text.",
                   source="https://site.com/story/")
        plan = compute_sync_plan(tmp_vault, force=True)
        execute_sync(tmp_vault, plan)
        result = compute_independence(tmp_vault)
        assert any(c["kind"] == "url" for c in result["clusters"])


class TestCJKLengthCheck:
    """`str.split()` word counts collapse to near-zero for prose in scripts
    that don't delimit words with ASCII whitespace (Chinese, Japanese,
    Korean, Thai, ...), so a report that is squarely within its documented
    character-count target must not fail length-in-range on a spurious
    word count. The detector is a structural heuristic (average
    whitespace-delimited token length), not a hardcoded script allowlist --
    it must generalize to any such script without code changes."""

    def test_lacks_word_boundaries(self):
        from hyperresearch.core.runs import _lacks_word_boundaries

        # Japanese (kana + kanji) and Chinese (hanzi) prose is written with
        # no spaces between words at all.
        assert _lacks_word_boundaries("この文章はほぼ全て日本語の文字で構成されています。")
        assert _lacks_word_boundaries("这是一段中文测试文本内容和证据。")
        # Structural-only proof of generality to a non-CJK, non-Latin
        # script family (Thai) -- no claim about grammaticality, just that
        # a long run of a spaceless script's characters trips the same
        # heuristic without any script-specific code.
        assert _lacks_word_boundaries("คำ" * 30)
        # Korean is the counter-example that justifies a *structural*
        # heuristic over a hardcoded script list: unlike Chinese/Japanese,
        # modern Korean orthography IS space-delimited, so str.split()
        # word counts are meaningful for it and it must NOT trip this
        # branch. A script-identity allowlist would get this wrong.
        assert not _lacks_word_boundaries(
            "이것은 한국어 문장으로 구성된 테스트입니다 그리고 띄어쓰기를 사용합니다."
        )
        assert not _lacks_word_boundaries(
            "This paragraph is entirely English prose with no CJK content at all."
        )
        # A handful of long wikilink citation keys inside a mostly-English
        # report should not trip the branch -- many short real words still
        # dominate the average token length.
        assert not _lacks_word_boundaries(
            "This is an English report with real citations. "
            "[[dagitty-a-graphical-tool-for-analyzing-causal-diagrams-semantic-scholar]] " * 15
        )

    def test_verify_passes_cjk_report_within_char_target_despite_low_word_count(
        self, tmp_vault
    ):
        init_run(tmp_vault, "cjk-01", profile="light")
        run_dir = tmp_vault.run_dir("cjk-01")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## 結果"],
        }), encoding="utf-8")
        (run_dir / "polish-log.json").write_text('{"applied": []}', encoding="utf-8")
        # light/short CJK char target is 1500-6000; this Japanese sentence
        # has almost no ASCII whitespace, so str.split() would count only a
        # handful of "words" despite being solidly in-range by characters.
        sentence = "これは実質的な証拠を伴う文章である[[src-note]]。"
        report = tmp_vault.root / "research" / "notes" / "final_report_cjk-01.md"
        body = "## 結果\n\n" + (sentence * 90)
        report.write_text(body, encoding="utf-8")

        word_count = len(body.split())
        assert word_count < 500  # would fail the English word-count target

        result = verify_run(tmp_vault, "cjk-01")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["length-in-range"]["ok"] is True
        assert "chars" in by_name["length-in-range"]["detail"]
        _assert_legacy_unverified(result)

    def test_verify_still_fails_cjk_report_far_outside_char_target(self, tmp_vault):
        init_run(tmp_vault, "cjk-02", profile="light")
        run_dir = tmp_vault.run_dir("cjk-02")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## 結果"],
        }), encoding="utf-8")
        # Well under the 1500-char floor (even with the 20% tolerance) --
        # the CJK branch must still be a real length check, not a bypass.
        report = tmp_vault.root / "research" / "notes" / "final_report_cjk-02.md"
        report.write_text("## 結果\n\n短い。", encoding="utf-8")

        result = verify_run(tmp_vault, "cjk-02")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["length-in-range"]["ok"] is False
        assert result["passed"] is False

    def test_verify_respects_profile_override_for_non_cjk_script(self, tmp_vault):
        """End-to-end proof that a deployment serving a non-CJK,
        non-word-boundary script (simulated here with a spaceless Thai-script
        blob) is not stuck with CJK-calibrated numbers: it configures its own
        char_targets_no_word_boundary via the standard profile-overlay
        mechanism, and verify_run honors it -- no code change needed to
        support a script this project has no real usage data for."""
        cfg_dir = tmp_vault.root / ".hyperresearch"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.toml").write_text(
            "[profile.light]\n"
            "char_targets_no_word_boundary = { short = [300, 900] }\n",
            encoding="utf-8",
        )
        init_run(tmp_vault, "th-01", profile="light")
        run_dir = tmp_vault.run_dir("th-01")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## Results"],
        }), encoding="utf-8")
        (run_dir / "polish-log.json").write_text('{"applied": []}', encoding="utf-8")
        # A spaceless Thai-script blob: within the overridden 300-900 char
        # target, but far below the shipped CJK default's 1500-char floor --
        # this only passes if the override is actually being read.
        report = tmp_vault.root / "research" / "notes" / "final_report_th-01.md"
        report.write_text("## Results\n\n" + ("คำ" * 250), encoding="utf-8")

        result = verify_run(tmp_vault, "th-01")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["length-in-range"]["ok"] is True
        assert "300-900" in by_name["length-in-range"]["detail"]


class TestClassifiedTierArtifacts:
    """The router lets step 1 reclassify a run's tier after `run init`:
    "the manifest's profile field is informational — the decomposition's
    tier rules". The ship gate has to read the same rule, or a
    light-classified run started on the installed gear is asked for critic
    findings that light tier never produces."""

    def _light_classified_gear_run(self, tmp_vault, tag: str, tier: str | None):
        init_run(tmp_vault, tag, profile="full")
        run_dir = tmp_vault.run_dir(tag)
        decomp = {
            "response_format": "short",
            "required_section_headings": ["## Findings"],
        }
        if tier is not None:
            decomp["pipeline_tier"] = tier
        (run_dir / "prompt-decomposition.json").write_text(
            json.dumps(decomp), encoding="utf-8"
        )
        (run_dir / "polish-log.json").write_text('{"applied": []}', encoding="utf-8")
        report = tmp_vault.root / "research" / "notes" / f"final_report_{tag}.md"
        report.write_text(
            "## Findings\n\n"
            + ("Substantive sentence with real evidence attached [[src-note]]. " * 80),
            encoding="utf-8",
        )
        return run_dir

    def test_light_classified_gear_run_passes_without_critic_artifacts(self, tmp_vault):
        self._light_classified_gear_run(tmp_vault, "tier-01", "light")

        result = verify_run(tmp_vault, "tier-01")
        names = {c["name"] for c in result["checks"]}
        assert not [n for n in names if n.startswith("artifact:critic-findings")]
        assert "artifact:patch-log.json" not in names
        assert "artifact:polish-log.json" in names
        _assert_legacy_unverified(result)

    def test_gear_run_without_declared_tier_still_needs_critic_artifacts(self, tmp_vault):
        self._light_classified_gear_run(tmp_vault, "tier-02", None)

        result = verify_run(tmp_vault, "tier-02")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["artifact:critic-findings-dialectic.json"]["ok"] is False
        assert result["passed"] is False

    def test_unknown_declared_tier_falls_back_to_manifest_profile(self, tmp_vault):
        self._light_classified_gear_run(tmp_vault, "tier-03", "bogus")

        result = verify_run(tmp_vault, "tier-03")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["artifact:critic-findings-dialectic.json"]["ok"] is False
        assert result["passed"] is False


class TestTelemetryAndVerify:
    def test_run_report_rollup(self, tmp_vault):
        init_run(tmp_vault, "tel-01", profile="light")
        set_step(tmp_vault, "tel-01", "1", "running")
        set_step(tmp_vault, "tel-01", "1", "done")
        report = run_report_data(tmp_vault, "tel-01")
        step1 = next(s for s in report["steps"] if s["step"] == "1")
        assert step1["status"] == "done"
        assert step1["minutes"] is not None
        assert report["events"]["step"] >= 2

    def test_verify_passes_well_formed_light_run(self, tmp_vault):
        init_run(tmp_vault, "vf-01", profile="light")
        run_dir = tmp_vault.run_dir("vf-01")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## Findings"],
        }), encoding="utf-8")
        (run_dir / "polish-log.json").write_text('{"applied": []}', encoding="utf-8")
        report = tmp_vault.root / "research" / "notes" / "final_report_vf-01.md"
        body = "## Findings\n\n" + ("Substantive sentence with real evidence attached [[src-note]]. " * 80)
        report.write_text(body, encoding="utf-8")

        result = verify_run(tmp_vault, "vf-01")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["report-exists"]["ok"]
        assert by_name["required-headings"]["ok"]
        assert by_name["length-in-range"]["ok"]
        assert by_name["citation-density"]["ok"]
        _assert_legacy_unverified(result)

    def test_verify_density_counts_each_grouped_source(self, tmp_vault):
        init_run(tmp_vault, "vf-04", profile="light")
        run_dir = tmp_vault.run_dir("vf-04")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## Findings"],
        }), encoding="utf-8")
        report = tmp_vault.root / "research" / "notes" / "final_report_vf-04.md"
        filler = "Substantive analysis continues with replicated evidence in view. " * 14
        block = filler + "The consensus across measurements holds [1, 2, 3]. "
        report.write_text("## Findings\n\n" + block * 8, encoding="utf-8")

        result = verify_run(tmp_vault, "vf-04")
        by_name = {c["name"]: c for c in result["checks"]}
        # One bracket per 133 words (~7.5/1000) sits under the 9/1000 floor;
        # the three sources inside each grouped bracket clear it (~22/1000).
        # Counting markers instead of cited-source numbers would fail this.
        assert by_name["citation-density"]["ok"]
        assert "citations/1000 words" in by_name["citation-density"]["detail"]

    @staticmethod
    def _density_check(tmp_vault, tag: str, body: str, heading: str = "## Findings") -> dict:
        init_run(tmp_vault, tag, profile="light")
        run_dir = tmp_vault.run_dir(tag)
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": [heading],
        }), encoding="utf-8")
        report = tmp_vault.root / "research" / "notes" / f"final_report_{tag}.md"
        report.write_text(body, encoding="utf-8")
        result = verify_run(tmp_vault, tag)
        return {c["name"]: c for c in result["checks"]}["citation-density"]

    def test_density_english_boundary_is_nine_per_thousand_words(self, tmp_vault):
        """The floor is 9 cited-source references per 1000 words — the old
        1.5-per-1000-characters floor expressed in words for English prose
        (~6 characters per word incl. the space), so English verdicts don't
        move (#76). Exactly 9 in 1000 words passes; 8 fails."""
        cited = "Replicated measurements support the committed position here [1]. "
        plain = "Replicated measurements support the committed position here too. "

        def report(n_cited: int) -> str:
            # n_cited cited sentences, then plain prose, padded with single
            # tokens to exactly 1000 whitespace-delimited words.
            body = "## Findings\n\n" + cited * n_cited
            while len((body + plain).split()) <= 1000:
                body += plain
            body += "pad " * (1000 - len(body.split()))
            assert len(body.split()) == 1000, len(body.split())
            return body

        ok = self._density_check(tmp_vault, "den-en-1", report(9))
        assert ok["ok"] is True, ok
        assert ok["detail"].startswith("9.00 citations/1000 words (floor 9.0)")
        fail = self._density_check(tmp_vault, "den-en-2", report(8))
        assert fail["ok"] is False, fail

    def test_density_cjk_clears_the_same_floor_per_unit_of_content(self, tmp_vault):
        """A Japanese report has no ASCII word boundaries, so the denominator
        is characters / chars_per_word_no_word_boundary (3): one citation
        per ~50 characters is ~60 per 1000 effective words and passes; one
        per ~600 characters (~5 per 1000 words) fails — even though the
        old per-character floor (1.67 per 1000 chars) would have passed it.
        The floor now means the same amount of content in every script."""
        dense = "この文章は再現された測定結果に基づく実質的な証拠を示している[1]。"  # ~34 chars, 1 cite
        assert 30 <= len(dense) <= 40
        body = "## 結果\n\n" + dense * 60
        ok = self._density_check(tmp_vault, "den-ja-1", body, heading="## 結果")
        assert ok["ok"] is True, ok
        assert "no word boundaries" in ok["detail"]

        sparse_filler = "この文章は再現された測定結果に基づく実質的な証拠を示している。"  # ~31 chars
        sparse = sparse_filler * 18 + "この文章は再現された測定結果に基づく実質的な証拠を示している[1]。"
        assert 560 <= len(sparse) <= 640
        from hyperresearch.core.runs import _lacks_word_boundaries

        assert _lacks_word_boundaries(sparse)
        body = "## 結果\n\n" + sparse * 4
        old_chars_density = 4 / len(body) * 1000
        assert old_chars_density >= 1.5  # would have cleared the old gate
        fail = self._density_check(tmp_vault, "den-ja-2", body, heading="## 結果")
        assert fail["ok"] is False, fail

    def test_density_korean_takes_the_word_path(self, tmp_vault):
        """Korean is space-delimited, so it is counted by words like English
        — the detail names plain words, not the chars/ratio denominator."""
        sentence = "이 문장은 반복된 측정에서 확인된 실질적인 근거를 제시한다 [1]. "  # 9 tokens, 1 cite
        body = "## 결과\n\n" + sentence * 60
        from hyperresearch.core.runs import _lacks_word_boundaries

        assert not _lacks_word_boundaries(body)
        res = self._density_check(tmp_vault, "den-ko-1", body, heading="## 결과")
        assert res["ok"] is True, res
        assert "citations/1000 words (floor" in res["detail"]
        assert "no word boundaries" not in res["detail"]

    def test_density_counts_wikilinks_with_the_shared_pattern(self, tmp_vault):
        """[[...]] citations are counted with core.patterns.WIKI_LINK_RE, not
        a private regex, so this gate agrees with lint and cite-check about
        what a wiki-link citation is."""
        from hyperresearch.core.patterns import WIKI_LINK_RE

        plain = "Replicated measurements support the committed position here too. "
        body = "## Findings\n\n" + (
            "Evidence sits in the vault [[src-note-alpha]] and [[src-note-beta|Beta]]. "
            + plain * 3
        ) * 20
        expected = len(WIKI_LINK_RE.findall(body))
        assert expected == 40
        res = self._density_check(tmp_vault, "den-wl-1", body)
        words = len(body.split())
        assert res["detail"].startswith(f"{expected * 1000 / words:.2f} citations/1000 words")

    def test_verify_density_floor_comes_from_profile(self, tmp_vault):
        """`citation_density_min` used to be dead config (declared, never
        read) while the gate hardcoded its own floor (#101). A profile
        overlay must now move the gate."""
        cfg = tmp_vault.root / ".hyperresearch" / "config.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("[profile.light]\ncitation_density_min = 10000\n", encoding="utf-8")
        init_run(tmp_vault, "vf-05", profile="light")
        run_dir = tmp_vault.run_dir("vf-05")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## Findings"],
        }), encoding="utf-8")
        report = tmp_vault.root / "research" / "notes" / "final_report_vf-05.md"
        body = "## Findings\n\n" + ("Substantive sentence with real evidence attached [[src-note]]. " * 80)
        report.write_text(body, encoding="utf-8")

        result = verify_run(tmp_vault, "vf-05")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["citation-density"]["ok"] is False
        assert "floor 10000" in by_name["citation-density"]["detail"]

    def test_verify_fails_on_missing_heading_and_report(self, tmp_vault):
        init_run(tmp_vault, "vf-02", profile="light")
        result = verify_run(tmp_vault, "vf-02")
        assert result["passed"] is False

    def test_verify_cli_exit_code(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(tmp_vault, "vf-03", profile="light")
        monkeypatch.chdir(tmp_vault.root)
        r = CliRunner().invoke(app, ["run", "verify", "vf-03", "--json"])
        assert r.exit_code == 1  # no report -> fail


class TestFinishGate:
    """`run finish` is the terminal gate: it must be impossible to reach
    status "done" past a failing check, and the two Q62 failure modes
    (hallucinated quotes assessed away, length gate never run) must now be
    mechanically blocking."""

    def _well_formed_light_run(self, tmp_vault, tag: str, body: str | None = None, *, complete=True):
        manifest = init_run(tmp_vault, tag, profile="light")
        run_dir = tmp_vault.run_dir(tag)
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## Findings"],
        }), encoding="utf-8")
        (run_dir / "polish-log.json").write_text('{"applied": []}', encoding="utf-8")
        report = tmp_vault.root / "research" / "notes" / f"final_report_{tag}.md"
        if body is None:
            body = "## Findings\n\n" + (
                "Substantive sentence with real evidence attached [[src-note]]. " * 80
            )
        report.write_text(body, encoding="utf-8")
        if complete and manifest.get("finalization_version") in {1, 2}:
            from hyperresearch.core.note import write_note
            from hyperresearch.core.sync import compute_sync_plan, execute_sync

            write_note(tmp_vault.notes_dir, "Src Note", body="Synthetic source body supports the fixture sentence.")
            execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
            _complete_light(tmp_vault, tag, report)
        return report

    def test_finish_marks_clean_run_done(self, tmp_vault):
        from hyperresearch.core.runs import finish_run, load_manifest

        self._well_formed_light_run(tmp_vault, "fin-01")
        result = finish_run(tmp_vault, "fin-01")
        assert result["verify"]["passed"] is True
        manifest = load_manifest(tmp_vault, "fin-01")
        assert manifest["status"] == "done"
        assert manifest["blocked_on"] is None
        assert manifest["verify"]["passed"] is True
        assert manifest["verify"]["failed_checks"] == []

    def test_comprehensive_finish_cannot_drop_an_unknown_occurrence(self, cited_vault):
        from hyperresearch.core.citation_contracts import report_revision
        from hyperresearch.core.citecheck import write_pairs_file
        from hyperresearch.core.runs import finish_run

        tag = "comprehensive-unknown"
        unknown = "An unresolved claim has a missing numbered source [99]."
        body = "## Findings\n\n" + (
            "Substantive context discusses concurrent input and output [[python-async-patterns]]. " * 80
        ) + unknown
        report = self._well_formed_light_run(cited_vault, tag, body)
        pairs = write_pairs_file(cited_vault, tag, report, coverage_mode="comprehensive", final=True)
        assert len(pairs["dangling"]) == 1 and pairs["unreviewed_pair_ids"] == []
        envelope = {"schema_version": 1, "report_revision": pairs["report_revision"],
                    "selected_pair_ids": pairs["selected_pair_ids"], "findings": [], "results": [{
                        "pair_id": pair["pair_id"], "verdict": "supported",
                        "source_revision": pair["source_input"]["revision"],
                        "source_excerpt": "Python's async/await syntax enables concurrent I/O.",
                        "evidence": "Recorded source-body review fixture.",
                    } for pair in pairs["sampled_for_llm"]]}
        path = cited_vault.run_dir(tag) / "final-cite-check-findings.json"
        path.write_text(json.dumps(envelope), encoding="utf-8")
        blocked = finish_run(cited_vault, tag)
        checks = {c["name"]: c for c in blocked["verify"]["checks"]}
        assert checks["finalization"]["ok"] is False
        assert "dangling" in checks["finalization"]["detail"]
        assert blocked["manifest"]["status"] == "blocked"
        pair = pairs["dangling"][0]
        envelope["findings"] = [{
            "pair_id": pair["pair_id"], "finding_id": pair["finding_id"],
            "sentence": pair["sentence"], "cited_note_id": None, "correct_note_id": None,
            "severity": "critical", "verdict": "dangling", "evidence": "No Sources mapping exists.",
            "suggested_fix": "Remove the unsupported claim.",
        }]
        path.write_text(json.dumps(envelope), encoding="utf-8")
        assert finish_run(cited_vault, tag)["verify"]["passed"] is False  # no reviewed resolution
        log = {"schema_version": 1, "findings_report_revision": pairs["report_revision"],
               "reviewed_report_revision": report_revision(report.read_bytes()), "resolutions": [{
                   "finding_id": pair["finding_id"], "status": "resolved", "review_verdict": "claim-removed",
                   "evidence": "Reread current report; the unknown-source claim is absent.",
               }]}
        (cited_vault.run_dir(tag) / "final-cite-check-patch-log.json").write_text(json.dumps(log), encoding="utf-8")
        assert finish_run(cited_vault, tag)["verify"]["passed"] is False  # same-byte resolution cannot clear current critical
        report.write_text(body.replace(unknown, ""), encoding="utf-8")
        set_step(cited_vault, tag, "16", "running")
        set_step(cited_vault, tag, "16", "done")
        _write_supported_audit(cited_vault, tag, report, final=True)
        assert finish_run(cited_vault, tag)["verify"]["passed"] is True

    def test_finish_blocks_hallucinated_quote(self, tmp_vault):
        from hyperresearch.core.runs import finish_run, load_manifest

        body = "## Findings\n\n" + (
            "Substantive sentence with real evidence attached [[src-note]]. " * 80
        ) + '\n\nAs one expert put it, "this quotation was never fetched into any vault note anywhere."\n'
        self._well_formed_light_run(tmp_vault, "fin-02", body=body)
        result = finish_run(tmp_vault, "fin-02")
        assert result["verify"]["passed"] is False
        by_name = {c["name"]: c for c in result["verify"]["checks"]}
        assert by_name["quote-integrity"]["ok"] is False
        manifest = load_manifest(tmp_vault, "fin-02")
        assert manifest["status"] == "blocked"
        assert manifest["blocked_on"] == "verify"
        assert "quote-integrity" in manifest["verify"]["failed_checks"]

    def test_finish_blocks_over_length_report(self, tmp_vault):
        from hyperresearch.core.runs import finish_run, load_manifest

        # light/short target is 500-2000 words; 20% tolerance caps at 2400.
        body = "## Findings\n\n" + (
            "Substantive sentence with real evidence attached [[src-note]]. " * 500
        )
        self._well_formed_light_run(tmp_vault, "fin-03", body=body)
        result = finish_run(tmp_vault, "fin-03")
        assert result["verify"]["passed"] is False
        by_name = {c["name"]: c for c in result["verify"]["checks"]}
        assert by_name["length-in-range"]["ok"] is False
        manifest = load_manifest(tmp_vault, "fin-03")
        assert manifest["status"] == "blocked"
        assert manifest["blocked_on"] == "verify"

    def test_finish_then_fix_then_done(self, tmp_vault):
        """The intended loop: blocked -> fix the report -> finish passes."""
        from hyperresearch.core.runs import finish_run, load_manifest

        body = "## Findings\n\n" + (
            "Substantive sentence with real evidence attached [[src-note]]. " * 80
        ) + '\n\nAs one expert put it, "this quotation was never fetched into any vault note anywhere."\n'
        report = self._well_formed_light_run(tmp_vault, "fin-04", body=body)
        assert finish_run(tmp_vault, "fin-04")["verify"]["passed"] is False

        # The prescribed fix: drop the quotation marks, not the gate.
        fixed = report.read_text(encoding="utf-8").replace(
            '"this quotation was never fetched into any vault note anywhere."',
            "this claim stands as the report's own framing.",
        )
        report.write_text(fixed, encoding="utf-8")
        set_step(tmp_vault, "fin-04", "16", "running")
        set_step(tmp_vault, "fin-04", "16", "done")
        _write_supported_audit(tmp_vault, "fin-04", report, final=True)
        assert finish_run(tmp_vault, "fin-04")["verify"]["passed"] is True
        assert load_manifest(tmp_vault, "fin-04")["status"] == "done"

    def test_finish_cli_exit_code(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(tmp_vault, "fin-05", profile="light")
        monkeypatch.chdir(tmp_vault.root)
        r = CliRunner().invoke(app, ["run", "finish", "fin-05", "--json"])
        assert r.exit_code == 1  # no report -> gate fails -> blocked
        from hyperresearch.core.runs import load_manifest

        assert load_manifest(tmp_vault, "fin-05")["status"] == "blocked"

    def test_verify_includes_content_gates(self, tmp_vault):
        """verify_run itself must carry quote-integrity + retracted-citations
        checks — one command, whole verdict."""
        self._well_formed_light_run(tmp_vault, "fin-06")
        result = verify_run(tmp_vault, "fin-06")
        names = {c["name"] for c in result["checks"]}
        assert "quote-integrity" in names
        assert "retracted-citations" in names

    def test_cite_check_findings_accepts_both_shapes(self, tmp_vault):
        """Legacy shapes remain readable, but log presence proves no resolution."""

        for tag, payload in (
            ("fin-07", {"findings": [{"severity": "critical", "verdict": "unsupported"}]}),
            ("fin-08", [{"severity": "critical", "verdict": "unsupported"}]),
        ):
            self._well_formed_light_run(tmp_vault, tag, complete=False)
            run_dir = tmp_vault.run_dir(tag)
            _historical_review_step(tmp_vault, tag)
            (run_dir / "cite-check-findings.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            result = verify_run(tmp_vault, tag)  # must not raise
            by_name = {c["name"]: c for c in result["checks"]}
            # A critical finding with no patch log fails the check cleanly.
            assert by_name["cite-check-resolved"]["ok"] is False
            (run_dir / "cite-check-patch-log.json").write_text("[]", encoding="utf-8")
            result = verify_run(tmp_vault, tag)
            by_name = {c["name"]: c for c in result["checks"]}
            # A log's presence cannot prove that a legacy critical was reviewed.
            assert by_name["cite-check-resolved"]["ok"] is False

    @pytest.mark.parametrize("payload", [{}, {"findings": None}, {"findings": {}}, 1, [1]])
    def test_cite_check_rejects_malformed_payload_cleanly(self, tmp_vault, payload):
        tag = "malformed-citations"
        self._well_formed_light_run(tmp_vault, tag, complete=False)
        _historical_review_step(tmp_vault, tag)
        (tmp_vault.run_dir(tag) / "cite-check-findings.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        by_name = {c["name"]: c for c in verify_run(tmp_vault, tag)["checks"]}
        assert by_name["cite-check-resolved"]["ok"] is False

    @pytest.mark.parametrize("payload", [[], {"findings": []}])
    def test_cite_check_legacy_empty_is_diagnostic_without_rewriting(self, tmp_vault, payload):
        tag = "legacy-zero"
        self._well_formed_light_run(tmp_vault, tag, complete=False)
        _historical_review_step(tmp_vault, tag)
        path = tmp_vault.run_dir(tag) / "cite-check-findings.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        before = path.read_bytes()
        by_name = {c["name"]: c for c in verify_run(tmp_vault, tag)["checks"]}
        assert by_name["cite-check-resolved"]["ok"] is True
        assert "diagnostic" in by_name["cite-check-resolved"]["detail"]
        assert by_name["cite-check-coverage"]["ok"] is False
        assert verify_run(tmp_vault, tag)["passed"] is False
        assert path.read_bytes() == before

    def test_cite_check_binds_original_findings_and_reviewed_patched_bytes(self, tmp_vault):
        from hyperresearch.core.citation_contracts import report_revision
        from hyperresearch.core.citecheck import write_pairs_file

        tag = "reviewed-critical"
        report = self._well_formed_light_run(tmp_vault, tag, complete=False)
        run_dir = tmp_vault.run_dir(tag)
        pairs = write_pairs_file(tmp_vault, tag, report)
        pair = pairs["pairs"][0]
        findings = {
            "schema_version": 1, "report_revision": pairs["report_revision"],
            "findings": [{
                "pair_id": pair["pair_id"], "finding_id": pair["finding_id"],
                "sentence": pair["sentence"], "cited_note_id": pair["note_id"],
                "correct_note_id": None, "severity": "critical", "verdict": "dangling",
                "evidence": "The citation does not resolve.", "suggested_fix": "Remove the claim.",
            }],
        }
        (run_dir / "cite-check-findings.json").write_text(json.dumps(findings), encoding="utf-8")
        _historical_review_step(tmp_vault, tag)

        def citation_check():
            return next(c for c in verify_run(tmp_vault, tag)["checks"] if c["name"] == "cite-check-resolved")

        assert citation_check()["ok"] is False  # missing review
        report.write_bytes(report.read_bytes() + b"\nPatched report.\n")
        log = {
            "schema_version": 1, "findings_report_revision": findings["report_revision"],
            "reviewed_report_revision": report_revision(report.read_bytes()),
            "applied": [{"finding_id": pair["finding_id"]}],
            "resolutions": [{
                "finding_id": pair["finding_id"], "status": "resolved",
                "review_verdict": "supported", "evidence": "Reread report and the corrected source.",
            }],
        }
        (run_dir / "cite-check-patch-log.json").write_text(json.dumps(log), encoding="utf-8")
        assert citation_check()["ok"] is True
        # Even a newline change invalidates a recorded post-patch review.
        report.write_bytes(report.read_bytes() + b"\n")
        assert citation_check()["ok"] is False
        assert "stale" in citation_check()["detail"]
        # A fresh recorded rereview can bind later polished bytes while the
        # original finding identity/revision remains intact.
        original_revision = log["findings_report_revision"]
        log["reviewed_report_revision"] = report_revision(report.read_bytes())
        log["resolutions"][0]["evidence"] = "Reread current polished report and corrected source again."
        (run_dir / "cite-check-patch-log.json").write_text(json.dumps(log), encoding="utf-8")
        assert citation_check()["ok"] is True
        assert log["findings_report_revision"] == original_revision

    @pytest.mark.parametrize("contents", [b"{", b"\xff"])
    def test_cite_check_invalid_json_or_encoding_fails_cleanly(self, tmp_vault, contents):
        tag = "unreadable-citations"
        self._well_formed_light_run(tmp_vault, tag, complete=False)
        _historical_review_step(tmp_vault, tag)
        (tmp_vault.run_dir(tag) / "cite-check-findings.json").write_bytes(contents)
        by_name = {c["name"]: c for c in verify_run(tmp_vault, tag)["checks"]}
        assert by_name["cite-check-resolved"]["ok"] is False

    def test_cite_check_major_application_log_cannot_prove_resolution(self, cited_vault):
        from hyperresearch.core.citecheck import write_pairs_file

        tag = "major-only"
        body = "## Findings\n\n" + (
            "Sources provide limited evidence about the current claim [[python-async-patterns]]. " * 80
        )
        report = self._well_formed_light_run(cited_vault, tag, body, complete=False)
        run_dir = cited_vault.run_dir(tag)
        pairs = write_pairs_file(cited_vault, tag, report)
        pair = pairs["pairs"][0]
        findings = {
            "schema_version": 1, "report_revision": pairs["report_revision"],
            "findings": [{
                "pair_id": pair["pair_id"], "finding_id": pair["finding_id"],
                "sentence": pair["sentence"], "cited_note_id": pair["note_id"],
                "correct_note_id": None, "severity": "major", "verdict": "partially-supported",
                "evidence": "The source supports only the narrower claim.", "suggested_fix": "Narrow the claim.",
            }],
        }
        (run_dir / "cite-check-findings.json").write_text(json.dumps(findings), encoding="utf-8")
        log = {
            "schema_version": 1, "findings_report_revision": pairs["report_revision"],
            "reviewed_report_revision": None, "resolutions": [], "total_findings": 1,
            "applied": [{"finding_id": pair["finding_id"]}], "skipped": [],
            "conflicts": [], "orchestrator_escalated": [],
        }
        (run_dir / "cite-check-patch-log.json").write_text(json.dumps(log), encoding="utf-8")
        _historical_review_step(cited_vault, tag)
        by_name = {c["name"]: c for c in verify_run(cited_vault, tag)["checks"]}
        assert by_name["cite-check-resolved"]["ok"] is False, by_name["cite-check-resolved"]
        # A claimed review must bind the actual known finding identity.
        from hyperresearch.core.citation_contracts import report_revision

        log["reviewed_report_revision"] = report_revision(report.read_bytes())
        log["resolutions"] = [{
            "finding_id": "finding-v1:" + "0" * 64, "status": "resolved",
            "review_verdict": "supported", "evidence": "Unrelated review.",
        }]
        (run_dir / "cite-check-patch-log.json").write_text(json.dumps(log), encoding="utf-8")
        by_name = {c["name"]: c for c in verify_run(cited_vault, tag)["checks"]}
        assert by_name["cite-check-resolved"]["ok"] is False


class TestCiteCheckerAgentInstall:
    def test_agent_installs(self, tmp_vault):
        from hyperresearch.core.hooks import _install_cite_checker_agent

        result = _install_cite_checker_agent(tmp_vault.root, "hyperresearch")
        assert result is not None
        body = (tmp_vault.root / ".claude" / "agents" / "hyperresearch-cite-checker.md").read_text(encoding="utf-8")
        assert "name: hyperresearch-cite-checker" in body
        assert "model: sonnet" in body
        assert "wrong-source" in body
        assert "SKEPTICAL" in body
        assert "{hpr_path}" not in body
        assert "<<" not in body


class TestFinalizationContract:
    def test_final_cli_and_finish_honor_custom_research_directory(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app
        from hyperresearch.core.note import write_note
        from hyperresearch.core.runs import finish_run
        from hyperresearch.core.sync import compute_sync_plan, execute_sync
        from hyperresearch.core.vault import Vault

        vault = Vault.init(tmp_path / "custom-vault", research_dir="docs/wiki")
        write_note(vault.notes_dir, "Python Async Patterns", body="Synthetic source supports concurrent input and output.")
        execute_sync(vault, compute_sync_plan(vault, force=True))
        tag = "custom-dir"
        _complete_profile(vault, tag, "light")
        monkeypatch.chdir(vault.root)
        result = CliRunner().invoke(app, ["citecheck", "extract", tag, "--final", "--sample-rate", "1", "--json"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["data"]["pairs_file"] == str(
            vault.run_dir(tag) / "final-cite-check-pairs.json"
        )
        finished = finish_run(vault, tag)
        assert finished["verify"]["passed"], [check for check in finished["verify"]["checks"] if not check["ok"]]

    def test_known_tier_keeps_configured_scale(self, cited_vault):
        from hyperresearch.core.runs import finish_run

        with cited_vault.config_path.open("a") as config:
            config.write("\n[profile.full]\nsource_min = 90\ncitation_density_min = 12\n")
        _complete_profile(cited_vault, "custom-scale", "full")
        result = finish_run(cited_vault, "custom-scale")
        assert result["verify"]["passed"]
        assert result["manifest"]["verify"]["inputs"]["profile"]["source_min"] == 90

    def test_shipped_nonempty_output_shapes_remain_usable(self, cited_vault):
        from hyperresearch.core.runs import finish_run

        tag = "nonempty-outputs"
        report = _complete_profile(cited_vault, tag)
        run = cited_vault.run_dir(tag)
        outputs = {
            "temp/consensus-claims.json": ["Independent sources agree on this bounded claim."],
            "critic-findings-depth.json": {"findings": [{"severity": "minor", "location": "Findings",
                "issue": "A qualifier could help.", "recommendation": "Consider a bounded qualifier."}]},
            "loci.json": {"loci": [{"name": "Mechanism", "one_line": "A bounded mechanism", "rationale": "Synthetic evidence.",
                "flavor": "technical", "importance": 1, "uncertainty": 1, "disagreement": 1, "decision_impact": 1,
                "composite_score": 4, "source_budget": 0}]},
            "corpus-critic-gaps.json": {"gaps": [{"id": "cc-1", "priority": "high", "type": "strengthening"}]},
            "polish-log.json": {"applied": [{"category": "hygiene", "description": "Checked fixture prose.", "chars_removed": 0}], "escalations": []},
            "readability-recommendations.json": {"recommendations": [{"id": "rec-1", "category": "make-list", "severity": "minor",
                "section": "Findings", "current": "Source describes", "recommended": "- Source describes", "rationale": "Optional list."}],
                "summary": {"total_recommendations": 1}},
            "readability-decisions.json": {"total_recommendations": 1, "applied": [],
                "skipped": [{"id": "rec-1", "reason": "Preserve prose."}], "edit_failures": [], "net_char_delta_actual": 0},
        }
        for name, payload in outputs.items():
            (run / name).write_text(json.dumps(payload))
        for step in ("14.5", "15", "16"):
            set_step(cited_vault, tag, step, "running")
            set_step(cited_vault, tag, step, "done")
        _write_supported_audit(cited_vault, tag, report, final=True)
        assert finish_run(cited_vault, tag)["verify"]["passed"]

    @pytest.mark.parametrize("profile", ["light", "full", "premier", "dissertation"])
    def test_valid_tier_matrix_and_current_receipt(self, cited_vault, profile):
        from hyperresearch.core.runs import approval_current, finish_run, load_manifest

        tag = f"current-{profile}"
        _complete_profile(cited_vault, tag, profile)
        result = finish_run(cited_vault, tag)
        assert result["verify"]["passed"], result["verify"]["checks"]
        manifest = load_manifest(cited_vault, tag)
        assert approval_current(cited_vault, manifest)
        assert manifest["verify"]["inputs"]["report_revision"]
        if profile == "light":
            assert not (cited_vault.run_dir(tag) / "cite-check-pairs.json").exists()

    @pytest.mark.parametrize("profile,stage", [("light", "15"), ("full", "14.5"), ("premier", "12"), ("dissertation", "1.5")])
    def test_required_flags_cannot_be_faked_or_skipped(self, cited_vault, profile, stage):
        from hyperresearch.core.runs import finish_run, load_manifest, manifest_path

        tag = "missing-stage"
        _complete_profile(cited_vault, tag, profile)
        manifest = load_manifest(cited_vault, tag)
        manifest["steps"][stage]["status"] = "skipped"
        manifest["profile_steps"].remove(stage)  # recovery state cannot waive the tier contract
        manifest["status"] = "done"  # forged status cannot replace a receipt
        manifest_path(cited_vault, tag).write_text(json.dumps(manifest))
        assert finish_run(cited_vault, tag)["verify"]["passed"] is False

    @pytest.mark.parametrize("name,contents", [
        ("polish-log.json", None), ("polish-log.json", "[]"), ("polish-log.json", '{"applied": []}'),
        ("critic-findings-depth.json", "{}"), ("patch-log.json", '{"applied": []}'),
        ("loci.json", '{"loci": 1}'), ("temp/contradiction-graph.json", "{}"),
        ("readability-decisions.json", "{}"), ("temp/draft-b.md", ""),
        ("critic-findings-depth.json", '{"findings": [{}]}'),
        ("loci.json", '{"loci": [{}]}'), ("corpus-critic-gaps.json", '{"gaps": [{}]}'),
        ("polish-log.json", '{"applied": [{}], "escalations": []}'),
        ("readability-recommendations.json", '[{"id": "rec-1"}]'),
    ])
    def test_required_outputs_are_validated(self, cited_vault, name, contents):
        from hyperresearch.core.runs import finish_run

        _complete_profile(cited_vault, "bad-output")
        path = cited_vault.run_dir("bad-output") / name
        if contents is None:
            path.unlink()
        else:
            path.write_text(contents)
        assert finish_run(cited_vault, "bad-output")["verify"]["passed"] is False

    @pytest.mark.parametrize("kind", ["pending", "unregistered", "missing-draft", "cycle", "dependency-order"])
    def test_exact_chapter_completion_and_dependencies(self, cited_vault, kind):
        from hyperresearch.core.runs import finish_run, load_manifest, manifest_path

        tag = "chapter-negative"
        _complete_profile(cited_vault, tag, "dissertation")
        run = cited_vault.run_dir(tag)
        manifest = load_manifest(cited_vault, tag)
        if kind == "pending":
            manifest["chapters"]["ch1"]["steps"]["9"]["status"] = "pending"
        elif kind == "unregistered":
            del manifest["chapters"]["ch2"]
        elif kind == "missing-draft":
            (run / "chapters/ch2/draft.md").unlink()
        else:
            plan = json.loads((run / "chapter-plan.json").read_text())
            plan["chapters"][0]["depends_on"] = ["ch2"]
            if kind == "cycle":
                plan["chapters"][1]["depends_on"] = ["ch1"]
            (run / "chapter-plan.json").write_text(json.dumps(plan))
        manifest_path(cited_vault, tag).write_text(json.dumps(manifest))
        assert finish_run(cited_vault, tag)["verify"]["passed"] is False

    def test_outer_boundaries_and_initial_review_snapshot_survive_polish(self, cited_vault):
        from hyperresearch.core.runs import RunError, finish_run, load_manifest

        tag = "initial-preserved"
        report = _complete_profile(cited_vault, tag)
        initial = {name: (cited_vault.run_dir(tag) / name).read_bytes() for name in ("cite-check-pairs.json", "cite-check-findings.json")}
        set_step(cited_vault, tag, "14.5", "running")
        with pytest.raises(RunError, match=r"14\.5"):
            set_step(cited_vault, tag, "15", "done")
        set_step(cited_vault, tag, "14.5", "done")
        set_step(cited_vault, tag, "15", "running")
        with pytest.raises(RunError, match="15"):
            set_step(cited_vault, tag, "16", "done")
        set_step(cited_vault, tag, "15", "done")
        report.write_bytes(report.read_bytes() + b"\nPolished conclusion.\n")
        with pytest.raises(RunError, match="restart"):
            set_step(cited_vault, tag, "16", "done")
        set_step(cited_vault, tag, "16", "running")
        set_step(cited_vault, tag, "16", "done")
        _write_supported_audit(cited_vault, tag, report, final=True)
        assert finish_run(cited_vault, tag)["verify"]["passed"]
        assert load_manifest(cited_vault, tag)["steps"]["14.5"]["completion"]["report_revision"] != load_manifest(cited_vault, tag)["verify"]["inputs"]["report_revision"]
        assert all((cited_vault.run_dir(tag) / name).read_bytes() == data for name, data in initial.items())

    def test_initial_critical_requires_real_review_before_completion(self, cited_vault):
        from hyperresearch.core.citation_contracts import report_revision
        from hyperresearch.core.runs import RunError, finish_run

        tag = "initial-critical"
        report = _complete_profile(cited_vault, tag)
        run = cited_vault.run_dir(tag)
        set_step(cited_vault, tag, "14.5", "running")
        pairs, payload = _write_supported_audit(cited_vault, tag, report)
        pair = pairs["sampled_for_llm"][0]
        payload["results"][0]["verdict"] = "wrong-source"
        payload["findings"] = [{"pair_id": pair["pair_id"], "finding_id": pair["finding_id"],
            "sentence": pair["sentence"], "cited_note_id": pair["note_id"], "correct_note_id": None,
            "verdict": "wrong-source", "severity": "critical", "evidence": "Recorded source mismatch.",
            "suggested_fix": "Remove the claim."}]
        (run / "cite-check-findings.json").write_text(json.dumps(payload))
        with pytest.raises(RunError):
            set_step(cited_vault, tag, "14.5", "done")
        report.write_text(report.read_text().replace(pair["sentence"], "", 1))
        log = {"schema_version": 1, "findings_report_revision": pairs["report_revision"],
               "reviewed_report_revision": report_revision(report.read_bytes()), "resolutions": [{
                   "finding_id": pair["finding_id"], "status": "resolved", "review_verdict": "claim-removed",
                   "evidence": "Recorded reread of the corrected report; assigned occurrence removed."}]}
        (run / "cite-check-patch-log.json").write_text(json.dumps(log))
        set_step(cited_vault, tag, "14.5", "done")
        initial = (run / "cite-check-patch-log.json").read_bytes()
        set_step(cited_vault, tag, "15", "running")
        set_step(cited_vault, tag, "15", "done")
        set_step(cited_vault, tag, "16", "running")
        report.write_bytes(report.read_bytes() + b"\nPolished ending.\n")
        set_step(cited_vault, tag, "16", "done")
        _write_supported_audit(cited_vault, tag, report, final=True)
        assert finish_run(cited_vault, tag)["verify"]["passed"]
        assert (run / "cite-check-patch-log.json").read_bytes() == initial

    @pytest.mark.parametrize("kind", ["report", "source", "audit", "stage", "output"])
    def test_stale_done_receipts_are_detected_without_status_mutation(self, cited_vault, kind):
        from hyperresearch.core.codex import stop_gate_decision
        from hyperresearch.core.runs import (
            finish_run,
            load_manifest,
            manifest_path,
            run_resume_position,
            status_summary,
        )

        tag = "stale-done"
        report = _complete_profile(cited_vault, tag)
        assert finish_run(cited_vault, tag)["verify"]["passed"]
        assert stop_gate_decision(cited_vault, session_id="final-session") is None
        run = cited_vault.run_dir(tag)
        if kind == "report":
            report.write_bytes(report.read_bytes() + b"\n")
        elif kind == "source":
            path = cited_vault.notes_dir / "python-async-patterns.md"
            path.write_bytes(path.read_bytes() + b"\nChanged source.\n")
        elif kind == "audit":
            (run / "final-cite-check-findings.json").write_text("{}")
        elif kind == "stage":
            manifest = load_manifest(cited_vault, tag)
            manifest["steps"]["10"]["finished_at"] = "changed"
            manifest_path(cited_vault, tag).write_text(json.dumps(manifest))
        else:
            (run / "polish-log.json").write_text('{"applied": [], "escalations": [], "changed": true}')
        before = manifest_path(cited_vault, tag).read_bytes()
        assert status_summary(cited_vault, tag)["approval_current"] is False
        assert run_resume_position(cited_vault, load_manifest(cited_vault, tag))["action"] != "complete"
        assert stop_gate_decision(cited_vault, session_id="final-session")["decision"] == "block"
        assert manifest_path(cited_vault, tag).read_bytes() == before

    @pytest.mark.parametrize("during", ["verify", "before-save", "after-save", "finish-event"])
    def test_mutation_across_verification_and_persistence_is_rejected(self, cited_vault, monkeypatch, during):
        from hyperresearch.core import runs

        tag = "mutation"
        report = _complete_profile(cited_vault, tag)
        original_verify, original_save = runs.verify_run, runs._save
        original_event = runs.record_event
        if during == "verify":
            from hyperresearch.cli import lint

            original_lint = lint._check_cited_quote_integrity

            def mutate_lint(*args, **kwargs):
                report.write_bytes(report.read_bytes() + b"\n")
                return original_lint(*args, **kwargs)

            monkeypatch.setattr(lint, "_check_cited_quote_integrity", mutate_lint)
        elif during == "before-save":
            def mutate_verify(*args):
                result = original_verify(*args)
                report.write_bytes(report.read_bytes() + b"\n")
                return result

            monkeypatch.setattr(runs, "verify_run", mutate_verify)
        elif during == "after-save":
            def mutate_save(*args):
                original_save(*args)
                report.write_bytes(report.read_bytes() + b"\n")

            monkeypatch.setattr(runs, "_save", mutate_save)
        else:
            def mutate_event(vault, vault_tag, event):
                original_event(vault, vault_tag, event)
                if event.get("type") == "finish" and event.get("passed") is True:
                    report.write_bytes(report.read_bytes() + b"\n")

            monkeypatch.setattr(runs, "record_event", mutate_event)
        result = runs.finish_run(cited_vault, tag)
        assert result["verify"]["passed"] is False
        assert runs.load_manifest(cited_vault, tag)["status"] == "blocked"
        events = [json.loads(line) for line in (cited_vault.run_dir(tag) / "events.jsonl").read_text().splitlines()]
        finishes = [event for event in events if event.get("type") == "finish"]
        assert finishes[-1]["passed"] is False
        if during == "finish-event":
            assert finishes[-2]["passed"] is True
            assert finishes[-1]["invalidated"] is True

    def test_final_actions_and_truthful_sampled_coverage(self, cited_vault):
        from hyperresearch.core.runs import finish_run, load_manifest, run_resume_position

        tag = "sampled-final"
        report = _complete_profile(cited_vault, tag, "light")
        (cited_vault.run_dir(tag) / "final-cite-check-findings.json").unlink()
        position = run_resume_position(cited_vault, load_manifest(cited_vault, tag))
        assert position["next_step"] is None and position["action"] == "final-audit"
        assert "--final" in position["command"]
        pairs, _ = _write_supported_audit(cited_vault, tag, report, final=True, rate=0.25)
        assert len(pairs["unreviewed_pair_ids"]) == 60
        assert run_resume_position(cited_vault, load_manifest(cited_vault, tag))["action"] == "final-audit"
        assert not finish_run(cited_vault, tag)["verify"]["passed"]
        _write_supported_audit(cited_vault, tag, report, final=True)
        assert finish_run(cited_vault, tag)["verify"]["passed"]

    def test_final_cli_refuses_incomplete_inputs_and_uses_distinct_paths(self, cited_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app
        from hyperresearch.core.runs import load_manifest, manifest_path

        tag = "final-cli"
        _complete_profile(cited_vault, tag, "light")
        monkeypatch.chdir(cited_vault.root)
        result = CliRunner().invoke(app, ["citecheck", "extract", tag, "--final", "--json"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["data"]["pairs_file"].endswith("final-cite-check-pairs.json")
        assert json.loads(result.stdout)["data"]["coverage_mode"] == "comprehensive"
        assert json.loads(result.stdout)["data"]["unreviewed"] == 0
        assert not (cited_vault.run_dir(tag) / "cite-check-pairs.json").exists()
        manifest = load_manifest(cited_vault, tag)
        manifest["steps"]["15"]["status"] = "pending"
        manifest_path(cited_vault, tag).write_text(json.dumps(manifest))
        result = CliRunner().invoke(app, ["citecheck", "extract", tag, "--final", "--json"])
        assert result.exit_code == 1

    def test_plain_status_and_legacy_diagnostics_do_not_claim_completion(self, cited_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app
        from hyperresearch.core.runs import load_manifest, manifest_path

        tag = "plain-status"
        _complete_profile(cited_vault, tag, "light")
        (cited_vault.run_dir(tag) / "final-cite-check-findings.json").unlink()
        monkeypatch.chdir(cited_vault.root)
        runner = CliRunner()
        status = runner.invoke(app, ["run", "status", tag])
        assert status.exit_code == 0
        assert "final-audit" in status.stdout and "unverified" in status.stdout
        manifest = load_manifest(cited_vault, tag)
        manifest.pop("finalization_version")
        path = manifest_path(cited_vault, tag)
        path.write_text(json.dumps(manifest))
        before = path.read_bytes()
        for command in ("verify", "resume", "finish"):
            result = runner.invoke(app, ["run", command, tag])
            assert "diagnostic" in result.stdout.lower()
            assert path.read_bytes() == before

    def test_even_consistent_dropped_final_pairs_fail_actual_extraction(self, cited_vault):
        from hyperresearch.core.runs import finish_run

        tag = "dropped-final"
        _complete_profile(cited_vault, tag, "light")
        run = cited_vault.run_dir(tag)
        pairs = json.loads((run / "final-cite-check-pairs.json").read_text())
        pairs.update({"pairs": [], "selected_pair_ids": [], "unreviewed_pair_ids": [], "sampled_for_llm": [], "dangling": [],
                      "summary": {"total": 0, "needs_llm": 0, "dangling": 0, "selected": 0, "unreviewed": 0}})
        (run / "final-cite-check-pairs.json").write_text(json.dumps(pairs))
        (run / "final-cite-check-findings.json").write_text(json.dumps({"schema_version": 1,
            "report_revision": pairs["report_revision"], "selected_pair_ids": [], "results": [], "findings": []}))
        result = finish_run(cited_vault, tag)
        assert not result["verify"]["passed"]
        assert "actual report extraction" in next(c["detail"] for c in result["verify"]["checks"] if c["name"] == "finalization")

    @pytest.mark.parametrize("kind", ["config", "retraction", "quote-support"])
    def test_existing_blocking_gate_inputs_invalidate_done_receipt(self, cited_vault, kind):
        from hyperresearch.core.runs import finish_run, status_summary

        tag = "blocking-inputs"
        report = _complete_profile(cited_vault, tag, "light")
        if kind == "quote-support":
            report.write_text(report.read_text() + '\nEvidence says "Fundamental patterns for concurrent programming." [[concurrency]].\n')
            set_step(cited_vault, tag, "16", "running")
            set_step(cited_vault, tag, "16", "done")
            _write_supported_audit(cited_vault, tag, report, final=True)
        assert finish_run(cited_vault, tag)["verify"]["passed"]
        if kind == "config":
            with cited_vault.config_path.open("a") as config:
                config.write("\n[profile.light]\ncitation_density_min = 10000\n")
        elif kind == "retraction":
            cited_vault.db.execute("UPDATE notes SET is_retracted = 1 WHERE id = 'python-async-patterns'")
            cited_vault.db.commit()
        else:
            path = cited_vault.notes_dir / "concurrency.md"
            path.write_text(path.read_text().replace("Fundamental patterns for concurrent programming.", "The captured quotation was corrected."))
        assert status_summary(cited_vault, tag)["approval_current"] is False
        assert verify_run(cited_vault, tag)["passed"] is False

    @pytest.mark.parametrize("version", [True, False, "2", 2.0, 1, 3])
    def test_finalization_discriminator_is_strict_and_read_only(self, tmp_vault, version):
        from hyperresearch.core.runs import finish_run, manifest_path

        manifest = init_run(tmp_vault, "unknown-version", profile="light")
        manifest["finalization_version"] = version
        path = manifest_path(tmp_vault, "unknown-version")
        path.write_text(json.dumps(manifest))
        before = path.read_bytes()
        assert finish_run(tmp_vault, "unknown-version")["verify"]["passed"] is False
        assert path.read_bytes() == before
    def test_fake_finish_cannot_skip_polish_or_final_audit(self, tmp_vault):
        from hyperresearch.core.runs import finish_run

        TestFinishGate()._well_formed_light_run(tmp_vault, "missing-polish", complete=False)
        result = finish_run(tmp_vault, "missing-polish")
        assert result["verify"]["passed"] is False
        assert result["manifest"]["status"] == "blocked"

    def test_legacy_finish_is_read_only_diagnostic(self, tmp_vault):
        from hyperresearch.core.runs import finish_run, manifest_path

        TestFinishGate()._well_formed_light_run(tmp_vault, "legacy-diagnostic")
        path = manifest_path(tmp_vault, "legacy-diagnostic")
        manifest = json.loads(path.read_text())
        manifest.pop("finalization_version", None)
        path.write_text(json.dumps(manifest))
        before = path.read_bytes()
        result = finish_run(tmp_vault, "legacy-diagnostic")
        assert result["verify"]["passed"] is False
        assert path.read_bytes() == before

    def test_full_required_stages_include_initial_citation_review_in_order(self, tmp_vault):
        from hyperresearch.core.runs import _required_stage_ids

        manifest = init_run(tmp_vault, "fractional-required")
        stages = _required_stage_ids(manifest, tmp_vault.run_dir("fractional-required"), tmp_vault.config_path)
        assert stages[stages.index("14") + 1:stages.index("16")] == ["14.5", "15"]


class TestFinalizationAuditCorrections:
    @pytest.mark.parametrize("command", ["verify", "finish", "status", "resume"])
    def test_legacy_cli_does_not_access_database_property(self, tmp_vault, monkeypatch, command):
        from typer.testing import CliRunner

        from hyperresearch.cli import app
        from hyperresearch.core.runs import manifest_path
        from hyperresearch.core.vault import Vault

        tag = "legacy-no-access"
        TestFinishGate()._well_formed_light_run(tmp_vault, tag, complete=False)
        path = manifest_path(tmp_vault, tag)
        manifest = json.loads(path.read_text())
        manifest.pop("finalization_version")
        manifest["steps"]["14.5"] = {"status": "done"}
        path.write_text(json.dumps(manifest))
        calls = []

        def reject_database_access(vault):
            calls.append(vault.root)
            raise AssertionError("legacy diagnostics may not access Vault.db")

        monkeypatch.setattr(Vault, "db", property(reject_database_access))
        monkeypatch.chdir(tmp_vault.root)
        result = CliRunner().invoke(app, ["run", command, tag, "--json"])
        assert result.exit_code in (0, 1), result.exception
        assert calls == []
        if command in {"verify", "finish"}:
            data = json.loads(result.stdout)["data"]
            data = data["verify"] if command == "finish" else data
            by_name = {check["name"]: check for check in data["checks"]}
            assert by_name["cite-check-coverage"]["ok"] is False
            assert "database access" in by_name["cite-check-coverage"]["detail"]

    @pytest.mark.parametrize("command", ["verify", "finish", "status", "resume"])
    @pytest.mark.parametrize("db_state", ["old-schema", "missing-index", "missing-db"])
    @pytest.mark.parametrize("version", [None, True, 1, 3])
    def test_legacy_cli_diagnostics_never_open_or_change_database(self, tmp_vault, monkeypatch, command, db_state, version):
        import sqlite3

        from typer.testing import CliRunner

        from hyperresearch.cli import app
        from hyperresearch.core.runs import manifest_path

        tag = "legacy-database"
        report = TestFinishGate()._well_formed_light_run(tmp_vault, tag, complete=False)
        path = manifest_path(tmp_vault, tag)
        manifest = json.loads(path.read_text())
        if version is None:
            manifest.pop("finalization_version")
        else:
            manifest["finalization_version"] = version
        manifest["verify"] = {"passed": True, "at": "historical-receipt", "original": "preserve this stored receipt"}
        path.write_text(json.dumps(manifest))
        tmp_vault._conn.close()
        tmp_vault._conn = None
        if db_state == "missing-db":
            tmp_vault.db_path.unlink()
        else:
            with sqlite3.connect(tmp_vault.db_path) as connection:
                connection.execute("INSERT INTO _meta(key, value) VALUES ('legacy-sentinel', 'unchanged')")
                connection.execute("DROP INDEX IF EXISTS idx_notes_tier")
                if db_state == "old-schema":
                    connection.execute("UPDATE _meta SET value = '9' WHERE key = 'schema_version'")
            connection.close()
        before_db = tmp_vault.db_path.read_bytes() if tmp_vault.db_path.exists() else None
        before_db_files = {file: file.read_bytes() for file in tmp_vault.db_path.parent.glob(f"{tmp_vault.db_path.name}*")}
        before_artifacts = {file: file.read_bytes() for file in tmp_vault.run_dir(tag).rglob("*") if file.is_file()}
        before_artifacts[report] = report.read_bytes()
        monkeypatch.chdir(tmp_vault.root)
        result = CliRunner().invoke(app, ["run", command, tag, "--json"])
        assert result.exit_code in (0, 1), result.exception
        assert (tmp_vault.db_path.read_bytes() if tmp_vault.db_path.exists() else None) == before_db
        assert {file: file.read_bytes() for file in tmp_vault.db_path.parent.glob(f"{tmp_vault.db_path.name}*")} == before_db_files
        if db_state != "missing-db":
            with sqlite3.connect(f"file:{tmp_vault.db_path}?mode=ro", uri=True) as connection:
                assert connection.execute("SELECT value FROM _meta WHERE key = 'legacy-sentinel'").fetchone()[0] == "unchanged"
                assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'idx_notes_tier'").fetchone() is None
                if db_state == "old-schema":
                    assert connection.execute("SELECT value FROM _meta WHERE key = 'schema_version'").fetchone()[0] == "9"
            connection.close()
        after_artifacts = {file: file.read_bytes() for file in tmp_vault.run_dir(tag).rglob("*") if file.is_file()}
        after_artifacts[report] = report.read_bytes()
        assert after_artifacts == before_artifacts
        payload = json.loads(result.stdout)["data"]
        if command in {"verify", "finish"}:
            diagnostic = payload["verify"] if command == "finish" else payload
            assert diagnostic["passed"] is False and diagnostic["diagnostic_only"] is True
            by_name = {check["name"]: check for check in diagnostic["checks"]}
            assert by_name["required-headings"]["ok"] is True
            assert by_name["quote-integrity"]["ok"] is False
            assert "unavailable" in by_name["quote-integrity"]["detail"]
        elif command == "status":
            assert payload["approval_current"] is False
            assert payload["escalations"] is None
            assert "unavailable" in payload["escalations_diagnostic"]
        else:
            assert payload["action"] == "legacy-diagnostic" and payload["approval_current"] is False

    def test_shipped_instruction_structural_mirror_survives_renewed_completion(self, cited_vault):
        from hyperresearch.core.runs import finish_run

        tag = "structural-mirror"
        report = _complete_profile(cited_vault, tag)
        path = cited_vault.run_dir(tag) / "critic-findings-instruction.json"
        path.write_text(json.dumps({"critic_type": "instruction", "findings": [{
            "severity": "critical", "atomic_item": "required_section_headings[0]: ## Findings",
            "failure_mode": "wrong-order", "location": "",
            "issue": "Expected H2 at position 0: Findings. Got MISSING.",
            "requires_orchestrator_restructure": True,
        }]}))
        original = path.read_bytes()
        for step in ("14.5", "15", "16"):
            set_step(cited_vault, tag, step, "running")
            set_step(cited_vault, tag, step, "done")
        _write_supported_audit(cited_vault, tag, report, final=True)
        result = finish_run(cited_vault, tag)
        assert result["verify"]["passed"], [item for item in result["verify"]["checks"] if not item["ok"]]
        assert path.read_bytes() == original

    def test_finite_decimal_locus_scores_remain_supported(self, cited_vault):
        from hyperresearch.core.runs import finish_run

        tag = "decimal-locus"
        report = _complete_profile(cited_vault, tag)
        path = cited_vault.run_dir(tag) / "loci.json"
        path.write_text(json.dumps({"loci": [{"name": "Mechanism", "one_line": "A bounded mechanism", "rationale": "Synthetic evidence.",
            "flavor": "technical", "importance": 1.5, "uncertainty": 1, "disagreement": 1.25,
            "decision_impact": 1, "composite_score": 4.75, "source_budget": 0}]}))
        for step in ("14.5", "15", "16"):
            set_step(cited_vault, tag, step, "running")
            set_step(cited_vault, tag, step, "done")
        _write_supported_audit(cited_vault, tag, report, final=True)
        assert finish_run(cited_vault, tag)["verify"]["passed"]

    @pytest.mark.parametrize("field,bad", [
        ("importance", "high"), ("uncertainty", None), ("disagreement", True),
        ("decision_impact", float("nan")), ("composite_score", float("inf")),
        ("composite_score", float("-inf")), ("source_budget", 0.5),
    ])
    def test_locus_scores_reject_nonnumeric_or_nonfinite_values(self, tmp_path, field, bad):
        from hyperresearch.core.runs import RunError, _validate_output

        record = {"name": "Mechanism", "one_line": "A bounded mechanism", "rationale": "Synthetic evidence.",
                  "flavor": "technical", "importance": 1, "uncertainty": 1, "disagreement": 1,
                  "decision_impact": 1, "composite_score": 4, "source_budget": 0}
        record[field] = bad
        path = tmp_path / "loci.json"
        path.write_text(json.dumps({"loci": [record]}))
        with pytest.raises(RunError, match="finite numeric scores"):
            _validate_output(path, "loci")

    @pytest.mark.parametrize("role,changed", [
        ("depth", {}), ("instruction", {"requires_orchestrator_restructure": False}),
        ("instruction", {"atomic_item": "an ordinary atomic item"}),
        ("instruction", {"failure_mode": "missing"}), ("instruction", {"severity": "major"}),
        ("instruction", {"issue": ""}), ("instruction", {"recommendation": None}),
    ])
    def test_structural_mirror_exception_does_not_weaken_other_findings(self, tmp_path, role, changed):
        from hyperresearch.core.runs import RunError, _validate_output

        record = {"severity": "critical", "atomic_item": "required_section_headings[0]: ## Findings",
                  "failure_mode": "wrong-order", "location": "", "issue": "Required heading is missing.",
                  "requires_orchestrator_restructure": True, **changed}
        path = tmp_path / f"critic-findings-{role}.json"
        path.write_text(json.dumps({"critic_type": role, "findings": [record]}))
        with pytest.raises(RunError):
            _validate_output(path, "findings")
