"""Synthetic evidence-binding tests, not a toy classifier or reviewer benchmark."""

from __future__ import annotations

import copy

import pytest

from hyperresearch.core.citation_contracts import (
    CitationContractError,
    report_revision,
    source_input,
)
from hyperresearch.core.citecheck import extract_pairs, write_pairs_file
from hyperresearch.core.semantic_review import (
    METHOD_DIMENSIONS,
    assertion_id,
    build_inventory,
    validate_review,
)


@pytest.fixture
def semantic_case(seeded_vault):
    text = "## Findings\nPython's async/await syntax enables concurrent I/O [[python-async-patterns]].\n"
    path = seeded_vault.notes_dir / "semantic.md"
    path.write_text(text)
    pairs = write_pairs_file(seeded_vault, "semantic", path, coverage_mode="comprehensive")
    pairs["finalization_inputs"] = {"input_digest": "synthetic-task-context"}
    pairs["semantic_inventory"] = build_inventory(text, pairs["report_revision"], pairs["pairs"])
    units = pairs["semantic_inventory"]["units"]
    heading, claim = units
    span = {key: claim[key] for key in ("start", "end", "text")}
    pair = pairs["pairs"][0]
    snapshot, _ = source_input(seeded_vault, pair["note_id"])
    assertion = {**span, "assertion_id": assertion_id(pairs["report_revision"], claim["unit_id"], **span),
        "kind": "empirical", "presentation": "evidence-backed", "material": True, "disposition": "supported",
        "reasoning": "The quoted original body directly describes syntax enabling concurrent I/O; it does not claim a speedup.",
        "task_fit": "The synthetic question requests this language's concurrency mechanism.",
        "scope": "Language syntax enabling concurrent I/O only, without a performance benchmark.",
        "method_scope": "This is a qualitative mechanism statement, with no cost or numerical inference.",
        "method_checks": {}, "evidence": [{"pair_id": pair["pair_id"], "note_id": pair["note_id"],
            "source_revision": snapshot["revision"],
            "source_excerpt": "Python's async/await syntax enables concurrent I/O.",
            "reasoning": "The source body explicitly states the same bounded enabling mechanism."}]}
    review = {"schema_version": 1, "report_revision": pairs["report_revision"],
        "inventory_digest": pairs["semantic_inventory"]["inventory_digest"],
        "finalization_input_digest": "synthetic-task-context",
        "reviewer": {"identity": "synthetic-reviewer", "scope": "whole-report",
            "provenance_note": "Declared test provenance; independent execution is not established."},
        "task_fit": {"outcome": "satisfactory", "reason": "The complete report answers the bounded synthetic mechanism question."},
        "method_review": {dimension: {"outcome": "not-applicable", "reason":
            f"The mechanism claim makes no {dimension} comparison or inference."} for dimension in METHOD_DIMENSIONS},
        "units": [{"unit_id": heading["unit_id"], "atomization_reason": "A structural heading names the section without asserting a result.",
            "assertions": [], "nonassertive_spans": [{**{key: heading[key] for key in ("start", "end", "text")},
                "reason": "Section label only; no substantive result is asserted."}]},
            {"unit_id": claim["unit_id"], "atomization_reason": "One enabling relation is asserted, with one citation; no comparative conjunction is present.",
             "assertions": [assertion], "nonassertive_spans": []}]}
    sources = {pair["note_id"]: source_input(seeded_vault, pair["note_id"])}
    return seeded_vault, text, pairs, review, sources


def _validate(case):
    _, text, pairs, review, sources = case
    return validate_review(text, pairs["report_revision"], pairs, review, sources)


def _with_report_content(case, content):
    """Author fresh synthetic report/context identities, retaining review fields."""
    vault, _, old_pairs, old_review, _ = case
    text = f"## Findings\n{content}\n"
    revision = report_revision(text.encode("utf-8"))
    actual = extract_pairs(text, vault.db, revision=revision, whole_report=True)
    sources = {}
    for pair in actual:
        if pair["note_id"]:
            sources[pair["note_id"]] = source_input(vault, pair["note_id"])
            pair["source_input"] = sources[pair["note_id"]][0]
    pairs = {**copy.deepcopy(old_pairs), "pairs": actual, "report_revision": revision}
    pairs["semantic_inventory"] = build_inventory(text, revision, actual)
    review = copy.deepcopy(old_review)
    review.update({"report_revision": revision, "inventory_digest": pairs["semantic_inventory"]["inventory_digest"]})
    for unit, recorded in zip(pairs["semantic_inventory"]["units"], review["units"], strict=True):
        recorded["unit_id"] = unit["unit_id"]
        span = {key: unit[key] for key in ("start", "end", "text")}
        for segment in recorded["assertions"] + recorded["nonassertive_spans"]:
            segment.update(span)
            if "assertion_id" in segment:
                segment["assertion_id"] = assertion_id(revision, unit["unit_id"], **span)
    return vault, text, pairs, review, sources


def test_complete_bound_review_is_read_only_and_honest(semantic_case):
    before = copy.deepcopy(semantic_case[1:])
    assert _validate(semantic_case) == {"units_reviewed": 2, "assertions_reviewed": 1,
                                       "judgment_status": "recorded-review-not-truth-proof"}
    assert semantic_case[1:] == before


def test_inventory_retains_every_content_kind_and_sources_tail(seeded_vault):
    text = ("# Topic\n\nA prose claim. Another clause.\n\n| Metric | Value |\n| change | -5bp |\n\n"
            "- A list claim.\n\n> A quotation claim.\n\n## Sources\n"
            "[1] Python Async Patterns. https://example.com/async\n"
            "The supposedly hidden result is 5% [[python-async-patterns]].\n")
    pairs = extract_pairs(text, seeded_vault.db, whole_report=True)
    inventory = build_inventory(text, "synthetic-revision", pairs)
    assert [unit["text"] for unit in inventory["units"]] == [line for line in text.splitlines() if line]
    assert {unit["kind"] for unit in inventory["units"]} == {"heading", "prose", "table", "list", "quote"}
    assert pairs[-1]["sentence"].startswith("The supposedly hidden")
    assert inventory["units"][-1]["context"]["heading_path"] == ["# Topic", "## Sources"]
    assert inventory["units"][-1]["context"]["pair_ids"] == [pairs[-1]["pair_id"]]


def test_leading_citation_with_url_in_body_is_not_a_bibliography_definition(seeded_vault):
    text = ("[1] Python enables concurrent I/O; see https://example.com/async\n\n"
            "## Sources\n[1] Python Async Patterns. https://example.com/async\n")
    pairs = extract_pairs(text, seeded_vault.db, whole_report=True)
    assert len(pairs) == 1
    assert pairs[0]["note_id"] == "python-async-patterns"
    assert pairs[0]["sentence"].startswith("[1] Python enables")


@pytest.mark.parametrize("mutation", [
    "absent", "version", "dropped-unit", "duplicate-unit", "dropped-assertion", "duplicate-assertion",
    "duplicate-span", "missing-nonassertive-reason", "missing-atomization", "wrong-text", "wrong-id",
    "inventory-drop", "stale-task", "stale-report", "stale-context", "no-materiality", "no-disposition",
    "no-reasoning", "no-scope", "no-task-fit", "no-method-scope", "no-reviewer", "no-rubric",
    "no-evidence", "uncited-empirical", "other-note", "misbound-pair", "stale-source", "frontmatter-only",
    "missing-passage-reason", "duplicate-passage",
])
def test_missing_dropped_or_misbound_review_fails(semantic_case, mutation):
    _, text, pairs, review, sources = semantic_case
    record = review["units"][1]
    assertion = record["assertions"][0]
    evidence = assertion["evidence"][0]
    if mutation == "absent":
        review = None
    elif mutation == "version":
        review["schema_version"] = True
    elif mutation == "dropped-unit":
        review["units"].pop()
    elif mutation == "duplicate-unit":
        review["units"].append(copy.deepcopy(record))
    elif mutation == "dropped-assertion":
        record["assertions"] = []
    elif mutation == "duplicate-assertion":
        record["assertions"].append(copy.deepcopy(assertion))
    elif mutation == "duplicate-span":
        record["nonassertive_spans"] = [{key: assertion[key] for key in ("start", "end", "text")} | {"reason": "Duplicate classification."}]
    elif mutation == "missing-nonassertive-reason":
        review["units"][0]["nonassertive_spans"][0]["reason"] = ""
    elif mutation == "missing-atomization":
        record["atomization_reason"] = ""
    elif mutation == "wrong-text":
        assertion["text"] = "A different assertion."
    elif mutation == "wrong-id":
        assertion["assertion_id"] = "assertion-v1:wrong"
    elif mutation == "inventory-drop":
        pairs["semantic_inventory"]["units"].pop()
    elif mutation == "stale-task":
        review["finalization_input_digest"] = "different-task"
    elif mutation == "stale-report":
        review["report_revision"] = "different-report"
    elif mutation == "stale-context":
        review["inventory_digest"] = "different-context"
    elif mutation.startswith("no-") and mutation not in {"no-evidence", "no-reviewer", "no-rubric"}:
        key = {"no-materiality": "material", "no-disposition": "disposition", "no-reasoning": "reasoning",
               "no-scope": "scope", "no-task-fit": "task_fit", "no-method-scope": "method_scope"}[mutation]
        assertion.pop(key)
    elif mutation == "no-reviewer":
        review.pop("reviewer")
    elif mutation == "no-rubric":
        review["method_review"].pop("signs")
    elif mutation == "no-evidence":
        assertion["evidence"] = []
    elif mutation == "uncited-empirical":
        evidence["pair_id"] = "uncited-source"
    elif mutation == "other-note":
        evidence["note_id"] = "rust-ownership"
    elif mutation == "misbound-pair":
        evidence["pair_id"] = "pair-v1:" + "0" * 64
    elif mutation == "stale-source":
        evidence["source_revision"] = "sha256:" + "0" * 64
    elif mutation == "frontmatter-only":
        evidence["source_excerpt"] = "Guide to async/await in Python"
    elif mutation == "missing-passage-reason":
        evidence["reasoning"] = ""
    elif mutation == "duplicate-passage":
        assertion["evidence"].append(copy.deepcopy(evidence))
    with pytest.raises(CitationContractError):
        validate_review(text, pairs["report_revision"], pairs, review, sources)


@pytest.mark.parametrize("disposition", ["partially-supported", "unsupported", "unknown"])
def test_all_material_nonsupported_judgments_block(semantic_case, disposition):
    semantic_case[3]["units"][1]["assertions"][0]["disposition"] = disposition
    with pytest.raises(CitationContractError, match="blocking"):
        _validate(semantic_case)


@pytest.mark.parametrize("dimension,reason", [
    ("signs", "The report says +255 but the original passage reports -255."),
    ("units", "The report writes 5bp while the original passage reports 5%."),
    ("denominators", "The report uses all participants; the source uses only eligible respondents."),
    ("measured_vs_reported", "The vendor reports a capability but no independent measurement is supplied."),
    ("api_vs_format", "A documented API endpoint does not establish native format support."),
    ("costs_eligibility_pit", "The reported return omits costs and uses future membership for eligibility."),
    ("method_feasibility", "The proposed method requires unavailable point-in-time inputs."),
    ("counterhypothesis", "The same observed change is consistent with the stated selection effect."),
])
def test_scoped_method_judgments_block_without_keyword_classification(semantic_case, dimension, reason):
    assertion = semantic_case[3]["units"][1]["assertions"][0]
    assertion["method_checks"] = {dimension: {"outcome": "concern", "reason": reason}}
    assertion["method_scope"] = f"Reviewer explicitly examined {dimension} for this supplied assertion."
    with pytest.raises(CitationContractError, match="blocking"):
        _validate(semantic_case)
    assertion["method_checks"][dimension] = {"outcome": "satisfactory", "reason": "The revised bounded statement now preserves the original passage's scope."}
    assert _validate(semantic_case)["assertions_reviewed"] == 1


@pytest.mark.parametrize("kind,presentation", [("proposal", "proposed"), ("design-parameter", "design-parameter"),
                                             ("capture-gap", "bounded-capture-gap"), ("derived", "derived")])
def test_explicit_nonempirical_and_pure_calculation_controls(semantic_case, kind, presentation):
    wording = {"proposal": "We propose testing a concurrency queue in a future experiment.",
               "design-parameter": "For the proposed design, set the initial queue capacity to 16 items.",
               "capture-gap": "Within this bounded capture, no comparative benchmark passage was retrieved; other sources remain unexamined.",
               "derived": "For stipulated design units, two units plus two units gives four units (2 + 2 = 4)."}
    case = _with_report_content(semantic_case, wording[kind])
    assertion = case[3]["units"][1]["assertions"][0]
    assertion.update({"kind": kind, "presentation": presentation, "evidence": [],
                      "scope": "Synthetic proposal/parameter/capture boundary only; no measured claim is presented.",
                      "reasoning": "The supplied fixture judgment explicitly treats this span as nonempirical.",
                      "nonempirical_basis": "A scoped design choice or bounded capture limitation; no empirical source support is claimed."})
    if kind == "derived":
        assertion["derivation"] = {"source_dependent": False, "premises": "Two stipulated design units plus two stipulated units.",
                                   "calculation": "2 + 2 = 4; arithmetic only, not a measured result."}
    case[3]["units"][1]["atomization_reason"] = "This line contains one explicitly scoped nonempirical proposal, parameter, capture boundary or arithmetic calculation."
    assert _validate(case)["assertions_reviewed"] == 1
    if kind == "derived":
        assertion["derivation"]["source_dependent"] = True
        with pytest.raises(CitationContractError, match="cited premises"):
            _validate(case)
    else:
        assertion["presentation"] = "evidence-backed"
        with pytest.raises(CitationContractError):
            _validate(case)


def test_citation_local_quotes_cannot_borrow_an_unrelated_note(seeded_vault):
    from hyperresearch.cli.lint import _check_cited_quote_integrity, _check_quote_integrity

    text = 'The source states "Python\'s async/await syntax enables concurrent I/O" [[rust-ownership]].'
    path = seeded_vault.notes_dir / "quotes.md"
    assert _check_quote_integrity(seeded_vault, seeded_vault.db, path, text) == []
    assert _check_cited_quote_integrity(seeded_vault, seeded_vault.db, path, text)
    assert _check_cited_quote_integrity(seeded_vault, seeded_vault.db, path,
        text.replace("[[rust-ownership]]", "[[python-async-patterns]]")) == []


@pytest.mark.parametrize("capture", ["absent", "wrong-cited-source"])
def test_long_quotes_cannot_bypass_current_citation_local_integrity(seeded_vault, capture):
    from hyperresearch.cli.lint import _check_cited_quote_integrity
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    quote = "A captured original passage describes a bounded qualitative mechanism with careful conditions " * 12
    quote = quote.strip()
    assert len(quote) > 600 and len(quote.split()) >= 5
    if capture == "wrong-cited-source":
        write_note(seeded_vault.notes_dir, "Unrelated Long Capture", body=quote)
        execute_sync(seeded_vault, compute_sync_plan(seeded_vault, force=True))
    text = f'The source states "{quote}" [[rust-ownership]].'
    issues = _check_cited_quote_integrity(seeded_vault, seeded_vault.db, "long-report.md", text)
    assert any(issue["rule"] == "quote-integrity" and issue["severity"] == "error" for issue in issues)


def test_long_literal_quote_in_current_locally_cited_body_passes(seeded_vault):
    from hyperresearch.cli.lint import _check_cited_quote_integrity
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    quote = "A captured original passage describes a bounded qualitative mechanism with careful conditions " * 12
    quote = quote.strip()
    write_note(seeded_vault.notes_dir, "Original Long Capture", body=quote)
    execute_sync(seeded_vault, compute_sync_plan(seeded_vault, force=True))
    text = f'The source states "{quote}" [[original-long-capture]].'
    assert _check_cited_quote_integrity(seeded_vault, seeded_vault.db, "long-report.md", text) == []


def test_quoted_bibliographic_identity_is_not_a_body_quotation(seeded_vault):
    from hyperresearch.cli.lint import _check_cited_quote_integrity

    title = "Python Async Patterns For Concurrent Input And Output"
    seeded_vault.db.execute("UPDATE notes SET title = ? WHERE id = 'python-async-patterns'", (title,))
    seeded_vault.db.execute(
        "INSERT INTO sources (url, note_id, domain, fetched_at, provider, content_hash) "
        "VALUES ('https://example.com/title', 'python-async-patterns', 'example.com', '2026-01-01', 'test', 'x')")
    seeded_vault.db.commit()
    # The title appears only in metadata, not in the original body.
    text = f'## Sources\n[1] "{title}" https://example.com/title\n'
    assert _check_cited_quote_integrity(seeded_vault, seeded_vault.db, "report.md", text) == []
    wrong_quote = '\nThe source states "Python\'s async/await syntax enables concurrent I/O" [[rust-ownership]].\n'
    assert _check_cited_quote_integrity(seeded_vault, seeded_vault.db, "report.md", text + wrong_quote)
    disguised = f'## Findings\n[1] "{title}" https://example.com/title\n'
    assert _check_cited_quote_integrity(seeded_vault, seeded_vault.db, "report.md", disguised)


def test_uncited_empirical_fact_is_not_a_supported_proposal(semantic_case):
    case = _with_report_content(semantic_case, "The measured throughput increased by 20%.")
    case[3]["units"][1]["assertions"][0]["evidence"] = []
    with pytest.raises(CitationContractError, match="empirical assertion requires cited"):
        _validate(case)


def test_atomic_span_partition_cannot_drop_one_clause(semantic_case):
    first = "Python's async/await syntax enables concurrent I/O [[python-async-patterns]]."
    second = "We propose evaluating a queue next."
    case = _with_report_content(semantic_case, first + " " + second)
    unit = case[2]["semantic_inventory"]["units"][1]
    recorded = case[3]["units"][1]
    empirical = recorded["assertions"][0]
    empirical.update({"text": first, "end": unit["start"] + len(first)})
    empirical["assertion_id"] = assertion_id(case[2]["report_revision"], unit["unit_id"],
                                             empirical["start"], empirical["end"], empirical["text"])
    # Rebind the empirical passage to the current citation occurrence.
    empirical["evidence"][0]["pair_id"] = case[2]["pairs"][0]["pair_id"]
    proposal = {**copy.deepcopy(empirical), "start": empirical["end"] + 1, "end": unit["end"],
                "text": second, "kind": "proposal", "presentation": "proposed", "evidence": [],
                "nonempirical_basis": "An explicitly proposed future evaluation, not an observed result."}
    proposal["assertion_id"] = assertion_id(case[2]["report_revision"], unit["unit_id"],
                                            proposal["start"], proposal["end"], proposal["text"])
    recorded["assertions"].append(proposal)
    recorded["atomization_reason"] = "The enabling mechanism and the proposed future test are separate assertions with separate spans and dispositions."
    assert _validate(case)["assertions_reviewed"] == 2
    recorded["assertions"].pop()
    with pytest.raises(CitationContractError, match="uncovered unit text"):
        _validate(case)


def test_report_qualifier_or_reference_remap_invalidates_review(semantic_case):
    _, text, pairs, review, sources = semantic_case
    for changed in (text.replace("enables", "always enables"), text.replace("python-async-patterns", "rust-ownership")):
        with pytest.raises(CitationContractError, match="inventory"):
            validate_review(changed, pairs["report_revision"], pairs, review, sources)


def test_nonmaterial_unknown_is_recorded_without_claiming_support(semantic_case):
    assertion = semantic_case[3]["units"][1]["assertions"][0]
    assertion.update({"material": False, "disposition": "unknown", "evidence": [],
                      "reasoning": "A peripheral interpretation has no supporting captured passage and is not used for the conclusion."})
    assert _validate(semantic_case)["judgment_status"] == "recorded-review-not-truth-proof"


def test_task_fit_cannot_be_declared_inapplicable(semantic_case):
    semantic_case[3]["task_fit"] = {"outcome": "not-applicable", "reason": "Attempt to skip the question fit judgment."}
    with pytest.raises(CitationContractError, match="always applies"):
        _validate(semantic_case)


@pytest.mark.parametrize("target,field,bad", [
    ("assertion", "kind", []), ("assertion", "presentation", {}),
    ("assertion", "disposition", True), ("assertion", "material", "yes"),
    ("evidence", "pair_id", []), ("task", "outcome", {}),
])
def test_wrong_types_are_contract_errors(semantic_case, target, field, bad):
    assertion = semantic_case[3]["units"][1]["assertions"][0]
    record = {"assertion": assertion, "evidence": assertion["evidence"][0],
              "task": semantic_case[3]["task_fit"]}[target]
    record[field] = bad
    with pytest.raises(CitationContractError):
        _validate(semantic_case)
