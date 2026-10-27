"""Per-run workspaces and the run manifest.

A run is one /hyperresearch invocation. Everything run-scoped lives under
`research/runs/<vault_tag>/`:

    run.json          — the manifest (this module's contract)
    events.jsonl      — append-only event log (step boundaries, spawns, fetches)
    query.md          — canonical verbatim research query
    scaffold.md, prompt-decomposition.json, loci.json, comparisons.md, ...
    temp/             — scratch artifacts (claims JSONs, drafts, notes)
    chapters/chN/     — per-chapter artifact sets (dissertation profile)

The manifest replaces the 1.x "find the highest-numbered artifact on disk"
recovery heuristic with explicit, durable state: per-step status, per-chapter
status, spend counters, and a budget ceiling. The orchestrator updates it at
step boundaries via `hpr run ...` commands; `hpr run resume <tag>` computes
the exact next position.

Vault notes stay global — runs are ephemeral workspaces over the compounding
vault. Final reports ship to `research/notes/final_report_<vault_tag>.md`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_VERSION = 1
MANIFEST_NAME = "run.json"
FINALIZATION_VERSION = 2

# Avg. chars per ASCII-whitespace token above which str.split() word counts
# are no longer trustworthy (see _lacks_word_boundaries).
_NO_WORD_BOUNDARY_AVG_TOKEN_CHARS = 15.0


def _lacks_word_boundaries(text: str) -> bool:
    """True if ASCII-whitespace doesn't meaningfully segment `text` into words."""
    tokens = text.split()
    if not tokens:
        return False
    avg_token_chars = sum(len(t) for t in tokens) / len(tokens)
    return avg_token_chars >= _NO_WORD_BOUNDARY_AVG_TOKEN_CHARS


def _effective_word_count(text: str, chars_per_word: float) -> float:
    """Script-neutral word count: `str.split()` where whitespace delimits
    words, else characters / `chars_per_word` (the profile's ratio for
    scripts like Chinese, Japanese or Thai). Korean is space-delimited and
    takes the split path."""
    if _lacks_word_boundaries(text):
        return len(text) / chars_per_word
    return len(text.split())


EVENTS_NAME = "events.jsonl"

RUN_STATUSES = ("running", "paused", "blocked", "done", "failed", "aborted")
STEP_STATUSES = ("pending", "running", "done", "skipped", "failed")

# Step 1.5 (chapter partition) registers each chapter by emitting this event
# type with {"chapter": <id>, "title": <title>}; record_event folds it into
# manifest["chapters"] so resume_position sees the chapter as pending. This
# is the ONLY registration path — there is no separate chapter command.
CHAPTER_PLAN_EVENT = "chapter-plan"

# Chaptered profiles loop steps 2..10 per chapter (see the step-1.5 skill's
# "Chapter execution loop"); a chapter is complete once its step 10 is done.
CHAPTER_LAST_STEP = "10"

# A run whose manifest hasn't been touched in this long is flagged
# possibly-stalled by `hpr run status`.
STALL_MINUTES = 30


class RunError(ValueError):
    pass


def is_current_run(manifest: dict) -> bool:
    return type(manifest.get("finalization_version")) is int and manifest["finalization_version"] == FINALIZATION_VERSION


def _require_writable_run(manifest: dict) -> None:
    if not is_current_run(manifest):
        raise RunError("legacy/unknown finalization contract: read-only diagnostic; run mutation unavailable")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def manifest_path(vault, vault_tag: str) -> Path:
    return vault.run_dir(vault_tag) / MANIFEST_NAME


def init_run(
    vault,
    vault_tag: str,
    profile: str = "full",
    budget_usd: float | None = None,
    query: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Scaffold research/runs/<vault_tag>/ and write a fresh manifest.

    Idempotent: re-running on an existing run returns the existing manifest
    unchanged (so a recovering orchestrator can call it safely).
    """
    from hyperresearch.core.codex import valid_session_id
    from hyperresearch.core.profiles import resolve_profile

    if session_id is not None and not valid_session_id(session_id):
        raise RunError("invalid Codex session id")

    run_dir = vault.run_dir(vault_tag)
    mpath = run_dir / MANIFEST_NAME
    if mpath.exists():
        existing = load_manifest(vault, vault_tag)
        owner = existing.get("codex_session_id")
        if session_id is not None and owner is not None and owner != session_id:
            raise RunError("run belongs to another Codex session; existing owner preserved")
        return existing

    resolved = resolve_profile(profile, vault.config_path)

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "temp").mkdir(exist_ok=True)

    if query is not None:
        (run_dir / "query.md").write_text(query, encoding="utf-8")

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "finalization_version": FINALIZATION_VERSION,
        "vault_tag": vault_tag,
        "profile": profile,
        "profile_steps": [str(s) for s in resolved.steps],
        "status": "running",
        "started_at": _now(),
        "updated_at": _now(),
        "budget_usd": budget_usd,
        "blocked_on": None,
        "steps": {},
        "chapters": {},
        "spend": {
            "estimated_usd": 0.0,
            "sources_fetched": 0,
            "notes_written": 0,
            "agents_spawned": 0,
        },
    }
    manifest["profile_steps"] = _required_stage_ids(manifest, run_dir, vault.config_path)
    if session_id is not None:
        manifest["codex_session_id"] = session_id
    _save(vault, vault_tag, manifest)
    return manifest


def load_manifest(vault, vault_tag: str) -> dict:
    mpath = manifest_path(vault, vault_tag)
    if not mpath.exists():
        raise RunError(f"no run '{vault_tag}' (missing {mpath})")
    try:
        return json.loads(mpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RunError(f"corrupt manifest for run '{vault_tag}': {e}") from e


def _save(vault, vault_tag: str, manifest: dict) -> None:
    manifest["updated_at"] = _now()
    mpath = manifest_path(vault, vault_tag)
    tmp = mpath.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    tmp.replace(mpath)  # atomic on same filesystem


def record_event(vault, vault_tag: str, event: dict) -> None:
    """Append one event to events.jsonl and touch the manifest heartbeat.

    A `chapter-plan` event (step 1.5) also registers its chapter in
    `manifest["chapters"]` — status "planned", plus the title when given —
    so the manifest, not the events log, stays the single input to
    `resume_position`. Re-emitting the event for a chapter that already
    has step progress never regresses its status.
    """
    run_dir = vault.run_dir(vault_tag)
    if not (run_dir / MANIFEST_NAME).exists():
        raise RunError(f"no run '{vault_tag}'")
    manifest = load_manifest(vault, vault_tag)
    _require_writable_run(manifest)
    event = {"at": _now(), **event}
    with open(run_dir / EVENTS_NAME, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    if event.get("type") == CHAPTER_PLAN_EVENT:
        _fold_chapter_plan(manifest, event)
    _save(vault, vault_tag, manifest)  # heartbeat


# Bounds on what a chapter-plan event may write into the manifest. Events
# come from `hpr run event --data <json>` — agent-authored, so the payload
# shape is not trusted: only a short scalar chapter id and a short string
# title are folded; every other key is left in events.jsonl.
CHAPTER_ID_MAX_CHARS = 64
CHAPTER_TITLE_MAX_CHARS = 500


def _chapter_id_of(value) -> str | None:
    """A chapter id is a short non-empty string or int; anything else is
    ignored (bools, floats, lists, dicts, None)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > CHAPTER_ID_MAX_CHARS:
        return None
    return value


def _fold_chapter_plan(manifest: dict, event: dict) -> None:
    chapter = _chapter_id_of(event.get("chapter"))
    if chapter is None:
        return
    chapters = manifest.get("chapters")
    if not isinstance(chapters, dict):
        chapters = manifest["chapters"] = {}
    ch = chapters.get(chapter)
    if not isinstance(ch, dict):
        ch = chapters[chapter] = {}
    ch.setdefault("status", "planned")
    title = event.get("title")
    if isinstance(title, str) and title.strip():
        ch["title"] = title.strip()[:CHAPTER_TITLE_MAX_CHARS]


def set_step(
    vault,
    vault_tag: str,
    step: str,
    status: str,
    chapter: str | None = None,
) -> dict:
    """Mark a step's status. Steps are keyed as strings ("1", "1.5", "11g")."""
    if status not in STEP_STATUSES:
        raise RunError(f"invalid step status '{status}' (one of {STEP_STATUSES})")
    manifest = load_manifest(vault, vault_tag)
    _require_writable_run(manifest)
    step = str(step)
    current = is_current_run(manifest)
    if current and step == "1" and status == "done" and not chapter:
        tier = _declared_tier(vault.run_dir(vault_tag)) or manifest.get("profile", "full")
        frozen = manifest.get("resolved_pipeline_tier")
        if frozen is not None and tier != frozen:
            raise RunError("pipeline tier changed after stage 1 completion; the resolved route is frozen")
        requirements = _evidence_requirements(vault, manifest, allow_unfrozen=True)
        if frozen is None:
            manifest["resolved_profile_steps"] = _required_stage_ids(manifest, vault.run_dir(vault_tag), vault.config_path)
            manifest["resolved_pipeline_tier"] = tier
            manifest["resolved_evidence_requirements"] = requirements
    if chapter and current:
        if _chapter_id_of(chapter) != chapter or "/" in chapter or "\\" in chapter or chapter in {".", ".."}:
            raise RunError("invalid chapter id")
        ch = manifest["chapters"].setdefault(chapter, {})
        entry = ch.setdefault("steps", {}).setdefault(step, {})
    else:
        entry = manifest["steps"].setdefault(step, {})
    previous = dict(entry)
    entry["status"] = status
    if status == "running" and "started_at" not in entry:
        entry["started_at"] = _now()
    if status in ("done", "skipped", "failed"):
        entry["finished_at"] = previous.get("finished_at") if previous.get("status") == status else _now()
    if current and status != "done":
        entry.pop("completion", None)
    if chapter:
        entry["chapter"] = chapter
        ch = manifest["chapters"].setdefault(chapter, {})
        ch["status"] = f"step-{step}-{status}"
    if current and status == "done" and not chapter and step in {"14.5", "15", "16"}:
        try:
            if step == "14.5":
                completion = _initial_review(vault, manifest)
            else:
                _validate_initial_completion(vault, manifest)
                if step == "16":
                    _validate_edit_completion(vault, manifest, "15")
                completion = {
                    "inputs": _stage_inputs(vault, manifest, through=step),
                    "report_revision": _file_revision(_report_path(vault, vault_tag)),
                }
            if previous.get("status") == "done" and previous.get("completion") != completion:
                raise RunError(f"step {step} inputs changed; restart it with --status running before completing again")
            entry["completion"] = completion
        except (ValueError, OSError, UnicodeError) as exc:
            raise RunError(f"step {step} completion rejected: {exc}") from exc
    _save(vault, vault_tag, manifest)
    record_event(vault, vault_tag, {"type": "step", "step": str(step), "status": status, "chapter": chapter})
    return manifest


def add_spend(
    vault,
    vault_tag: str,
    estimated_usd: float = 0.0,
    sources_fetched: int = 0,
    notes_written: int = 0,
    agents_spawned: int = 0,
) -> dict:
    manifest = load_manifest(vault, vault_tag)
    _require_writable_run(manifest)
    spend = manifest["spend"]
    spend["estimated_usd"] = round(spend.get("estimated_usd", 0.0) + estimated_usd, 4)
    spend["sources_fetched"] = spend.get("sources_fetched", 0) + sources_fetched
    spend["notes_written"] = spend.get("notes_written", 0) + notes_written
    spend["agents_spawned"] = spend.get("agents_spawned", 0) + agents_spawned

    # Budget governor: crossing the ceiling flips the run to blocked. The
    # orchestrator checks `hpr run status` at step boundaries and must pause
    # (never silently skip tier-mandated steps — shrink fan-out instead).
    budget = manifest.get("budget_usd")
    if budget is not None and spend["estimated_usd"] >= budget and manifest["status"] == "running":
        manifest["status"] = "blocked"
        manifest["blocked_on"] = "budget"
    _save(vault, vault_tag, manifest)
    return manifest


def set_status(vault, vault_tag: str, status: str, blocked_on: str | None = None) -> dict:
    if status not in RUN_STATUSES:
        raise RunError(f"invalid run status '{status}' (one of {RUN_STATUSES})")
    manifest = load_manifest(vault, vault_tag)
    _require_writable_run(manifest)
    if status == "done" and is_current_run(manifest):
        raise RunError("only run finish may mark a current run done")
    manifest["status"] = status
    manifest["blocked_on"] = blocked_on if status == "blocked" else None
    _save(vault, vault_tag, manifest)
    return manifest


def list_runs(vault) -> list[dict]:
    """All runs, newest-started first. Tolerates corrupt manifests."""
    runs = []
    if not vault.runs_dir.is_dir():
        return runs
    for child in vault.runs_dir.iterdir():
        mpath = child / MANIFEST_NAME
        if not mpath.exists():
            continue
        try:
            m = json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            runs.append({"vault_tag": child.name, "status": "corrupt-manifest"})
            continue
        runs.append(m)
    runs.sort(key=lambda m: m.get("started_at", ""), reverse=True)
    return runs


def latest_run_tag(vault) -> str | None:
    runs = list_runs(vault)
    return runs[0]["vault_tag"] if runs else None


def resume_position(manifest: dict, required_steps: set[str] | None = None) -> dict:
    """Compute where a run should continue.

    Returns {next_step, done_steps, remaining_steps, chapters_pending}.
    next_step is None when every profile step is done. A registered
    chapter (see CHAPTER_PLAN_EVENT) stays pending until its last looped
    step is done — `set_step(..., chapter=)` records "step-<N>-done" per
    step, and only step CHAPTER_LAST_STEP closes the chapter.

    `required_steps` narrows the walk to the steps the run's declared tier
    actually runs (see `run_resume_position`); without it every
    `profile_steps` entry counts, so a light-tier run would resume at a
    step its tier skips.
    """
    profile_steps = manifest.get("profile_steps", [])
    if required_steps is not None:
        ordered = [s for s in profile_steps if s in required_steps]
        extra = sorted(required_steps - set(profile_steps), key=_step_sort_key)
        profile_steps = ordered + extra
        if is_current_run(manifest):
            profile_steps.sort(key=_step_sort_key)
    steps = manifest.get("steps", {})
    complete_statuses = ("done",) if is_current_run(manifest) else ("done", "skipped")
    done = [s for s in profile_steps if steps.get(s, {}).get("status") in complete_statuses]
    remaining = [s for s in profile_steps if s not in done]
    chapter_done = ("done", f"step-{CHAPTER_LAST_STEP}-done")
    chapters = manifest.get("chapters")
    if not isinstance(chapters, dict):
        chapters = {}
    chapters_pending = [
        name
        for name, ch in chapters.items()
        if not isinstance(ch, dict) or ch.get("status") not in chapter_done
        or (is_current_run(manifest)
            and any(ch.get("steps", {}).get(str(step), {}).get("status") != "done" for step in range(2, 11)))
    ]
    return {
        "next_step": remaining[0] if remaining else None,
        "done_steps": done,
        "remaining_steps": remaining,
        "chapters_pending": chapters_pending,
    }


def _step_sort_key(step: str) -> tuple[int, ...]:
    """"14.5" -> (14, 5), so half-steps order between their neighbours."""
    try:
        return tuple(int(part) for part in str(step).split("."))
    except ValueError:
        return (10**6,)


def run_resume_position(vault, manifest: dict) -> dict:
    """`resume_position` scoped to the tier step 1 declared for this run.

    Same rule as the ship gate (`_required_step_ids`): current runs use the
    route frozen at stage 1 completion. A pre-work `light` classification
    resumes at step 10, not step 3; later decomposition edits cannot shrink it.
    """
    run_dir = vault.run_dir(manifest["vault_tag"])
    current = is_current_run(manifest)
    required = set(_required_stage_ids(manifest, run_dir, vault.config_path)) if current else _required_step_ids(manifest, run_dir, vault.config_path)
    position = resume_position(manifest, required)
    if not current:
        position.update({"action": "legacy-diagnostic", "approval_current": False})
        return position
    # Chapter steps do not complete a different chapter or the global stage 6.
    if "1.5" in required:
        position["remaining_steps"] = [step for step in position["remaining_steps"] if step not in {str(i) for i in range(2, 11)} or step == "6"]
        position["next_step"] = position["remaining_steps"][0] if position["remaining_steps"] else None
        position["chapters_ready"] = []
        if position["next_step"] not in {"1", "1.5"}:
            try:
                plan = _chapter_plan(vault, manifest)
            except (ValueError, OSError, UnicodeError, TypeError, KeyError):
                position.update({"next_step": "1.5", "restart_required": True})
            else:
                pending = {}
                for chapter in plan:
                    progress = manifest["chapters"][chapter["id"]].get("steps", {})
                    pending[chapter["id"]] = [step for step in map(str, range(2, 11)) if progress.get(step, {}).get("status") != "done"]
                ready = [{"chapter": chapter["id"], "next_step": pending[chapter["id"]][0]}
                         for chapter in plan if pending[chapter["id"]]
                         and all(not pending[dep] for dep in chapter["depends_on"])]
                position["chapters_ready"] = ready
                if ready:
                    position.update(ready[0])
                elif any(pending.values()):
                    position.update({"next_step": "1.5", "restart_required": True})
    current_approval = manifest.get("status") == "done" and approval_current(vault, manifest)
    if position["next_step"] is None and not current_approval:
        for step in ("14.5", "15", "16"):
            if step not in required:
                continue
            try:
                if step == "14.5":
                    _validate_initial_completion(vault, manifest)
                else:
                    _validate_edit_completion(vault, manifest, step, current_report=step == "16")
            except (ValueError, OSError, UnicodeError, TypeError, KeyError):
                position["next_step"] = step
                position["restart_required"] = True
                break
    position["approval_current"] = current_approval
    position["action"] = "complete" if current_approval else "step" if position["next_step"] else "final-audit"
    if position["next_step"] is None and not current_approval:
        try:
            _validate_final_audit(vault, manifest)
        except (ValueError, OSError, UnicodeError, TypeError, KeyError):
            pass
        else:
            position["action"] = "finish"
        position["command"] = f"citecheck extract {manifest['vault_tag']} --final --json" if position["action"] == "final-audit" else f"run finish {manifest['vault_tag']} --json"
    return position


def status_summary(vault, vault_tag: str, stall_minutes: int = STALL_MINUTES) -> dict:
    """Manifest + derived fields (stall detection, resume position, budget)."""
    manifest = load_manifest(vault, vault_tag)
    summary = dict(manifest)
    summary["resume"] = run_resume_position(vault, manifest)
    summary["approval_current"] = manifest.get("status") == "done" and approval_current(vault, manifest)
    summary["finalization_diagnostic"] = (
        "current" if summary["approval_current"] else "unverified or stale; run resume for required action"
    )

    possibly_stalled = False
    if manifest.get("status") == "running":
        try:
            updated = datetime.fromisoformat(manifest["updated_at"])
            age_min = (datetime.now(UTC) - updated).total_seconds() / 60
            possibly_stalled = age_min > stall_minutes
        except (KeyError, ValueError):
            possibly_stalled = True
    summary["possibly_stalled"] = possibly_stalled

    budget = manifest.get("budget_usd")
    if budget:
        spent = manifest.get("spend", {}).get("estimated_usd", 0.0)
        summary["budget_remaining_usd"] = round(max(0.0, budget - spent), 4)
    return summary


def _minutes_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
    except ValueError:
        return None
    return round((e - s).total_seconds() / 60, 1)


def run_report_data(vault, vault_tag: str) -> dict:
    """Telemetry rollup for one run: per-step wall-time, spend, event counts."""
    manifest = load_manifest(vault, vault_tag)

    steps = []
    for step_id in manifest.get("profile_steps", []):
        entry = manifest.get("steps", {}).get(step_id, {})
        steps.append({
            "step": step_id,
            "status": entry.get("status", "pending"),
            "minutes": _minutes_between(entry.get("started_at"), entry.get("finished_at")),
            "chapter": entry.get("chapter"),
        })
    # Steps recorded outside the profile list (1.5, 11g, ...) still report
    extra = sorted(set(manifest.get("steps", {})) - set(manifest.get("profile_steps", [])))
    for step_id in extra:
        entry = manifest["steps"][step_id]
        steps.append({
            "step": step_id,
            "status": entry.get("status", "pending"),
            "minutes": _minutes_between(entry.get("started_at"), entry.get("finished_at")),
            "chapter": entry.get("chapter"),
        })

    event_counts: dict[str, int] = {}
    events_file = vault.run_dir(vault_tag) / EVENTS_NAME
    if events_file.exists():
        for line in events_file.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_counts[ev.get("type", "unknown")] = event_counts.get(ev.get("type", "unknown"), 0) + 1

    return {
        "vault_tag": vault_tag,
        "profile": manifest.get("profile"),
        "status": manifest.get("status"),
        "total_wall_minutes": _minutes_between(manifest.get("started_at"), manifest.get("updated_at")),
        "steps": steps,
        "chapters": manifest.get("chapters", {}),
        "spend": manifest.get("spend", {}),
        "budget_usd": manifest.get("budget_usd"),
        "events": event_counts,
    }


def _declared_tier(run_dir: Path) -> str | None:
    """The `pipeline_tier` step 1 wrote into prompt-decomposition.json.

    Tolerant on purpose: a missing or unreadable decomposition just means
    "no declared tier", and verify_run reports the unreadable case through
    its own `decomposition-readable` check.
    """
    decomp_path = run_dir / "prompt-decomposition.json"
    if not decomp_path.exists():
        return None
    try:
        decomp = json.loads(decomp_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    tier = decomp.get("pipeline_tier") if isinstance(decomp, dict) else None
    return tier if isinstance(tier, str) and tier.strip() else None


def _required_step_ids(manifest: dict, run_dir: Path, config_path: Path | None) -> set[str]:
    """Step ids whose artifacts the ship gate demands.

    Stage 1 can reclassify the initialized gear before completing. Current
    runs then retain the frozen route. Before that boundary, and for legacy
    diagnostics, a resolvable declaration takes precedence over profile_steps.
    """
    from hyperresearch.core.profiles import ProfileError, resolve_profile

    if is_current_run(manifest) and "resolved_pipeline_tier" in manifest:
        return {str(s) for s in manifest.get("resolved_profile_steps", [])}
    steps = {str(s) for s in manifest.get("profile_steps", [])}
    tier = _declared_tier(run_dir)
    if tier is None or tier == manifest.get("profile"):
        return steps
    try:
        return {str(s) for s in resolve_profile(tier, config_path).steps}
    except ProfileError:
        return steps


def _required_stage_ids(manifest: dict, run_dir: Path, config_path: Path | None) -> list[str]:
    """Existing fractional procedures, without widening Profile.steps' public schema."""
    from hyperresearch.core.profiles import BUILTIN_PROFILES

    steps = _required_step_ids(manifest, run_dir, config_path)
    tier = (manifest.get("resolved_pipeline_tier") if is_current_run(manifest) else None) or _declared_tier(run_dir) or manifest.get("profile", "full")
    # Recorded/configured lists may add work, but cannot waive a known tier's
    # shipped route merely by deleting flags from its recovery manifest.
    if tier in BUILTIN_PROFILES:
        steps.update(str(step) for step in BUILTIN_PROFILES[tier]["steps"])
    if {"12", "14"} <= steps or tier in {"full", "premier", "dissertation"}:
        steps.add("14.5")
    if tier == "dissertation":
        steps.add("1.5")
    return sorted(steps, key=_step_sort_key)


def _evidence_requirements(vault, manifest: dict, *, allow_unfrozen: bool = False) -> dict:
    """Numeric scale gear is independent of the stage-routing tier.

    Freeze its identity and resolved minima at stage 1. Later configuration or
    task raises apply, while neither can lower the frozen floors.
    """
    from hyperresearch.core.profiles import _load_user_overlays, resolve_profile

    gear = manifest.get("profile", "full")
    profile = resolve_profile(gear, vault.config_path)
    overlay = _load_user_overlays(vault.config_path).get(gear, {})
    current = {"gear": gear}
    decomposition_path = vault.run_dir(manifest["vault_tag"]) / "prompt-decomposition.json"
    decomposition = _read_json(decomposition_path) if decomposition_path.exists() else {}
    declared = decomposition.get("evidence_requirements", {}) if isinstance(decomposition, dict) else None
    if not isinstance(declared, dict) or not set(declared) <= {"source_min", "claims_min"}:
        raise RunError("evidence requirements must contain only source_min/claims_min")
    for key in ("source_min", "claims_min"):
        base = overlay.get(key, getattr(profile, key))
        requested = declared.get(key, 0)
        if type(base) is not int or base < 0 or type(requested) is not int or requested < 0:
            raise RunError("evidence requirements require strict nonnegative integer minima")
        current[key] = max(base, requested)
    frozen = manifest.get("resolved_evidence_requirements")
    if frozen is None:
        if not allow_unfrozen:
            raise RunError("evidence requirements were not frozen at stage 1 completion")
        return current
    if (not isinstance(frozen, dict) or frozen.get("gear") != gear
            or any(type(frozen.get(key)) is not int or frozen[key] < 0 for key in ("source_min", "claims_min"))):
        raise RunError("scale gear identity changed or frozen evidence requirements are invalid")
    return {"gear": gear, **{key: max(current[key], frozen[key]) for key in ("source_min", "claims_min")}}


def _report_path(vault, tag: str) -> Path:
    return vault.notes_dir / f"final_report_{tag}.md"


def _file_revision(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _records_shape(value, label: str) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RunError(f"{label} must be an array of objects")
    return value


def _required_text(record: dict, fields: tuple[str, ...], label: str) -> None:
    if any(not isinstance(record.get(field), str) or not record[field].strip() for field in fields):
        raise RunError(f"{label} requires text fields: {', '.join(fields)}")


def _recommendation_records(payload, label: str) -> list[dict]:
    records = _records_shape(payload if isinstance(payload, list) else payload.get("recommendations"), label)
    categories = {"merge-paragraphs", "break-paragraph", "make-list", "make-table", "bold-keyterms", "split-sentence", "remove-hr", "add-whitespace"}
    for record in records:
        _required_text(record, ("id", "section", "rationale", "category", "severity"), label)
        if (record.get("category") not in categories or record.get("severity") not in {"minor", "moderate", "major"}
                or not isinstance(record.get("current"), str) or not isinstance(record.get("recommended"), str)):
            raise RunError(f"{label} has malformed recommendation fields")
    if isinstance(payload, dict) and "summary" in payload:
        summary = payload["summary"]
        if not isinstance(summary, dict) or type(summary.get("total_recommendations")) is not int or summary["total_recommendations"] != len(records):
            raise RunError(f"{label} summary count differs from recommendations")
    return records


def _decomposition_atomic_items(decomposition: object) -> dict[str, object]:
    """Occurrence identities plus verbatim content, not semantic completeness.

    References disambiguate repeated text and keep entity field obligations
    distinct. The chapter assignment retains the values for downstream use.
    """
    if not isinstance(decomposition, dict):
        raise RunError("atomic item decomposition must be an object")
    items = {}
    for field in ("sub_questions", "entities", "required_formats", "required_sections",
                  "required_section_headings", "time_horizons", "time_periods", "scope_conditions"):
        values = decomposition.get(field, [])
        if not isinstance(values, list):
            raise RunError(f"atomic item category {field} must be an array")
        for index, value in enumerate(values):
            ref = f"/{field}/{index}"
            if field == "entities" and isinstance(value, dict):
                if not isinstance(value.get("name"), str) or not value["name"].strip():
                    raise RunError("atomic entity item requires a name")
                items[f"{ref}/name"] = value["name"]
                required = value.get("required_fields", [])
                if not isinstance(required, list):
                    raise RunError("atomic entity required_fields must be an array")
                for offset, requirement in enumerate(required):
                    if not isinstance(requirement, str) or not requirement.strip():
                        raise RunError("atomic entity required_fields must contain nonempty text")
                    items[f"{ref}/required_fields/{offset}"] = requirement
            elif (isinstance(value, str) and value.strip()) or (field == "time_periods" and isinstance(value, dict) and value):
                items[ref] = value
            else:
                raise RunError(f"atomic item category {field} contains a malformed item")
    if not items:
        raise RunError("chapter atomic partition requires decomposition items")
    return items


def _chapter_plan(vault, manifest: dict) -> list[dict]:
    plan = _read_json(vault.run_dir(manifest["vault_tag"]) / "chapter-plan.json")
    if not isinstance(plan, dict):
        raise RunError("chapter-plan.json must be an object")
    chapters = _records_shape(plan.get("chapters"), "chapter-plan chapters")
    ids = [chapter.get("id") for chapter in chapters]
    if not chapters or any(
        _chapter_id_of(cid) != cid or not isinstance(cid, str)
        or "/" in cid or "\\" in cid or cid in {".", ".."}
        for cid in ids
    ) or len(set(ids)) != len(ids):
        raise RunError("chapter-plan must contain unique safe chapter ids")
    if not isinstance(manifest.get("chapters"), dict) or set(ids) != set(manifest["chapters"]):
        raise RunError("chapter-plan and registered chapter ids differ")
    expected = _decomposition_atomic_items(_read_json(vault.run_dir(manifest["vault_tag"]) / "prompt-decomposition.json"))
    assigned = []
    dependencies = {}
    for chapter in chapters:
        cid = chapter["id"]
        deps = chapter.get("depends_on")
        if (not isinstance(chapter.get("title"), str) or not chapter["title"].strip()
                or not isinstance(chapter.get("atomic_items"), list)
                or not isinstance(deps, list) or any(not isinstance(dep, str) or dep not in ids for dep in deps)
                or len(set(deps)) != len(deps) or cid in deps):
            raise RunError("chapter-plan has malformed chapter/dependencies")
        refs = chapter.get("atomic_item_refs")
        values = chapter["atomic_items"]
        if (not isinstance(refs, list) or not refs or len(refs) != len(values)
                or any(not isinstance(ref, str) or ref not in expected for ref in refs)
                or any(_digest(value) != _digest(expected[ref]) for ref, value in zip(refs, values, strict=True))):
            raise RunError("chapter atomic_items must match aligned decomposition atomic_item_refs")
        assigned.extend(refs)
        dependencies[cid] = deps
    if len(assigned) != len(set(assigned)) or set(assigned) != set(expected):
        raise RunError("chapter atomic items must partition every decomposition item exactly once")
    visiting, visited = set(), set()

    def visit(cid):
        if cid in visiting:
            raise RunError("chapter dependencies contain a cycle")
        if cid not in visited:
            visiting.add(cid)
            for dep in dependencies[cid]:
                visit(dep)
            visiting.remove(cid)
            visited.add(cid)

    for cid in ids:
        visit(cid)
    return chapters


# These are the shipped producer outputs, not a new workflow or evidence ledger.
_STAGE_OUTPUTS = {
    "1": {"query.md": "text", "scaffold.md": "text", "prompt-decomposition.json": "decomposition",
          "temp/coverage-matrix.md": "text"},
    "1.5": {"chapter-plan.json": "chapters"},
    "3": {"temp/contradiction-graph.json": "records", "temp/consensus-claims.json": "records"},
    "4": {"loci.json": "loci"},
    "6": {"comparisons.md": "text"},
    "7": {"temp/source-tensions.json": "tensions"},
    "8": {"corpus-critic-gaps.json": "gaps", "temp/corpus-critic-results.md": "text"},
    "9": {"temp/evidence-digest.md": "text"},
    "11": {"temp/synthesis-plan.md": "text", "temp/synthesis-outline.md": "text", "temp/synthesis-pass1.md": "text"},
    "12": {f"critic-findings-{role}.json": "findings" for role in ("dialectic", "depth", "width", "instruction")},
    "13": {"temp/post-critic-fetch-log.md": "text"},
    "14": {"patch-log.json": "patch"},
    "14.5": {"cite-check-pairs.json": "pairs", "cite-check-findings.json": "citation-findings"},
    "15": {"polish-log.json": "polish"},
    "16": {"readability-recommendations.json": "recommendations", "readability-decisions.json": "decisions"},
}


def _output_specs(vault, manifest: dict, through: str | None = None) -> dict[str, str]:
    stages = _required_stage_ids(manifest, vault.run_dir(manifest["vault_tag"]), vault.config_path)
    if through is not None:
        stages = [stage for stage in stages if _step_sort_key(stage) <= _step_sort_key(through)]
    chaptered = "1.5" in stages
    specs = {}
    for stage in stages:
        if not chaptered or stage not in {str(i) for i in range(2, 11)}:
            specs.update(_STAGE_OUTPUTS.get(stage, {}))
    if chaptered and (through is None or _step_sort_key(through) >= (6,)):
        specs["comparisons.md"] = "text"  # the existing global step 6 output
        for chapter in _chapter_plan(vault, manifest):
            for stage in map(str, range(2, 11)):
                for name, shape in _STAGE_OUTPUTS.get(stage, {}).items():
                    specs[f"chapters/{chapter['id']}/{name}"] = shape
            specs[f"chapters/{chapter['id']}/draft.md"] = "text"
    elif "10" in stages and "11" in stages:
        from hyperresearch.core.profiles import resolve_profile

        profile = resolve_profile(manifest.get("profile", "full"), vault.config_path)
        for angle in "abcdefghijklmnopqrstuvwxyz"[:profile.draft_count]:
            specs[f"temp/draft-{angle}.md"] = "text"
    if "14.5" in stages and (vault.run_dir(manifest["vault_tag"]) / "cite-check-patch-log.json").exists():
        specs["cite-check-patch-log.json"] = "object"
    return specs


def _validate_output(path: Path, shape: str) -> None:
    if shape == "text":
        if not path.read_text(encoding="utf-8-sig").strip():
            raise RunError(f"{path.name} must contain text")
        return
    payload = _read_json(path)
    if shape == "records":
        if path.name == "consensus-claims.json":
            if not isinstance(payload, list) or any(
                not ((isinstance(item, str) and item.strip()) or (isinstance(item, dict) and item))
                for item in payload
            ):
                raise RunError("consensus claims must be an array of nonempty claim strings or objects")
            return
        records = _records_shape(payload, path.name)
        if any(not item for item in records):
            raise RunError(f"{path.name} contains empty records")
        if path.name == "contradiction-graph.json":
            for record in records:
                _required_text(record, ("cluster_id", "fight", "evidence_quality_delta", "scope_overlap", "decision_relevance"), path.name)
                for side in ("side_a", "side_b"):
                    data = record.get(side)
                    if not isinstance(data, dict):
                        raise RunError("contradiction clusters require two sides")
                    _required_text(data, ("position",), path.name)
                    for field in ("claims", "sources"):
                        if not isinstance(data.get(field), list) or any(not isinstance(item, str) for item in data[field]):
                            raise RunError("contradiction side claims/sources must be string arrays")
        return
    if shape == "recommendations" and isinstance(payload, list):
        _recommendation_records(payload, path.name)
        return
    if not isinstance(payload, dict):
        raise RunError(f"{path.name} must be an object")
    arrays = {"loci": ["loci"], "tensions": ["tensions"], "gaps": ["gaps"], "findings": ["findings"],
              "patch": ["applied", "skipped", "conflicts", "orchestrator_escalated"],
              "polish": ["applied", "escalations"], "chapters": ["chapters"],
              "recommendations": ["recommendations"], "decisions": ["skipped", "edit_failures"]}
    for key in arrays.get(shape, []):
        _records_shape(payload.get(key), f"{path.name}.{key}")
    if shape == "findings":
        for record in payload["findings"]:
            # The instruction critic has a separately documented structural-
            # mirror record: empty location, no recommendation, and an explicit
            # heading-index assignment for an orchestrator restructure.
            atomic_item = record.get("atomic_item")
            structural_mirror = (
                path.name == "critic-findings-instruction.json"
                and payload.get("critic_type", "instruction") == "instruction"
                and record.get("severity") == "critical"
                and record.get("failure_mode") == "wrong-order"
                and record.get("location") == ""
                and record.get("requires_orchestrator_restructure") is True
                and isinstance(atomic_item, str)
                and re.fullmatch(r"required_section_headings\[\d+\]:\s*\S.*", atomic_item) is not None
            )
            if structural_mirror:
                _required_text(record, ("severity", "issue"), path.name)
                if "recommendation" in record:
                    _required_text(record, ("recommendation",), path.name)
            else:
                _required_text(record, ("severity", "location", "issue", "recommendation"), path.name)
            if record.get("severity") not in {"critical", "major", "minor"}:
                raise RunError(f"{path.name} has invalid finding severity")
    elif shape == "loci":
        for record in payload["loci"]:
            _required_text(record, ("name", "one_line", "rationale", "flavor"), path.name)
            score_fields = ("importance", "uncertainty", "disagreement", "decision_impact", "composite_score")
            finite_scores = all(type(record.get(field)) is int or (
                type(record.get(field)) is float and math.isfinite(record[field])
            ) for field in score_fields)
            if (record.get("flavor") not in {"dialectical", "synthesis", "technical"}
                    or not finite_scores or type(record.get("source_budget")) is not int):
                raise RunError(f"{path.name} requires finite numeric scores, integer source_budget and a known flavor")
    elif shape == "gaps":
        for record in payload["gaps"]:
            _required_text(record, ("id", "type", "priority"), path.name)
    elif shape == "tensions":
        for record in payload["tensions"]:
            _required_text(record, ("name", "resolution", "origin", "decision_relevance"), path.name)
            for side in ("side_a", "side_b"):
                data = record.get(side)
                if not isinstance(data, dict):
                    raise RunError(f"{path.name} requires two tension sides")
                _required_text(data, ("position", "evidence"), path.name)
                if not isinstance(data.get("proponents"), list) or any(not isinstance(item, str) for item in data["proponents"]):
                    raise RunError(f"{path.name} proponents must be an array of note ids")
    elif shape == "polish":
        for record in payload["applied"]:
            _required_text(record, ("category", "description"), path.name)
            if type(record.get("chars_removed")) is not int:
                raise RunError("polish applied record requires integer chars_removed")
        for record in payload["escalations"]:
            _required_text(record, ("category", "issue"), path.name)
    elif shape == "recommendations":
        _recommendation_records(payload, path.name)
    elif shape == "decisions":
        for field in ("skipped", "edit_failures"):
            for record in payload[field]:
                _required_text(record, ("id", "reason"), path.name)
    if shape == "patch" and (type(payload.get("total_findings")) is not int or payload["total_findings"] < 0):
        raise RunError("patch-log.total_findings must be a nonnegative integer")
    if shape == "decomposition":
        _required_text(payload, ("pipeline_tier",), path.name)
        if payload.get("pipeline_tier") not in {"light", "full", "premier", "dissertation"}:
            raise RunError("decomposition must declare a supported pipeline_tier")
        if not isinstance(payload.get("required_section_headings", []), list):
            raise RunError("required_section_headings must be an array")
    if shape == "decisions" and (type(payload.get("total_recommendations")) is not int
                or not isinstance(payload.get("applied"), list)
                or any(not isinstance(item, str) for item in payload["applied"])
                or type(payload.get("net_char_delta_actual")) is not int):
        raise RunError("readability decisions have invalid counts/IDs")
    if shape == "pairs":
        from hyperresearch.core.citation_contracts import parse_pairs

        parse_pairs(payload)
    if shape == "citation-findings":
        from hyperresearch.core.citation_contracts import parse_findings

        if parse_findings(payload).legacy:
            raise RunError("current initial citation evidence must be versioned")


def _step_state(manifest: dict) -> dict:
    def state(entry):
        if not isinstance(entry, dict):
            raise RunError("stage entries must be objects")
        return {key: entry[key] for key in ("status", "started_at", "finished_at") if key in entry}

    if not isinstance(manifest.get("steps"), dict) or not isinstance(manifest.get("chapters"), dict):
        raise RunError("manifest steps/chapters must be objects")
    if any(not isinstance(chapter, dict) or not isinstance(chapter.get("steps", {}), dict) for chapter in manifest["chapters"].values()):
        raise RunError("chapter progress must be an object of stage entries")

    return {
        "profile": manifest.get("profile"), "profile_steps": manifest.get("profile_steps"),
        "resolved_pipeline_tier": manifest.get("resolved_pipeline_tier"),
        "resolved_profile_steps": manifest.get("resolved_profile_steps"),
        "resolved_evidence_requirements": manifest.get("resolved_evidence_requirements"),
        "steps": {key: state(value) for key, value in manifest.get("steps", {}).items()},
        "chapters": {key: {"title": value.get("title"), "steps": {
            step: state(entry) for step, entry in value.get("steps", {}).items()
        }} for key, value in manifest.get("chapters", {}).items()},
    }


def _stage_inputs(vault, manifest: dict, through: str | None = None) -> dict:
    run_dir = vault.run_dir(manifest["vault_tag"])
    if is_current_run(manifest):
        tier = manifest.get("resolved_pipeline_tier")
        if tier is None or tier != _declared_tier(run_dir):
            raise RunError("pipeline tier is missing or differs from the route frozen at stage 1 completion")
    stages = _required_stage_ids(manifest, run_dir, vault.config_path)
    stages = [stage for stage in stages if through is None or _step_sort_key(stage) <= _step_sort_key(through)]
    chaptered = "1.5" in stages
    global_stages = [stage for stage in stages if not chaptered or stage not in {str(i) for i in range(2, 11)} or stage == "6"]
    for stage in global_stages:
        if manifest.get("steps", {}).get(stage, {}).get("status") != "done":
            raise RunError(f"required stage {stage} is not done")
    if chaptered:
        chapters = _chapter_plan(vault, manifest)
        if through is None or _step_sort_key(through) >= (6,):
            for chapter in chapters:
                progress = manifest["chapters"][chapter["id"]].get("steps", {})
                for stage in map(str, range(2, 11)):
                    if progress.get(stage, {}).get("status") != "done":
                        raise RunError(f"chapter {chapter['id']} stage {stage} is not done")
                for dependency in chapter["depends_on"]:
                    dep = manifest["chapters"][dependency]["steps"]["10"]
                    first = progress.get("2", {})
                    if not dep.get("finished_at") or not first.get("finished_at") or dep["finished_at"] > first.get("started_at", first["finished_at"]):
                        raise RunError(f"chapter {chapter['id']} started before dependency {dependency} completed")
    revisions = {}
    for name, shape in _output_specs(vault, manifest, through).items():
        path = run_dir / name
        if not path.resolve().is_relative_to(run_dir.resolve()):
            raise RunError(f"output path escapes run directory: {name}")
        _validate_output(path, shape)
        revisions[name] = _file_revision(path)
    if "16" in stages:
        recs = _read_json(run_dir / "readability-recommendations.json")
        recs = recs if isinstance(recs, list) else recs["recommendations"]
        ids = [rec.get("id") for rec in recs]
        decisions = _read_json(run_dir / "readability-decisions.json")
        handled = decisions["applied"] + [rec.get("id") for field in ("skipped", "edit_failures") for rec in decisions[field]]
        if (any(not isinstance(identity, str) or not identity for identity in ids)
                or any(not isinstance(identity, str) or not identity for identity in handled)
                or len(set(ids)) != len(ids) or len(set(handled)) != len(handled)
                or set(ids) != set(handled) or decisions["total_recommendations"] != len(ids)):
            raise RunError("readability decisions must account for each recommendation exactly once")
    state = _step_state(manifest)
    state["steps"] = {key: value for key, value in state["steps"].items() if key in stages}
    return {"stages": state, "outputs": revisions}


def _initial_artifacts(vault, manifest: dict) -> dict:
    run_dir = vault.run_dir(manifest["vault_tag"])
    names = ["cite-check-pairs.json", "cite-check-findings.json"]
    if (run_dir / "cite-check-patch-log.json").exists():
        names.append("cite-check-patch-log.json")
    return {name: _file_revision(run_dir / name) for name in names}


def _initial_review(vault, manifest: dict) -> dict:
    from hyperresearch.core.citation_contracts import (
        parse_findings,
        validate_coverage,
        validate_resolutions,
    )

    run_dir = vault.run_dir(manifest["vault_tag"])
    # Every required earlier stage/output must exist, while children remain parallel within their stages.
    stages = _stage_inputs(vault, manifest, through="14")
    pairs = _read_json(run_dir / "cite-check-pairs.json")
    payload = _read_json(run_dir / "cite-check-findings.json")
    validate_coverage(pairs, payload, vault)
    findings = parse_findings(payload)
    revision = _file_revision(_report_path(vault, manifest["vault_tag"]))
    log = run_dir / "cite-check-patch-log.json"
    if any(item["severity"] in {"critical", "major"} for item in findings.findings) or log.exists():
        validate_resolutions(findings, _read_json(log), revision)
    elif pairs["report_revision"] != revision:
        raise RunError("initial audit report changed without a bound reviewed resolution")
    return {"report_revision": revision, "artifacts": _initial_artifacts(vault, manifest), "inputs": stages,
            "sources": [pair.get("source_input") for pair in pairs["pairs"] if pair["note_id"] is not None]}


def _validate_initial_completion(vault, manifest: dict) -> None:
    stages = _required_stage_ids(manifest, vault.run_dir(manifest["vault_tag"]), vault.config_path)
    if "14.5" not in stages:
        return
    entry = manifest.get("steps", {}).get("14.5", {})
    completion = entry.get("completion")
    if (entry.get("status") != "done" or not isinstance(completion, dict)
            or completion.get("artifacts") != _initial_artifacts(vault, manifest)
            or completion.get("inputs") != _stage_inputs(vault, manifest, through="14")):
        raise RunError("initial stage 14.5 review is missing or changed since completion")


def _validate_edit_completion(vault, manifest: dict, step: str, *, current_report: bool = False) -> None:
    entry = manifest.get("steps", {}).get(step, {})
    completion = entry.get("completion")
    if (entry.get("status") != "done" or not isinstance(completion, dict)
            or completion.get("inputs") != _stage_inputs(vault, manifest, through=step)):
        raise RunError(f"stage {step} completion inputs changed; restart final editing")
    if current_report and completion.get("report_revision") != _file_revision(_report_path(vault, manifest["vault_tag"])):
        raise RunError(f"report changed after stage {step}; restart final editing before final audit")


def finalization_inputs(vault, vault_tag: str) -> dict:
    """Inputs permitted for FINAL extraction, after all final edits and outputs."""
    manifest = load_manifest(vault, vault_tag)
    if not is_current_run(manifest):
        raise RunError("legacy/unknown finalization contract: read-only diagnostic, current approval unavailable")
    _validate_initial_completion(vault, manifest)
    _validate_edit_completion(vault, manifest, "15")
    _validate_edit_completion(vault, manifest, "16", current_report=True)
    inputs = {"finalization_version": FINALIZATION_VERSION, "vault_tag": vault_tag,
              "report_revision": _file_revision(_report_path(vault, vault_tag)),
              "evidence_requirements": _evidence_requirements(vault, manifest),
              **_stage_inputs(vault, manifest)}
    return {**inputs, "input_digest": _digest(inputs)}


def _verification_inputs(vault, manifest: dict) -> dict:
    """Stable inputs only: exclude status, heartbeat, spend, and the receipt itself."""
    from hyperresearch.cli.lint import _check_cited_quote_integrity, _check_retracted_citations
    from hyperresearch.core.citation_contracts import corpus_inputs, source_input
    from hyperresearch.core.citecheck import extract_pairs
    from hyperresearch.core.profiles import resolve_profile

    run_dir = vault.run_dir(manifest["vault_tag"])
    report = _report_path(vault, manifest["vault_tag"])
    raw = report.read_bytes() if report.exists() else b""
    pairs = extract_pairs(raw.decode("utf-8-sig"), vault.db, whole_report=True)
    source_cache = {}
    sources = {pair["note_id"]: source_input(vault, pair["note_id"], source_cache)[0] for pair in pairs if pair["note_id"] is not None}
    names = set(_output_specs(vault, manifest)) | {"final-cite-check-pairs.json", "final-cite-check-findings.json", "final-cite-check-patch-log.json"}
    text = raw.decode("utf-8-sig")
    lint_outcomes = {
        "quote-integrity": _check_cited_quote_integrity(vault, vault.db, report, text, pairs=pairs, source_cache=source_cache),
        "retracted-citations": _check_retracted_citations(vault, vault.db, report, text),
    }
    return {"finalization_version": manifest.get("finalization_version"), "vault_tag": manifest["vault_tag"],
            "codex_session_id": manifest.get("codex_session_id"), "stages": _step_state(manifest),
            "completions": {key: value.get("completion") for key, value in manifest.get("steps", {}).items() if key in {"14.5", "15", "16"}},
            "report_revision": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "outputs": {name: _file_revision(run_dir / name) if (run_dir / name).exists() else None for name in sorted(names)},
            "extracted_pairs": pairs, "sources": sources,
            "corpus_inputs": corpus_inputs(vault, manifest["vault_tag"], text, _evidence_requirements(vault, manifest), pairs, source_cache),
            "profile": resolve_profile(manifest.get("profile", "full"), vault.config_path).model_dump(),
            "config_revision": _file_revision(vault.config_path) if vault.config_path.exists() else None,
            "blocking_lint_outcomes": lint_outcomes}


def approval_current(vault, manifest: dict) -> bool:
    if not is_current_run(manifest):
        return False
    receipt = manifest.get("verify", {})
    try:
        return (receipt.get("passed") is True and receipt.get("input_digest") == _digest(_verification_inputs(vault, manifest)))
    except (ValueError, OSError, UnicodeError, TypeError, KeyError):
        return False


def _validate_final_audit(vault, manifest: dict) -> dict:
    from hyperresearch.core.citation_contracts import (
        corpus_inputs,
        parse_findings,
        validate_coverage,
    )
    from hyperresearch.core.citecheck import extract_pairs
    from hyperresearch.core.evidence import validate_corpus_review
    from hyperresearch.core.semantic_review import validate_review

    run_dir = vault.run_dir(manifest["vault_tag"])
    inputs = finalization_inputs(vault, manifest["vault_tag"])
    pairs = _read_json(run_dir / "final-cite-check-pairs.json")
    findings = _read_json(run_dir / "final-cite-check-findings.json")
    if not isinstance(pairs, dict) or pairs.get("finalization_inputs") != inputs:
        raise RunError("final citation extraction inputs are missing or stale")
    report = _report_path(vault, manifest["vault_tag"])
    if pairs.get("report_revision") != inputs["report_revision"]:
        raise RunError("final citation report revision is stale")
    text = report.read_bytes().decode("utf-8-sig")
    actual = extract_pairs(text, vault.db, revision=inputs["report_revision"], whole_report=True)
    keys = ("pair_index", "pair_id", "finding_id", "sentence", "note_id", "citation", "numbers", "strong", "report_span")
    def projection(records):
        if any(not isinstance(pair, dict) for pair in records):
            raise RunError("final pairs must be objects")
        return [{key: pair.get(key) for key in keys} for pair in records]
    if not isinstance(pairs.get("pairs"), list) or projection(pairs["pairs"]) != projection(actual):
        raise RunError("final pairs differ from actual report extraction; citation occurrences were dropped or changed")
    if pairs.get("coverage_mode") != "comprehensive" or pairs.get("unreviewed_pair_ids") != []:
        raise RunError("final acceptance requires comprehensive citation coverage; sampled final is diagnostic only")
    source_cache = {}
    coverage = validate_coverage(pairs, findings, vault, source_cache=source_cache)
    if any(item["severity"] in {"critical", "major"} for item in parse_findings(findings).findings):
        raise RunError("current final critical/major findings require correction and fresh extraction/results; a resolution log cannot clear them")
    coverage.update(validate_review(text, inputs["report_revision"], pairs, findings.get("semantic_review"), source_cache))
    current_corpus = corpus_inputs(vault, manifest["vault_tag"], text, inputs["evidence_requirements"], actual, source_cache)
    if pairs.get("corpus_inputs") != current_corpus:
        raise RunError("final corpus inputs are missing or stale; re-extract and review every current corpus member")
    coverage["evidence_counts"] = validate_corpus_review(pairs, findings["semantic_review"], findings.get("corpus_review"), source_cache)
    return coverage


def verify_run(vault, vault_tag: str) -> dict:
    """Structural verification battery for a completed run.

    The CI-able gate: report exists, headings honored, length in profile
    range, citation density above floor, tier-mandated artifacts present,
    cite-check findings resolved. Returns {passed, checks: [...]} — each
    check {name, ok, detail}. Content lint rules (quote-integrity etc.)
    run separately via `hpr lint`.
    """
    from hyperresearch.core.profiles import resolve_profile

    manifest = load_manifest(vault, vault_tag)
    profile = resolve_profile(manifest.get("profile", "full"), vault.config_path)
    run_dir = vault.run_dir(vault_tag)
    checks: list[dict] = []
    evidence_counts = None

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    current_contract = is_current_run(manifest)
    inputs_before = None
    if current_contract:
        try:
            inputs_before = _verification_inputs(vault, manifest)
        except (ValueError, OSError, UnicodeError, TypeError, KeyError) as exc:
            check("verification-inputs", False, str(exc))
    elif "finalization_version" in manifest:
        check("finalization-version", False, "unsupported finalization contract; read-only diagnostic")

    report_path = _report_path(vault, vault_tag)
    check("report-exists", report_path.exists(), str(report_path))

    report_text = ""
    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8-sig")

        decomp_path = run_dir / "prompt-decomposition.json"
        response_format = None
        required_headings: list[str] = []
        declares_levers = False
        if decomp_path.exists():
            try:
                decomp = json.loads(decomp_path.read_text(encoding="utf-8-sig"))
                if not isinstance(decomp, dict):
                    raise ValueError("decomposition must be an object")
                response_format = decomp.get("response_format")
                required_headings = decomp.get("required_section_headings", []) or []
                if not isinstance(required_headings, list) or any(not isinstance(h, str) for h in required_headings):
                    raise ValueError("required_section_headings must be strings")
                declares_levers = bool(decomp.get("levers"))
            except (ValueError, OSError, UnicodeError):
                required_headings = []
                check("decomposition-readable", False, "prompt-decomposition.json is not valid JSON")

        # Runs that declared levers must have rendered the shim files the
        # spawn contract pastes downstream. Lever-less runs (pre-levers or
        # defaults-only) skip the check entirely.
        if declares_levers:
            from hyperresearch.core.levers import ROLES

            missing_shims = [
                role for role in ROLES
                if not (run_dir / "shims" / f"{role}.md").exists()
            ]
            check(
                "levers-rendered",
                not missing_shims,
                "all shim files present" if not missing_shims
                else f"missing shims: {missing_shims} (run `hpr levers render {vault_tag}`)",
            )

        if response_format and response_format in profile.word_targets:
            if _lacks_word_boundaries(report_text):
                # char_targets_no_word_boundary is profile-configurable per
                # response_format; falls back to word_target * chars_per_word
                # if a format has no explicit target.
                char_targets = profile.char_targets_no_word_boundary
                if response_format in char_targets:
                    low, high = char_targets[response_format]
                else:
                    low_w, high_w = profile.word_targets[response_format]
                    ratio = profile.chars_per_word_no_word_boundary
                    low, high = int(low_w * ratio), int(high_w * ratio)
                count = len(report_text)
                check(
                    "length-in-range",
                    low * 0.8 <= count <= high * 1.2,
                    f"{count} chars vs target {low}-{high} ({response_format}; char-based; ±20% tolerance)",
                )
            else:
                low, high = profile.word_targets[response_format]
                wc = len(report_text.split())
                check(
                    "length-in-range",
                    low * 0.8 <= wc <= high * 1.2,
                    f"{wc} words vs target {low}-{high} ({response_format}; ±20% tolerance)",
                )

        missing = [h for h in required_headings if h not in report_text]
        check(
            "required-headings",
            not missing,
            "all present" if not missing else f"missing: {missing}",
        )

        import re as _re

        from hyperresearch.core.patterns import WIKI_LINK_RE

        # Grouped markers ([7, 12]) count one citation per source number,
        # so consolidating stacks never lowers measured density. Wiki-link
        # citations use the shared pattern so this gate and the lint/cite-
        # check rules agree on what a [[...]] citation is.
        cites = sum(
            len(g.split(","))
            for g in _re.findall(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]", report_text)
        ) + len(WIKI_LINK_RE.findall(report_text))
        # Per 1000 *effective* words, not characters: a character floor
        # means a different amount of content per script (CJK packs ~3x
        # the content per character), so the same number would be a
        # different bar for a Japanese report than for an English one.
        no_boundaries = _lacks_word_boundaries(report_text)
        effective_words = _effective_word_count(
            report_text, profile.chars_per_word_no_word_boundary
        )
        density = cites * 1000 / max(1.0, effective_words)
        floor = profile.citation_density_min  # also the instruction critic's re-count trigger
        unit = (
            f"words (chars / {profile.chars_per_word_no_word_boundary:g}; no word boundaries)"
            if no_boundaries
            else "words"
        )
        check(
            "citation-density",
            density >= floor,
            f"{density:.2f} citations/1000 {unit} (floor {floor})",
        )

        check(
            "no-scaffold-leak",
            "## User Prompt (VERBATIM" not in report_text,
            "scaffold gospel header must not ship",
        )

        if current_contract:
            # Content gates: the blocking lint rules run in-process, so this ONE
            # command carries the whole ship verdict. Bench Q62 shipped with 24
            # hallucinated-quote errors because the orchestrator ran the lint
            # separately and re-interpreted the failures as false positives —
            # folding the rules in here removes that seam.
            try:
                from hyperresearch.cli.lint import (
                    _check_cited_quote_integrity,
                    _check_retracted_citations,
                )

                for rule, fn in (
                    ("quote-integrity", _check_cited_quote_integrity),
                    ("retracted-citations", _check_retracted_citations),
                ):
                    errors = [
                        i for i in fn(vault, vault.db, report_path, report_text)
                        if i.get("severity") == "error"
                    ]
                    check(
                        rule,
                        not errors,
                        "clean" if not errors else (
                            f"{len(errors)} error(s) — first: "
                            f"{errors[0].get('message', '')[:160]}"
                        ),
                    )
            except Exception as exc:
                check("content-lints", False, f"content lint rules failed to run: {exc}")

    if not current_contract:
        for rule in ("quote-integrity", "retracted-citations"):
            check(rule, False, "unavailable/unverified: legacy or unknown finalization contract; database-backed lint omitted and database left unopened")

    # Tier-mandated artifacts, keyed on the tier the run actually ran (see
    # _required_step_ids) rather than the profile it was initialized with.
    steps = _required_step_ids(manifest, run_dir, vault.config_path)
    if {"12", "14"} <= steps:
        for name in (
            "critic-findings-dialectic.json", "critic-findings-depth.json",
            "critic-findings-width.json", "critic-findings-instruction.json",
            "patch-log.json",
        ):
            check(f"artifact:{name}", (run_dir / name).exists(), str(run_dir / name))
    if "15" in steps:
        check("artifact:polish-log.json", (run_dir / "polish-log.json").exists(),
              str(run_dir / "polish-log.json"))

    # Cite-check (step 14.5): explicit schema, original pair identity, and
    # reviewed critical resolution. Stage dependencies/final audit are separate.
    cc_findings = run_dir / "cite-check-findings.json"
    if not current_contract and manifest.get("steps", {}).get("14.5", {}).get("status") == "done":
        from hyperresearch.core.citation_contracts import (
            CitationContractError,
            bind_findings,
            parse_findings,
            parse_pairs,
            report_revision,
            validate_resolutions,
        )

        try:
            findings = parse_findings(json.loads(cc_findings.read_text(encoding="utf-8-sig")))
            if findings.legacy:
                # Read-only compatibility, never an invented identity or a
                # migration of historical artifacts. Zero is explicit, but
                # does not prove selected coverage or final-current-byte review.
                ok = not findings.findings
                detail = (
                    "legacy explicit zero findings; diagnostic only, review coverage unverified"
                    if ok else "legacy findings lack verified revision/identity; resolution unverified"
                )
            else:
                pairs_path = run_dir / "cite-check-pairs.json"
                pairs = parse_pairs(json.loads(pairs_path.read_text(encoding="utf-8-sig")))
                bind_findings(findings, pairs)
                criticals = [f for f in findings.findings if f["severity"] == "critical"]
                log_path = run_dir / "cite-check-patch-log.json"
                if criticals or log_path.exists():
                    validate_resolutions(
                        findings, json.loads(log_path.read_text(encoding="utf-8-sig")),
                        report_revision(report_path.read_bytes()),
                    )
                ok = True
                detail = f"file-only v1 contract: {len(criticals)} critical resolution record(s) bound to report bytes; source-body review unverified"
        except (CitationContractError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            ok = False
            detail = f"citation artifacts invalid/unverified: {exc}"
        check("cite-check-resolved", ok, detail)
        check("cite-check-coverage", False,
              "unavailable/unverified: legacy or unknown finalization contract; source-body coverage requires database access, which is omitted")

    if current_contract:
        try:
            coverage = _validate_final_audit(vault, manifest)
            evidence_counts = coverage["evidence_counts"]
            check("finalization", True, f"final {coverage['coverage_mode']} audit: {coverage['reviewed']}/{coverage['selected']} selected; {coverage['unreviewed']} explicitly unreviewed")
            check("qualified-evidence", True, json.dumps(evidence_counts, sort_keys=True))
        except (ValueError, OSError, UnicodeError, TypeError, KeyError) as exc:
            check("finalization", False, str(exc))
        try:
            unchanged = inputs_before is not None and inputs_before == _verification_inputs(vault, load_manifest(vault, vault_tag))
        except (ValueError, OSError, UnicodeError, TypeError, KeyError):
            unchanged = False
        check("verification-inputs-stable", unchanged, "exact inputs unchanged across verification" if unchanged else "inputs changed during verification or were unreadable")
    result = {"vault_tag": vault_tag, "passed": all(c["ok"] for c in checks), "checks": checks,
              "diagnostic_only": not current_contract}
    if inputs_before is not None:
        result["inputs"] = inputs_before
        result["input_digest"] = _digest(inputs_before)
    if evidence_counts is not None:
        result["evidence_counts"] = evidence_counts
    return result


def finish_run(vault, vault_tag: str) -> dict:
    """The terminal ship gate: verify, then flip the manifest accordingly.

    This is the ONLY path to status "done". Verification failure flips the
    run to blocked (blocked_on="verify") instead — the caller's job is then
    to change the REPORT until the gate passes, never to re-interpret the
    checks. The verify result is recorded in the manifest either way, so
    `run status` and the bench harness can see whether a "done" run actually
    earned it.
    """
    result = verify_run(vault, vault_tag)
    manifest = load_manifest(vault, vault_tag)
    if not is_current_run(manifest):
        result["passed"] = False
        result["checks"].append({"name": "finalization-version", "ok": False,
                                 "detail": "legacy/unknown run: read-only diagnostic; no current finish approval"})
        return {"manifest": manifest, "verify": result}

    def stable():
        try:
            return result.get("input_digest") == _digest(_verification_inputs(vault, load_manifest(vault, vault_tag)))
        except (ValueError, OSError, UnicodeError, TypeError, KeyError):
            return False

    def mutation():
        result["passed"] = False
        result["checks"].append({"name": "finish-inputs-stable", "ok": False,
                                 "detail": "inputs changed during finish verification/persistence; approval rejected"})

    if result["passed"] and not stable():
        mutation()
    manifest["verify"] = {
        "passed": result["passed"],
        "at": _now(),
        "failed_checks": [c["name"] for c in result["checks"] if not c["ok"]],
        "finalization_version": FINALIZATION_VERSION,
        "input_digest": result.get("input_digest"),
        "inputs": result.get("inputs"),
    }
    if result["passed"]:
        manifest["status"] = "done"
        manifest["blocked_on"] = None
    else:
        manifest["status"] = "blocked"
        manifest["blocked_on"] = "verify"
    _save(vault, vault_tag, manifest)
    if result["passed"] and not stable():
        mutation()
        manifest = load_manifest(vault, vault_tag)
        manifest["status"], manifest["blocked_on"] = "blocked", "verify"
        manifest["verify"]["passed"] = False
        manifest["verify"]["failed_checks"] = [c["name"] for c in result["checks"] if not c["ok"]]
        _save(vault, vault_tag, manifest)
    record_event(vault, vault_tag, {
        "type": "finish",
        "passed": result["passed"],
        "failed_checks": manifest["verify"]["failed_checks"],
    })
    if result["passed"] and not stable():
        mutation()
        manifest = load_manifest(vault, vault_tag)
        manifest["status"], manifest["blocked_on"] = "blocked", "verify"
        manifest["verify"]["passed"] = False
        manifest["verify"]["failed_checks"] = [c["name"] for c in result["checks"] if not c["ok"]]
        _save(vault, vault_tag, manifest)
        record_event(vault, vault_tag, {
            "type": "finish", "passed": False, "invalidated": True,
            "failed_checks": manifest["verify"]["failed_checks"],
        })
    return {"manifest": manifest, "verify": result}
