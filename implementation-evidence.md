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

## P1 baseline and readiness

Exact clean phase base: `4fe696179aef6aac01a830659b4f3d6dbb521c42`.
Readiness CLI: `phase-dependency-readiness-v1`, ready true for phase 1,
current parsed-plan SHA/current HEAD/P0 checks and zero-finding audit bound.
An initial Node import wrapper failed before invoking that CLI; read-only
baseline checks started before the wrapper was corrected. The actual CLI
passed before any P1 implementation/test edit. No source or research mutation
occurred during that procedural correction.

- P1-REGRESSION: `python -m pytest tests/test_core/ -q` passed, 85.148s.
- P1-LINT: `python -m ruff check .` passed, 0.190s.

Logs: `checks/P1/baseline/`. No new core failure relative to initial full-suite
baseline. P1 remains inside existing final citation artifacts and gate seams.

## P1 implementation and checks

P1-D1 requires comprehensive final pairs, complete unit/span coverage and
explicit atomic dispositions/task-method judgments inside existing final
findings. Source evidence is current, literal and bound to local report
citations. Legacy extraction refuses before synchronization. Quote acceptance
uses cited bodies; exact resolved bibliography titles are identity metadata.
One final checker owns the whole report; shard merging preserves that review.

Behavioral red `P1/red/COVERAGE-GUARDS`: all four intended false acceptances
reproduced, exit 1, 2.418s. Initial focused check exposed two existing fixtures
which depended on the old FTS quote helper/uncited positive quote. Updated
them to the new current helper and actual cited-file mutation; no guard was
waived. Original failures and two import-format lint failures are retained.

P1-REGRESSION (`python -m pytest tests/test_core/ -q`) passed, 69.053s.
Only test import formatting changed afterward; focused changed-module check
passed all 62 cases in 3.287s. P1-LINT passed, 0.082s. See
`checks/P1/final/REGRESSION/` and `checks/P1/close/`. No new core failures.
Recorded classifications, atomization, entailment and reviewer identity remain
judgments, not machine-certified truth/independence. P2 quotas are not yet
implemented. Independent phase audit follows the local checkpoint.

P1 checkpoint: `b24da9b046e5c662ddd3b45dfbcbc64372b772ef`.
Fresh auditor `semantic_p1_phase_audit` reviewed the complete range, tests,
instructions and original results; zero critical/major/minor findings. Its
independent selection ran on the clean audited checkpoint: 42 passed, exit 0,
2.901s (`checks/P1/audit/INDEPENDENT-PROBES/output.log`). Parent reconciled and
accepted P1, retaining the recorded-judgment limitations. P2 was excluded.

## P2 baseline and readiness

Exact clean phase base: `2548034240ba2aa137ed6a5a3fc332c74e1a8372`.
Readiness CLI: `phase-dependency-readiness-v1`, ready true for phase 2,
both prerequisite phase checks and zero-finding audits bound to current plan
and HEAD before P2 work. P2-REGRESSION (`python -m pytest tests/test_core/ -q`)
passed in 70.631s; P2-LINT (`python -m ruff check .`) passed in 0.188s.
Logs: `checks/P2/baseline/`. No new core failure.

Numeric policy retains the existing scale gear (`manifest.profile`); frozen
pipeline tier controls stages. Freeze that gear's configured evidence floors
at stage 1; explicit task requirements may raise them, never lower them.
Qualified counts use reviewed current corpus/propositions, not raw DB rows.
All additions remain within existing final pairs/findings and verification
inputs; no research, migration, new artifact, ledger or independence DB write.

## P2 implementation and checks

P2-D1 adds fresh read-only corpus membership/body/metadata inputs, including
uncited tagged originals and explicit citation/bibliography reuse. The existing
final findings carries complete qualification/proposition records. Review-based
unique works and distinct evidence-backed atomic propositions meet separate
configured floors; raw notes/pairs/DB claims and independent works are separate
metrics. DOI/URL/body and reviewed identities collapse mirrors; citation-free
proposition text plus reviewed keys prevents repeated markers/facts inflating
units. Bounded abstract support, original excerpts, secondary attribution and
first-party documents have explicit distinct scopes.

Behavioral red `P2/red/QUALITY-FLOORS`: 12 intended failures, 2.943s,
including raw-quota acceptance, ignored requirement freeze, invalid minima
and five stale uncited-corpus approvals. Pure validator tests cover full 45/30
boundaries and one-below controls. Fixture floors are explicit synthetic1/1
overlays; an existing configured90 test now correctly rejects one source.

Early focused run found a duplicate synthetic profile table in a mutation
fixture; fixed table insertion while preserving its density-change assertion.
Nine raw-regex strings and one import-format lint issue were corrected. A
premier prompt assertion retained its exact130 scale phrase after revised
qualification wording. Original failed command logs are retained.

Mapped producer seam: package `hyperresearch-1-decompose.md` documents explicit
task raises at the step which writes them, extending planned entry/freeze
instructions within P2. No global installed skill changes. Mapped backward
P1 seam: stable finding P1-Q-LONG, current quote regex inherited a600-character
limit. Tests reproduced two false passes (1.044s); the first bounded correction
adds an unbounded matcher only to current citation-local verification. Legacy
FTS diagnostics are unchanged. Fresh phase audit must close P1-Q-LONG.

Final P2-REGRESSION (`python -m pytest tests/test_core/ -q`) passed,73.422s;
P2-LINT passed,0.137s (`checks/P2/close/`). No new core failure against phase
baseline. Independent audit follows the local checkpoint. Originality,
relevance, semantic support and reviewer independence remain recorded judgments.

P2 initial checkpoint: `6f94ee4f565663e5f68c51da063729aec07224a7`.
Fresh auditor `semantic_p2_phase_audit` reviewed the full range and read its
independent clean-checkpoint probe receipt: 61 passed, exit0,4.172s. It closed
P1-Q-LONG: current long-quote checks fixed, legacy diagnostic unchanged.
Additional auditor-selected tests reproduced two major false-rejection defects:
P2-SI-CASE, mW/MW and Aa/aa facts collapsed to29/30 by casefold; and
P2-TAG-ALIAS, native-synced tag alias falsely reported metadata drift.
All3 new cases were red in0.932s (`checks/P2/audit-red/CASE-AND-ALIAS/`).
P2 is not accepted while these findings remain. First bounded correction only:
preserve meaningful case/NFC while retaining exact-repeat/key dedup, and apply
native one-hop tag alias resolution read-only. No new authority or exception.
A separate correction checkpoint, affected gates and fresh audit are required.

First correction candidate for both P2 findings: NFC/case-preserving fact
identity and native one-hop alias comparisons, with exact-repeat/citation/key
dedup and unsynced-change refusal retained. Positive alias scopes and unsynced
negative fixtures also assert zero database changes. P2-REGRESSION passed,
79.807s; P2-LINT passed,0.201s (`checks/P2/correction1/`). No source/test changes
after these gates. This is one successful local correction candidate, pending
fresh independent closure; neither finding is waived or reclassified.

Correction checkpoint: `8ca38f20175469de55bea60e194030b77779cd74`.
The fresh re-auditor requested two additional permanent controls (tests only):
native a→b→c aliases stay one-hop without database retagging, and NFC/NFD
spellings of the same fact still deduplicate. Both passed before their test-only
checkpoint; Ruff passed. Product code remains identical to8ca38f2. The next
clean-checkpoint auditor selection includes these controls and all relevant
evidence/whole-report regressions before acceptance.

Fresh re-auditor `semantic_p2_remediation_audit` reviewed clean test checkpoint
`ae9ba1c89c85ee36e904ffce4139e42fed996503`, the full P2 range and first
correction. Its independent selection passed131 cases, exit0,5.896s on that
exact clean HEAD (`checks/P2/reaudit/INDEPENDENT-PROBES/`). It closed
P2-SI-CASE, P2-TAG-ALIAS and sustained P1-Q-LONG closure, with zero open
critical/major/minor findings. Parent reconciled the actual receipts and
accepted P2. All three phases are now accepted locally; final aggregate
comparison and final independent outcome verification remain outstanding.

## Final aggregate comparison

Clean tested checkpoint: `f30f7cfb0ffab52fc757b8231e9ea042b6b8071c`.
FINAL-TEST: `python -m pytest tests/ -q`, exit1,145.835s. Exact failed-ID set
matches the initial clean-base full suite: only the same two
`test_crawl4ai_running_loop.py` cases named above. Parent independently compared
both logs and confirmed the same `DNS lookup failed for 'example.com'` error
fingerprint. No new failure; the suite is not represented as wholly green.
Logs: `checks/FINAL/candidate/FULL/`. Final Ruff passed,0.198s in the identical
isolated offline environment. No external research/model/search call was run.

The plan structural validator again returned ok:true, transfer-ready, no
findings, unchanged parsed-plan SHA82f96f43e72c1257671938283639dc9c09a34e678ec3c3a4f54ab40a4aab37fd.
Product source is identical to the reviewed8ca38f2 correction; later commits
added independent controls/evidence only. Main and origin/main remain at the
initialf8ccd081 base. The task branch is clean, with no history rewrite.

## Plan outcome

- Original objective: Implement the approved P0, P1 and P2 Hyperresearch semantic-verification hardening sequentially in a fresh workspace with offline tests and independent review, preserving historical results and existing worktrees.
- Result: Achieved for the approved scoped local implementation, confirmed by final independent verification.
- Acceptance: P0-AC-1, P1-AC-1 and P2-AC-1 satisfied;3/3. All phase checks and audits accepted, no open critical/major finding. The explicit aggregate no-new-failure criterion is satisfied with the two unchanged offline DNS failures disclosed.
- Material deviations: current fresh base already contained upstream PR2–4, so overlapping gates were preserved rather than reimplemented. Producer step1 and bounded P1-Q-LONG remediation mapped to the approved seams. The initial readiness-wrapper sequencing issue is disclosed above. No acceptance signal or preservation boundary was weakened.
- Deferred/unverified: real provider/model/research quality, reviewer truth and independent execution, semantic atomization/classification, and large real-vault performance were not tested. Recorded judgments remain distinct from automatic truth certification. No historical research replay, global installation, remote push/PR/merge or default-branch sync was performed or inferred.
- Rollback/handoff: ordinary reviewed correction/revert on this task branch only; no reset/clean/force. This local branch is the deliverable. Remote publication/integration needs separate action-scoped authority.

Final verifier `semantic_final_acceptance_verifier` inspected clean checkpoint
`665057d81dde81e490bfb3fed3e2b0411974b1c7`, the canonical plan, complete final
diff and evidence, phase/probe receipts and both aggregate logs. Verdict: pass
for all3 acceptance criteria; zero critical/major/minor verification findings.
It independently confirmed unchanged DNS failure IDs/fingerprint and the
declared no-new-failure criterion. Preservation/no-live/global/remote claims
are supported by execution evidence and changed-path inspection, not forensic
inspection of historical vaults or external state. This final evidence-only
checkpoint changes no product source, tests or previously validated outcome.

## Subsequent publication authorization

After the local handoff, the user explicitly approved pushing this P0–P2 branch,
opening its PR and merging with a merge commit after CI and independent review
pass. Exact binding: `Number531/hyperresearch`, head
`codex/hyperresearch-semantic-verification-20261027`, base `main`. All five
existing CI matrix jobs must succeed on the final head, and a fresh independent
PR audit must have no unresolved critical/major finding before merge. This
grant permits normal non-force task pushes and matching PR updates; no research
reruns, historical-result changes, dirty-worktree changes, local default-branch
sync, release, deployment or history rewrite. The original local-only handoff
and its failure receipts above remain historical evidence. No product or test
change accompanies this authorization record.
