"""Cite-check — does each citation actually support its sentence?

The FACT half of research quality, self-measured before ship instead of by
an external benchmark. Three layers:

1. `extract_pairs(report_text, conn)` — pure parsing. Splits the report into
   sentences and binds each citation marker to its sentence, for BOTH
   citation styles: numbered `[N]` (resolved through the `## Sources`
   section) and `[[note-id]]` wikilinks.

2. `triage_pairs(pairs, conn)` — mechanical routing hints. Numeric or word
   overlap identifies candidate evidence only; every resolved pair still
   needs semantic judgment by the cite-checker agent.

3. The `hyperresearch-cite-checker` agent (step 14.5) verifies the
   selected pairs against actual note bodies and emits explicit results and findings the
   patcher applies. Verdicts: supported | partially-supported |
   unsupported | wrong-source.
"""

from __future__ import annotations

import json
import re

from hyperresearch.core.citation_contracts import (
    CONTRACT_VERSION,
    finding_id,
    pair_id,
    report_revision,
    source_input,
)
from hyperresearch.core.patterns import WIKI_LINK_RE

# Sentence split: period/question/exclamation followed by space+capital, or newline.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z一-鿿])|\n+")
_NUMBERED_CITE_RE = re.compile(r"(?<!\[)\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\])")
_SOURCES_ENTRY_RE = re.compile(r"^\s*\[(\d{1,3})\]\s+(.+)$")
_NUMBER_RE = re.compile(r"[+\-−]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)%?")

# Sentences carrying these are checked at 100% regardless of sampling.
_STRONG_MARKERS = ("%", "$", "billion", "million", "increase", "decrease", "grew", "fell")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def sentence_routing(sentence: str) -> tuple[list[str], bool]:
    """Preserve signed numeric tokens for routing, without interpreting metrics.

    Citation marker numbers and note identifiers are not claim quantities.
    Neither a matching token nor a shingle establishes entailment.
    """
    text = WIKI_LINK_RE.sub("", _NUMBERED_CITE_RE.sub("", sentence))
    numbers = _NUMBER_RE.findall(text)
    return numbers, bool(numbers) or any(k in text.lower() for k in _STRONG_MARKERS)


def parse_sources_section(report_text: str, conn) -> dict[str, str | None]:
    """Map `[N]` -> note_id by matching Sources-section URLs/titles to the vault."""
    mapping: dict[str, str | None] = {}
    in_sources = False
    for line in report_text.splitlines():
        if re.match(r"^##\s+(Sources|References)\b", line, re.IGNORECASE):
            in_sources = True
            continue
        if in_sources and line.startswith("## "):
            break
        if not in_sources:
            continue
        m = _SOURCES_ENTRY_RE.match(line)
        if not m:
            continue
        num, rest = m.group(1), m.group(2)
        note_id = None
        url_m = re.search(r"https?://\S+", rest)
        if url_m:
            url = url_m.group(0).rstrip(".,)")
            row = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
            if row:
                note_id = row["note_id"]
        if note_id is None:
            title = rest.split("http")[0].strip(" .–-")
            if title:
                row = conn.execute(
                    "SELECT id FROM notes WHERE title = ? COLLATE NOCASE", (title,)
                ).fetchone()
                if row:
                    note_id = row["id"]
        mapping[num] = note_id
    return mapping


def extract_pairs(
    report_text: str, conn, *, revision: str | None = None, whole_report: bool = False,
) -> list[dict]:
    """All (sentence, note_id) citation bindings in the report.

    Pairs whose citation can't be resolved to a vault note get
    note_id=None — those are findings in themselves (dangling citation).
    """
    revision = revision or report_revision(report_text.encode("utf-8"))
    numbered_map = parse_sources_section(report_text, conn)
    known_ids = {row["id"] for row in conn.execute("SELECT id FROM notes")}

    # Initial repair diagnostics retain their historical body boundary. Final
    # extraction includes reference-section prose; a heading cannot hide claims.
    body = report_text if whole_report else re.split(
        r"^##\s+(?:Sources|References)\b", report_text, maxsplit=1, flags=re.M | re.I,
    )[0]
    headings = list(re.finditer(r"^##\s+(.+)$", body, flags=re.M))
    reference_ranges = [(heading.start(), headings[index + 1].start() if index + 1 < len(headings) else len(body))
                        for index, heading in enumerate(headings)
                        if re.match(r"(?:Sources|References)\b", heading[1], re.I)]

    pairs: list[dict] = []
    boundaries = [0] + [match.end() for match in _SENTENCE_SPLIT_RE.finditer(body)]
    ends = [match.start() for match in _SENTENCE_SPLIT_RE.finditer(body)] + [len(body)]
    for raw_start, raw_end in zip(boundaries, ends, strict=True):
        raw = body[raw_start:raw_end]
        sentence = raw.strip()
        if not sentence:
            continue
        start = raw_start + len(raw) - len(raw.lstrip())
        end = raw_end - len(raw) + len(raw.rstrip())
        cited: list[tuple[int, str | None, str]] = []
        for m in _NUMBERED_CITE_RE.finditer(sentence):
            # A leading reference-list declaration is a bibliography label,
            # not a citation occurrence. Its full line is still inventoried
            # and must receive explicit semantic classification/review.
            if (whole_report and m.start() == 0 and _SOURCES_ENTRY_RE.match(sentence)
                    and "http" in sentence and any(begin <= start < stop for begin, stop in reference_ranges)):
                continue
            for num in re.split(r"\s*,\s*", m.group(1)):
                target = numbered_map.get(num)
                cited.append((m.start(), target if target in known_ids else None, f"[{num}]"))
        for m in WIKI_LINK_RE.finditer(sentence):
            target = m.group(1).strip()
            cited.append((m.start(), target if target in known_ids else None, m.group(0)))
        numbers, strong = sentence_routing(sentence)
        for _, note_id, citation in sorted(cited, key=lambda item: item[0]):
            index = len(pairs)
            identity = pair_id(revision, index, sentence, note_id)
            pairs.append({
                "pair_index": index,
                "pair_id": identity,
                "finding_id": finding_id(identity),
                "sentence": sentence,
                "report_span": {"start": start, "end": end},
                "note_id": note_id,
                "citation": citation,
                "numbers": numbers,
                "strong": strong,
            })
    return pairs


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def triage_pairs(pairs: list[dict], conn) -> dict:
    """Mechanical candidate routing, never a support verdict.

    Verdicts per pair:
      dangling            — citation resolves to no vault note (finding)
      needs-llm           — the cite-checker agent must judge it, including
                            pairs with numeric/word-overlap routing hints
    """
    claims_by_note: dict[str, list[dict]] = {}

    def _claims(note_id: str) -> list[dict]:
        if note_id not in claims_by_note:
            rows = conn.execute(
                "SELECT claim, quoted_support, numbers FROM claims WHERE note_id = ?",
                (note_id,),
            ).fetchall()
            claims_by_note[note_id] = [dict(r) for r in rows]
        return claims_by_note[note_id]

    candidates = 0
    dangling = 0
    needs_llm = []
    for pair in pairs:
        if pair["note_id"] is None:
            pair["verdict"] = "dangling"
            dangling += 1
            continue
        hints = []
        note_claims = _claims(pair["note_id"])
        blob = _norm(" ".join(
            (c["claim"] or "") + " " + (c["quoted_support"] or "") + " " + (c["numbers"] or "")
            for c in note_claims
        ))
        if blob:
            nums = [n for n in pair["numbers"] if len(n.replace(",", "")) >= 2]
            if nums and all(n.replace(",", "") in blob.replace(",", "") for n in nums):
                hints.append("numeric-candidate")
            elif not nums:
                # Long word-overlap window: any 6-consecutive-word shingle of the
                # sentence found in the claims blob
                words = _norm(pair["sentence"]).split()
                for i in range(len(words) - 5):
                    if " ".join(words[i : i + 6]) in blob:
                        hints.append("word-overlap-candidate")
                        break
        pair["routing_hints"] = hints
        pair["verdict"] = "needs-llm"
        candidates += bool(hints)
        needs_llm.append(pair)

    return {
        "total": len(pairs),
        "evidence_candidates": candidates,
        "dangling": dangling,
        "needs_llm": len(needs_llm),
        "pairs": pairs,
    }


def sample_needs_llm(pairs: list[dict], sample_rate: float = 0.6) -> list[dict]:
    """Deterministic sampling of the LLM tier: 100% of strong (number-bearing)
    sentences, `sample_rate` of the rest. No RNG — reproducible across resumes.

    A weak pair is kept whenever floor(seen * rate) steps up, which spreads the
    kept pairs evenly and hits the rate exactly. The old every-k-th rule
    rounded 1/rate, so 0.6 became every 2nd and sampled 50%.
    """
    out = []
    weak_seen = 0
    from math import isfinite

    from hyperresearch.core.citation_contracts import CitationContractError

    if isinstance(sample_rate, bool) or not isfinite(sample_rate) or not 0 <= sample_rate <= 1:
        raise CitationContractError("weak_sample_rate must be finite and between 0 and 1")
    rate = sample_rate
    for pair in pairs:
        if pair.get("verdict") != "needs-llm":
            continue
        if pair["strong"]:
            out.append(pair)
            continue
        weak_seen += 1
        if int(weak_seen * rate) > int((weak_seen - 1) * rate):
            out.append(pair)
    return out


def write_pairs_file(
    vault, vault_tag: str, report_path, sample_rate: float = 0.6, *, coverage_mode: str | None = None, final: bool = False,
) -> dict:
    """Extract + triage + sample; write cite-check-pairs.json into the run dir."""
    from hyperresearch.core.citation_contracts import CitationContractError
    from hyperresearch.core.runs import (
        RunError,
        finalization_inputs,
        is_current_run,
        load_manifest,
        manifest_path,
    )

    if manifest_path(vault, vault_tag).exists() and not is_current_run(load_manifest(vault, vault_tag)):
        raise CitationContractError("legacy/unknown finalization contract: read-only diagnostic; extraction refused")

    final_inputs = None
    if final:
        if report_path.resolve() != (vault.notes_dir / f"final_report_{vault_tag}.md").resolve():
            raise CitationContractError("final audit must use the canonical final report")
        try:
            final_inputs = finalization_inputs(vault, vault_tag)
        except (RunError, OSError, UnicodeError, ValueError) as exc:
            raise CitationContractError(str(exc)) from exc
    report_bytes = report_path.read_bytes()
    revision = report_revision(report_bytes)
    report_text = report_bytes.decode("utf-8-sig")
    pairs = extract_pairs(report_text, vault.db, revision=revision, whole_report=final)
    triaged = triage_pairs(pairs, vault.db)

    if coverage_mode is None:
        coverage_mode = "comprehensive" if final else "sampled"
    if coverage_mode not in {"sampled", "comprehensive"}:
        raise CitationContractError("coverage_mode must be sampled or comprehensive")
    if coverage_mode == "comprehensive":
        sample_rate = 1.0
    to_check = sample_needs_llm(triaged["pairs"], sample_rate)
    selected = {p["pair_id"] for p in to_check}
    unreviewed = [p["pair_id"] for p in pairs if p["note_id"] is not None and p["pair_id"] not in selected]
    source_cache = {}
    for pair in pairs:
        if pair["note_id"] is not None:
            pair["source_input"], _ = source_input(vault, pair["note_id"], source_cache)

    run_dir = vault.run_dir(vault_tag)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "schema_version": CONTRACT_VERSION,
        "report_revision": revision,
        "report": str(report_path),
        "coverage_mode": coverage_mode,
        "sampling": {"method": "deterministic-floor-v1", "weak_sample_rate": sample_rate},
        "selected_pair_ids": [p["pair_id"] for p in to_check],
        "unreviewed_pair_ids": unreviewed,
        "pairs": triaged["pairs"],
        "summary": {**{k: v for k, v in triaged.items() if k != "pairs"},
                    "selected": len(to_check), "unreviewed": len(unreviewed)},
        "sampled_for_llm": to_check,
        "dangling": [p for p in triaged["pairs"] if p["verdict"] == "dangling"],
    }
    if final:
        if revision != final_inputs["report_revision"] or final_inputs != finalization_inputs(vault, vault_tag):
            raise CitationContractError("inputs changed during final extraction")
        out["finalization_inputs"] = final_inputs
        from hyperresearch.core.semantic_review import build_inventory

        out["semantic_inventory"] = build_inventory(report_text, revision, pairs)
        from hyperresearch.core.citation_contracts import corpus_inputs

        out["corpus_inputs"] = corpus_inputs(vault, vault_tag, report_text, final_inputs["evidence_requirements"], pairs, source_cache)
    filename = "final-cite-check-pairs.json" if final else "cite-check-pairs.json"
    (run_dir / filename).write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out
