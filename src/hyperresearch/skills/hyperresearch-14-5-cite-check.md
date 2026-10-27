---
name: hyperresearch-14-5-cite-check
description: >
  Step 14.5 of the hyperresearch V8 pipeline (full + dissertation tiers).
  Verifies that each citation in the patched report actually supports its
  sentence: mechanical triage auto-passes pairs confirmed by the claims
  table, the cite-checker agent judges the sampled remainder, and a second
  small patcher pass applies the findings. Runs AFTER step 14 (the patcher
  moved text and citations; audit what will actually ship) and BEFORE step
  15 (polish sees the corrected text). Invoked via <% if platform == "codex" %>step-file read<% else %>Skill tool<% endif %>.
---

# Step 14.5 — Cite-check (citation-sentence binding verification)

**Tier gate:** Runs for `full` and `dissertation`. SKIP for `light` — a light report's citation volume doesn't justify the pass; the `quote-integrity` and `numeric-consistency` lint rules still cover it mechanically at the step-15 gate.

**Goal:** every citation that ships either supports its sentence or gets fixed. This is the difference between "has citations" and "citations are true bindings" — the single thing external fact-checkers actually measure.

---

## Recover state

Read these inputs:
- `research/runs/<vault_tag>/scaffold.md` — vault_tag
- `research/notes/final_report_<vault_tag>.md` — the PATCHED report from step 14

---

## Step 14.5.1 — Extract + mechanical triage

```bash
{hpr_path} citecheck extract <vault_tag> -j
```

This parses every (sentence, citation) pair from the report — `[N]` markers (including grouped `[7, 12]`, one pair per source number) and `[[note-id]]` styles — and auto-passes pairs whose numbers or wording the cited note's extracted claims already confirm. Output: `research/runs/<vault_tag>/cite-check-pairs.json` with:
- `summary` — total / auto-passed / dangling / needs-llm counts
- `schema_version: 1`, `report_revision` — SHA-256 of exact report bytes
- `pairs` — all original pairs, each with `pair_index`, `pair_id`, and `finding_id`
- `sampled_for_llm` — the pairs the agent must judge (100% of number-bearing sentences; sampled for the rest)
- `dangling` — citations that resolve to NO vault note

**Dangling citations are findings immediately** — no agent needed. Each one becomes a `critical` finding with `verdict: "dangling"`, copying its `pair_id`, `finding_id`, exact `sentence`, and `note_id` as `cited_note_id` (null). Set `correct_note_id: null` and include nonempty `evidence` and `suggested_fix` strings. These are fabricated or mangled citations.

**If `sampled_for_llm` is empty and there are no dangling citations:** write `{"schema_version": 1, "report_revision": "<copy from pairs file>", "findings": []}` to `research/runs/<vault_tag>/cite-check-findings.json`, record `{hpr_path} run step <vault_tag> 14.5 --status done -j`, and proceed to step 15. An explicit empty array is a valid zero-findings payload; it does not itself prove review coverage.

---

## Step 14.5.2 — Spawn the cite-checker

Spawn ONE `hyperresearch-cite-checker` subagent<% if platform == "codex" %> (custom agent `.codex/agents/hyperresearch-cite-checker.toml`)<% else %><% endif %> (two in parallel with split index ranges when `sampled_for_llm` exceeds ~40 pairs)<% if platform == "codex" %> and wait for it (or both) to finish<% else %><% endif %>:

```
<% if platform == "codex" %>custom_agent: hyperresearch-cite-checker   # spawn the custom agent defined in .codex/agents/hyperresearch-cite-checker.toml<% else %>subagent_type: hyperresearch-cite-checker<% endif %>
prompt: |
  RESEARCH QUERY (verbatim, gospel):
  > {{paste research/runs/<vault_tag>/query.md body}}

  QUERY FILE: research/runs/<vault_tag>/query.md

  PIPELINE POSITION: You are step 14.5 (cite-checker) of the hyperresearch
  V8 pipeline. Step 14's patcher already applied critic findings; you
  verify citation-sentence bindings on the text that will ship. Your
  findings feed a second, small patcher pass. You do not edit the report.

  YOUR INPUTS:
  - pairs_file: research/runs/<vault_tag>/cite-check-pairs.json
  - your_range: sampled_for_llm[<start>..<end>]
  - findings_path: research/runs/<vault_tag>/cite-check-findings.json
  - vault_tag: <vault_tag>
  - mode: findings
```

When splitting across two checkers, give each its own findings path (`cite-check-findings-a.json` / `-b.json`). Retain both files. Confirm both envelopes copy the same original `report_revision`, then merge their `findings` arrays into one version-1 envelope in `cite-check-findings.json`. Preserve identities and reject duplicate records. Every finding must match the original pairs file's exact sentence/note/identity; never hash the patched report as the original findings revision.

---

## Step 14.5.3 — Second patcher pass

Append the dangling-citation findings (from 14.5.1) to the envelope's `findings` array, then reuse the step 14 patching machinery: spawn ONE `hyperresearch-patcher` (<% if platform == "codex" %>read + patch only<% else %>tool-locked Read + Edit<% endif %>) with `research/runs/<vault_tag>/cite-check-findings.json` as its findings input and `research/runs/<vault_tag>/cite-check-patch-log.json` pre-stubbed:

```json
{"schema_version": 1, "findings_report_revision": "<copy original findings revision>", "reviewed_report_revision": null, "resolutions": [], "total_findings": 0, "applied": [], "skipped": [], "conflicts": [], "orchestrator_escalated": []}
```

Fix repertoire (in the findings' `suggested_fix`): swap to `correct_note_id`, soften the claim to what the source supports, or delete the sentence when nothing supports it. Same rules as step 14: surgical hunks, zero regeneration, `critical` findings must not be silently skipped.

The patcher records each `finding_id` in the application entries and preserves the revision fields. Applying or escalating a patch does not resolve a critical finding. The initial null review revision is intentionally unverified.

**Skip the pass entirely** when the merged envelope's `findings` is `[]`.

## Step 14.5.4 — Review critical resolutions

If any critical findings exist, spawn the `hyperresearch-cite-checker` again with `mode: resolution-review`, the original `pairs_file`, `findings_input_path: research/runs/<vault_tag>/cite-check-findings.json`, `draft_path: research/notes/final_report_<vault_tag>.md`, and the existing `patch_log_path: research/runs/<vault_tag>/cite-check-patch-log.json`. Wait for it to reread the patched report and relevant source bodies. It must preserve application data and populate:

```json
{
  "schema_version": 1,
  "findings_report_revision": "<original audit revision>",
  "reviewed_report_revision": "sha256:<hash of exact post-patch report bytes>",
  "resolutions": [
    {"finding_id": "<copy original finding_id>", "status": "resolved", "review_verdict": "supported", "evidence": "<what the reread report and source establish>"}
  ]
}
```

`claim-removed` is also a successful review verdict when the claim was actually removed. Otherwise use `status: "unresolved"`, `review_verdict: "unresolved"`, explain the blocker, and fix/review again before marking the step done. Every critical needs exactly one successful resolution; records for other known findings are permitted. Unknown or duplicate IDs, stale original/reviewed revisions, and `applied` entries alone fail the native gate. Use the checker's byte-hash procedure; the shared native identity API lives in `hyperresearch.core.citation_contracts`.

**After any subsequent report edit, including steps 15 (polish) and 16 (readability), repeat `resolution-review` for the original critical findings before `run finish`.** The reviewer must reread the current report and relevant source bodies, then record the current byte revision. Preserve the original findings/pairs and `findings_report_revision`; never restamp a receipt without review or edit the report merely to reproduce an old hash. This refresh covers those original critical resolutions; it does not establish comprehensive review of later citation changes.

Do not rewrite legacy findings or patch logs merely to make verification pass. Bare lists and legacy `{"findings": [...]}` remain read-only diagnostics; legacy nonempty findings cannot establish reviewed resolution.

---

## Exit criterion

- `research/runs/<vault_tag>/cite-check-pairs.json` exists
- `research/runs/<vault_tag>/cite-check-findings.json` is a valid versioned envelope (possibly `findings: []`) bound to the original pairs revision
- If any critical findings exist: `cite-check-patch-log.json` contains matching explicit successful resolution reviews bound to the current post-patch report bytes
- Manifest: `{hpr_path} run step <vault_tag> 14.5 --status done -j`

## Next step

Return to the entry skill and invoke `<% if platform == "codex" %>cat .hyperresearch/codex/steps/hyperresearch-15-polish.md<% else %>Skill(skill: "hyperresearch-15-polish")<% endif %>`.
