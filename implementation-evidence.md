# Implementation evidence

Approved local objective: implement P0, P1 and P2 sequentially, offline tests and
independent review, in this fresh clone. Preserve historical results; no research
reruns or local default-branch sync. No remote publication/merge authority is
inferred. Canonical plan: `reports/hyperresearch-semantic-verification-20261027/`
in the parent workspace; owning workflow/executor: executable-foundation-plan /
executable-foundation-plan-implementation.

## P0 baseline

Phase base: `f8ccd0818c5875d30e4dbc9891cf008800cda84b`.
Branch: `codex/hyperresearch-semantic-verification-20261027`.
Clean index/tracked tree confirmed before tests. Structural plan validation:
`ok: true`, no findings, canonical parsed-plan SHA
`82f96f43e72c1257671938283639dc9c09a34e678ec3c3a4f54ab40a4aab37fd`.

- P0-REGRESSION: `python -m pytest tests/test_core/test_verification.py tests/test_core/test_runs.py tests/test_core/test_profiles.py tests/test_core/test_citation_contracts.py tests/test_core/test_prompt_golden.py tests/test_core/test_codex_skill_templates.py -q` passed, 73.943s.
- P0-LINT: `python -m ruff check .` passed, 0.711s.
- Initial aggregate baseline: `python -m pytest tests/ -q`, exit 1, 196.599s.
  Exactly two failures in `tests/test_web/test_crawl4ai_running_loop.py`:
  `test_fetch_succeeds_when_called_from_a_running_event_loop` and
  `test_fetch_still_succeeds_with_no_running_loop`. Both require DNS for
  `example.com`, unavailable in the enforced offline sandbox. No waiver of
  semantic acceptance tests is made; final suite must have no new failures.

Commands use a new dependency venv, copied offline cache, isolated HOME/XDG/temp,
credential-free environment and enforced external-network denial. Setup first
failed for missing editable-build support; installing cached `editables` and
retrying the offline editable install succeeded. Original setup failure retained
in fresh workspace checks. No product dependency configuration changed.

Current-base reconciliation: preserve already merged PR2–4 contracts. P0 extends
their existing finalization seam; P1's pure validator extends existing final
findings, and P2's pure validator extends existing pairs/findings. These are
within the approved seams, not a new workflow, harness or result ledger.

Fresh planning auditor `semantic_execution_plan_review` inspected the current
plan and source seams: no critical/major/minor planning findings. Its review did
not execute tests; the above baselines were executed and reconciled by parent.
No source implementation preceded structural validation and this review.

## P0 implementation and checks

P0-D1 adds fresh policy v2, reviewed major/critical resolution, frozen route,
exact chapter obligation partition, and refusal of noncurrent mutations before
database access. Chapter references are aligned with verbatim values in the
existing plan envelope because decomposition has categorized obligations, not
a single atomic-items list. No new artifact or workflow was introduced.

Behavioral red probes on prior implementation: `P0/red/GUARDS` (11.257s),
`P0/red/LEGACY-WRITES` (1.666s, all 18 API/CLI cases), and
`P0/red/JSON-TYPES` (0.934s). All reproduced their intended false acceptances.
Positive critical, minor-only and one-chapter controls remained covered.

Final same-source-tree validation in `checks/P0/final/`:
P0-REGRESSION passed (50.716s), P0-LINT passed (0.189s). No new targeted
failures against the clean phase baseline. Earlier successful candidate
checks and original failures remain retained. Independent phase audit follows
the normal local implementation checkpoint; P1 cannot begin until it clears.

P0 checkpoint: `6a34f5d4849381632b79f8c24f98ee43e9759ac6`.
Fresh auditor `semantic_p0_phase_audit` reviewed that range, source, prompts,
tests and original red/final results; zero critical/major/minor findings.
Its independent test selection ran on the clean checkpoint: 28 passed,
exit 0 in 3.228s (`checks/P0/audit/INDEPENDENT-PROBES/output.log`). The parent
reconciled that result and accepted P0. No semantic truth or producer
independence is certified. P1/P2 were explicitly excluded from this audit.
