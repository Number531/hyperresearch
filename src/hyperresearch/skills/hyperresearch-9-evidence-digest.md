---
name: hyperresearch-9-evidence-digest
description: >
  Step 9 of the hyperresearch V8 pipeline. Assembles the top load-bearing
  claims and verbatim quotes from the claims JSONs into
  research/runs/<vault_tag>/temp/evidence-digest.md — a single high-fidelity evidence
  index the draft sub-orchestrators read as primary evidence (higher
  fidelity than fetcher summaries). Invoked via <% if platform == "codex" %>step-file read<% else %>Skill tool<% endif %> from the
  entry skill (full tier).
---

# Step 9 — Evidence digest

**Tier gate:** Run for `full`. Skip for `light`.

**Goal:** assemble the top load-bearing claims and verbatim quotes from the claims JSONs into a single digest file the drafter reads as primary evidence — higher-fidelity than fetcher summaries.

---

## Recover state

Read these inputs:
- `research/runs/<vault_tag>/scaffold.md` — vault_tag
- `research/runs/<vault_tag>/prompt-decomposition.json` — atomic items, response_format, pipeline_tier
- All `research/runs/<vault_tag>/temp/claims-*.json` files
- `research/runs/<vault_tag>/temp/consensus-claims.json` (if step 3 ran)
- `research/runs/<vault_tag>/temp/contradiction-graph.json` (if step 3 ran)

---

## Procedure

1. **Read all claims files** from `research/runs/<vault_tag>/temp/claims-*.json` for every non-deprecated note tagged with the vault tag. If no claim files exist (e.g., fetchers didn't produce them), skip this step.

2. **Filter and rank.** Keep claims where `confidence` is `"high"` OR `evidence_type` is `"empirical"` or `"statistical"`. From the remainder, prefer claims with non-empty `numbers` arrays and non-empty `quoted_support`. Cap at **<< p.claims_cap|dash >> claims total** for `full` tier.

3. **Group by atomic item.** Match each surviving claim to the atomic item it is most relevant to based on **topic overlap** — do not rely on exact field matching. A claim about "United Health Group regulatory exposure" serves the atomic item "UNH risk factors" even though no field matches exactly. Use the claim's `entities`, `stance_target`, `scope_conditions`, and `claim` text holistically to judge relevance. When uncertain, include the claim under the most relevant item rather than dropping it to Ungrouped. Claims that genuinely don't map to any atomic item go into an "Ungrouped" section at the end.

4. **Include consensus and contested claims.**
   - If `research/runs/<vault_tag>/temp/consensus-claims.json` exists, include its claims marked as `[consensus]`.
   - If `research/runs/<vault_tag>/temp/contradiction-graph.json` exists, include the top 3–5 contested claim pairs with both sides' `quoted_support` passages.

5. **Write `research/runs/<vault_tag>/temp/evidence-digest.md`.** Format: one H3 per atomic item, bullet list of claims. Each bullet includes:
   - The `claim` text
   - The `quoted_support` verbatim passage (block-quoted)
   - The `source_note_id`

   Keep it scannable — this is an evidence index, not a narrative.

   Example:
   ```markdown
   ### Atomic item: Market growth in Southeast Asia

   - Annual growth rate of 12.4% in 2024 (empirical)
     > "Southeast Asian e-commerce GMV grew from $89B to $100B between 2023 and 2024, a 12.4% YoY expansion."
     [source-note-12]

   - Vietnam led by penetration rate (statistical)
     > "Vietnam reached 64% e-commerce penetration in 2024, the highest in SEA, surpassing Singapore (61%)."
     [source-note-19]
   ```

---

## Exit criterion

- `research/runs/<vault_tag>/temp/evidence-digest.md` exists
- Aim for at least << p.claims_min >> candidate claims for the installed scale gear;
  final acceptance uses the exact resolved evidence requirements
- Grouped by atomic item with verbatim quoted_support and source_note_id

If fewer candidates exist, include all of them and record the gap; final
evidence minima remain binding. Raw claim files/DB rows are an evidence index,
not supported atomic units. Explicit cross-run reuse reads claims by corpus
note identity, including their original run tags; never rewrite historical
claims or count every global row as current proof.

The existing final checker produces `corpus_review` in the same final findings
envelope as semantic_review. It maps current supported empirical and
source-dependent derived assertion IDs to distinct proposition keys, with
eligible literal body passages and scoped reasons. Repeated citations and
paraphrases of one proposition count once; proposals, parameters, capture gaps
and source-free arithmetic never count, even with incidental citations.
Abstract-level facts and explicit secondary attribution may support bounded
atomic facts without meeting the substantive-original source quota. Metadata
or unknown captures cannot clear material empirical support; vendor API docs
do not establish independent measured benchmarks. Use the exact stage-1
frozen numeric gear requirements, including explicit/configured raises,
not a universal claim threshold or the pipeline tier name. Report raw claims
separately from qualified works, independent works and supported atomic units.

---

## Next step

Return to the entry skill (`hyperresearch`). Invoke step 10:

```
<% if platform == "codex" %>cat .hyperresearch/codex/steps/hyperresearch-10-triple-draft.md<% else %>Skill(skill: "hyperresearch-10-triple-draft")<% endif %>
```

Step 10 is the most important step in the pipeline. Re-read the entry skill before invoking if needed — the triple-draft ensemble must spawn 3 draft-orchestrators for `full` tier.
