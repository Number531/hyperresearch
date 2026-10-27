"""Synthetic recorded corpus judgments; no reviewer accuracy is inferred."""

from __future__ import annotations

import copy

import pytest

from hyperresearch.core.citation_contracts import CitationContractError


def _case(works=45, claims=30):
    """Explicit full-gear boundary fixture, with distinct works/propositions."""
    members, sources, qualifications, assertions, propositions = [], {}, [], [], []
    for index in range(works):
        note_id = f"source-{index}"
        body = f"Original experimental result {index} describes its own measured population."
        snapshot = {"path": f"research/notes/{note_id}.md", "revision": f"revision-{index}", "body_status": "available"}
        members.append({"note_id": note_id, "source_input": snapshot,
                        "metadata": {"title": f"Work {index}", "tags": ["synthetic"]},
                        "identity_hints": {"doi": None, "canonical_url": None, "body_digest": f"body-{index}"},
                        "membership": ["tagged"], "is_final_report": False})
        sources[note_id] = snapshot, body
        qualifications.append({"note_id": note_id, "source_revision": snapshot["revision"],
            "work_id": f"work-{index}", "mirror_group": f"mirror-{index}",
            "capture_kind": "original-full", "originality": "original", "relevance": "relevant",
            "substance": "adequate", "source_excerpt": body,
            "reason": "The synthetic author declares this distinct original result relevant and adequately captured.",
            "independence": {"outcome": "independent", "scope": "This work's own measured population only.",
                             "reason": "This synthetic work measures its own distinct population."}})
    for index in range(claims):
        note_id = f"source-{index % works}"
        assertion = {"assertion_id": f"assertion-{index}", "text": f"Distinct atomic result {index}.",
            "kind": "empirical", "material": True, "disposition": "supported",
            "evidence": [{"note_id": note_id, "source_revision": sources[note_id][0]["revision"],
                          "source_excerpt": sources[note_id][1]}]}
        assertions.append(assertion)
        propositions.append({"assertion_id": assertion["assertion_id"], "proposition_key": f"proposition-{index}",
            "evidence_scope": "independent-measurement", "reason": "The cited synthetic original directly supplies this bounded measurement."})
    corpus = {"schema_version": 1, "vault_tag": "synthetic", "requirements": {"gear": "full", "source_min": 45, "claims_min": 30},
              "members": members, "raw_claim_rows": [], "input_digest": "synthetic-corpus"}
    pairs = {"report_revision": "synthetic-report", "pairs": [{"note_id": "source-0"}] * 60, "corpus_inputs": corpus}
    semantic = {"units": [{"assertions": assertions}]}
    review = {"schema_version": 1, "report_revision": pairs["report_revision"], "corpus_input_digest": corpus["input_digest"],
        "reviewer": {"identity": "synthetic-author", "provenance_note": "Explicit fixture judgments; no model execution claimed."},
        "qualifications": qualifications, "propositions": propositions}
    return pairs, semantic, review, sources


def _validate(case):
    from hyperresearch.core.evidence import validate_corpus_review

    return validate_corpus_review(*case)


def test_default_full_boundary_separates_all_counters():
    case = _case()
    case[0]["corpus_inputs"]["raw_claim_rows"] = [{"note_id": "source-0", "claim_hash": "old-run-claim"}]
    before = copy.deepcopy(case)
    result = _validate(case)
    assert result == {"raw_notes": 45, "citation_pairs": 60, "raw_db_claims": 1,
                      "qualified_unique_works": 45, "independent_works": 45, "supported_atomic_units": 30,
                      "requirements": {"gear": "full", "source_min": 45, "claims_min": 30},
                      "judgment_status": "recorded-review-not-truth-proof"}
    assert case == before


@pytest.mark.parametrize("axis", ["source_min", "claims_min"])
def test_default_full_boundary_one_below_fails(axis):
    case = _case(works=44 if axis == "source_min" else 45, claims=29 if axis == "claims_min" else 30)
    with pytest.raises(CitationContractError, match=r"minimum|floor"):
        _validate(case)


@pytest.mark.parametrize("hint", ["doi", "canonical_url", "body_digest"])
def test_raw_notes_and_differently_named_mirrors_do_not_meet_quota(hint):
    case = _case()
    for member in case[0]["corpus_inputs"]["members"]:
        member["identity_hints"][hint] = "same-original"
    case[0]["corpus_inputs"]["raw_claim_rows"] = [{"note_id": f"source-{index}", "claim_hash": str(index)} for index in range(45)]
    with pytest.raises(CitationContractError, match=r"minimum|floor"):
        _validate(case)


def test_uncited_relevant_original_can_meet_source_floor():
    case = _case()
    cited = {entry["note_id"] for unit in case[1]["units"] for assertion in unit["assertions"] for entry in assertion["evidence"]}
    assert "source-44" not in cited
    assert _validate(case)["qualified_unique_works"] == 45


def test_repeated_citations_and_identical_propositions_cannot_inflate_claims():
    case = _case()
    for assertion in case[1]["units"][0]["assertions"]:
        assertion["text"] = "The SAME bounded fact."
    with pytest.raises(CitationContractError, match=r"minimum|floor"):
        _validate(case)


def test_reviewed_paraphrase_identity_is_deduplicated():
    case = _case()
    for proposition in case[2]["propositions"]:
        proposition["proposition_key"] = "one-reviewed-proposition"
    with pytest.raises(CitationContractError, match=r"minimum|floor"):
        _validate(case)


@pytest.mark.parametrize("first,second", [
    ("The measured power was 1 mW.", "The measured power was 1 MW."),
    ("The documented API method is Aa.", "The documented API method is aa."),
])
def test_meaningful_case_distinguishes_reviewed_atomic_propositions(first, second):
    case = _case()
    assertions = case[1]["units"][0]["assertions"]
    assertions[0]["text"], assertions[1]["text"] = first, second
    assert case[2]["propositions"][0]["proposition_key"] != case[2]["propositions"][1]["proposition_key"]
    assert _validate(case)["supported_atomic_units"] == 30


@pytest.mark.parametrize("run_scope", ["canonical-run", "run-alias"])
def test_synced_current_tag_alias_is_a_valid_read_only_corpus_member(tmp_vault, run_scope):
    from hyperresearch.core.citation_contracts import corpus_inputs
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    tmp_vault.db.execute("INSERT INTO tag_aliases (alias, canonical) VALUES (?, ?)", ("run-alias", "canonical-run"))
    tmp_vault.db.commit()
    write_note(tmp_vault.notes_dir, "Aliased Original", body="A synthetic adequately captured original body.", tags=["run-alias"])
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    assert tmp_vault.db.execute("SELECT tag FROM tags WHERE note_id = 'aliased-original'").fetchone()["tag"] == "canonical-run"
    before = tmp_vault.db.total_changes
    corpus = corpus_inputs(tmp_vault, run_scope, "", {"gear": "full", "source_min": 1, "claims_min": 0}, [])
    assert [member["note_id"] for member in corpus["members"]] == ["aliased-original"]
    assert corpus["members"][0]["membership"] == ["tagged"]
    assert tmp_vault.db.total_changes == before


def test_unsynced_current_tag_alias_still_fails_closed_without_writes(tmp_vault):
    from hyperresearch.core.citation_contracts import corpus_inputs
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    tmp_vault.db.execute("INSERT INTO tag_aliases (alias, canonical) VALUES (?, ?)", ("run-alias", "canonical-run"))
    tmp_vault.db.commit()
    path = write_note(tmp_vault.notes_dir, "Unsynced Aliased Original", body="A captured original body.", tags=["other-run"])
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    path.write_text(path.read_text().replace("- other-run", "- run-alias"))
    before = tmp_vault.db.total_changes
    with pytest.raises(CitationContractError, match="drift"):
        corpus_inputs(tmp_vault, "canonical-run", "", {"gear": "full", "source_min": 1, "claims_min": 0}, [])
    assert tmp_vault.db.total_changes == before


def test_different_citation_markers_do_not_make_identical_atomic_facts_distinct():
    case = _case()
    for index, assertion in enumerate(case[1]["units"][0]["assertions"]):
        marker = f"[[source-{index}]]" if index % 2 else f"[{index + 1}]"
        assertion["text"] = f"The same bounded fact {marker}."
        case[0]["pairs"][index] = {"note_id": f"source-{index}", "citation": marker}
    with pytest.raises(CitationContractError, match="minimum"):
        _validate(case)


def test_grouped_citations_do_not_inflate_facts_and_meaningful_numbers_remain():
    from hyperresearch.core.evidence import _normalized

    citations = {"[1]", "[2]", "[[source-a]]"}
    assert _normalized("A 5 percent fact [1, 2].", citations) == _normalized("A 5 percent fact [[source-a]].", citations)
    assert _normalized("A 5 percent fact [1].", citations) != _normalized("A 6 percent fact [2].", citations)


def test_supported_source_dependent_derivations_count_atomic_units():
    case = _case()
    for assertion in case[1]["units"][0]["assertions"]:
        assertion.update(kind="derived", derivation={"source_dependent": True})
    assert _validate(case)["supported_atomic_units"] == 30


def test_shared_titles_alone_do_not_collapse_distinct_works():
    case = _case()
    for member in case[0]["corpus_inputs"]["members"]:
        member["metadata"]["title"] = "Shared title and authors are not a deterministic identity tie"
    assert _validate(case)["qualified_unique_works"] == 45


def test_conflicting_mirror_independence_is_conservative():
    case = _case(works=46)
    case[2]["qualifications"][-1]["mirror_group"] = case[2]["qualifications"][0]["mirror_group"]
    case[2]["qualifications"][-1]["independence"]["outcome"] = "derivative"
    result = _validate(case)
    assert result["qualified_unique_works"] == 45
    assert result["independent_works"] == 44


def test_verification_url_hints_preserve_meaningful_case_and_query_values():
    from hyperresearch.core.citation_contracts import _corpus_canonical_url

    normalize = _corpus_canonical_url
    assert normalize("HTTPS://EXAMPLE.COM/Work?source=A&ref=One&utm_source=x&gclid=tracking#section") == "https://example.com/Work?source=A&ref=One"
    assert normalize("https://example.com/Work?source=A") != normalize("https://example.com/work?source=A")
    assert normalize("https://example.com/Work?source=A") != normalize("https://example.com/Work?source=a")
    assert normalize("https://example.com/Work?ref=A") != normalize("https://example.com/Work?ref=B")


def test_source_body_identity_hints_preserve_meaningful_case_and_compatibility_characters(tmp_vault):
    from hyperresearch.core.citation_contracts import corpus_inputs
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    for index, body in enumerate(("Case matters in DNA Aa and Unit ①.", "Case matters in DNA aa and Unit 1.")):
        write_note(tmp_vault.notes_dir, f"Distinct Body {index}", body=body, tags=["identity-case"])
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    corpus = corpus_inputs(tmp_vault, "identity-case", "", {"gear": "full", "source_min": 2, "claims_min": 0}, [])
    assert len({member["identity_hints"]["body_digest"] for member in corpus["members"]}) == 2


def test_abstract_bounded_fact_counts_atomic_unit_but_not_original_quota():
    case = _case(works=46)
    qualification = case[2]["qualifications"][0]
    qualification["capture_kind"] = "original-abstract"
    case[2]["propositions"][0]["evidence_scope"] = "bounded-abstract"
    result = _validate(case)
    assert result["qualified_unique_works"] == 45
    assert result["supported_atomic_units"] == 30
    case[0]["corpus_inputs"]["requirements"]["source_min"] = 46
    with pytest.raises(CitationContractError, match=r"minimum|floor"):
        _validate(case)


@pytest.mark.parametrize("capture", ["metadata-only", "unknown"])
def test_material_metadata_or_unknown_support_blocks_despite_sufficient_other_evidence(capture):
    case = _case(works=46, claims=31)
    case[2]["qualifications"][0]["capture_kind"] = capture
    with pytest.raises(CitationContractError, match=r"material|eligible|support"):
        _validate(case)


def test_vendor_documentation_is_original_but_not_independent_measurement():
    case = _case()
    case[2]["qualifications"][0]["independence"]["outcome"] = "first-party"
    with pytest.raises(CitationContractError, match=r"independent|eligible|support"):
        _validate(case)
    case[2]["propositions"][0]["evidence_scope"] = "original-document"
    result = _validate(case)
    assert result["qualified_unique_works"] == 45
    assert result["independent_works"] == 44


def test_secondary_attribution_can_support_bounded_scope_without_original_quota():
    case = _case(works=46)
    case[2]["qualifications"][0].update(capture_kind="secondary", originality="secondary")
    case[2]["propositions"][0]["evidence_scope"] = "secondary-attribution"
    assert _validate(case)["supported_atomic_units"] == 30


@pytest.mark.parametrize("mutation", ["missing-review", "missing-member", "duplicate-member", "stale-source", "metadata-passage",
                                     "missing-work", "missing-mirror", "missing-reason", "missing-independence-scope", "missing-proposition", "stale-proposition", "final-report"])
def test_incomplete_or_stale_corpus_judgments_fail(mutation):
    case = list(_case())
    qualification = case[2]["qualifications"][0]
    if mutation == "missing-review":
        case[2] = None
    elif mutation == "missing-member":
        case[2]["qualifications"].pop()
    elif mutation == "duplicate-member":
        case[2]["qualifications"].append(copy.deepcopy(qualification))
    elif mutation == "stale-source":
        qualification["source_revision"] = "old"
    elif mutation == "metadata-passage":
        qualification["source_excerpt"] = "title: Work 0"
    elif mutation == "missing-work":
        qualification.pop("work_id")
    elif mutation == "missing-mirror":
        qualification.pop("mirror_group")
    elif mutation == "missing-reason":
        qualification["reason"] = ""
    elif mutation == "missing-independence-scope":
        qualification["independence"].pop("scope")
    elif mutation == "missing-proposition":
        case[2]["propositions"].pop()
    elif mutation == "stale-proposition":
        case[2]["propositions"][0]["assertion_id"] = "old"
    else:
        case[0]["corpus_inputs"]["members"][0]["is_final_report"] = True
    with pytest.raises(CitationContractError):
        _validate(case)


@pytest.mark.parametrize("kind", ["proposal", "design-parameter", "capture-gap", "derived"])
@pytest.mark.parametrize("attached_evidence", [False, True])
def test_uncited_proposals_parameters_gaps_and_source_free_math_are_not_supported_units(kind, attached_evidence):
    case = _case()
    for assertion in case[1]["units"][0]["assertions"]:
        assertion.update(kind=kind, derivation={"source_dependent": False})
        if not attached_evidence:
            assertion["evidence"] = []
    case[2]["propositions"] = []
    with pytest.raises(CitationContractError, match=r"minimum|floor"):
        _validate(case)
