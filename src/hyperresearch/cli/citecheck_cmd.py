"""Cite-check commands — extract citation pairs and candidate routing hints."""

from __future__ import annotations

from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


@app.command("extract")
def citecheck_extract(
    vault_tag: str = typer.Argument(..., help="Run tag (pairs file lands in the run workspace)"),
    report: str | None = typer.Option(None, "--report", help="Report path (default: research/notes/final_report_<tag>.md)"),
    sample_rate: float = typer.Option(0.6, "--sample-rate", help="Fraction of weak (non-number-bearing) needs-llm pairs to check; number-bearing sentences are always 100%"),
    coverage_mode: str | None = typer.Option(None, "--coverage-mode", help="Default comprehensive with --final, sampled otherwise; sampled final is diagnostic and cannot finish"),
    final: bool = typer.Option(False, "--final", help="Final audit after completed final edits; preserve initial citation artifacts"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Extract (sentence, citation) pairs from the final report and triage them.

    Numeric/word overlap supplies evidence candidates, never auto-support.
    Writes selected needs-llm pairs, explicit unreviewed remainder, and dangling citations to
    runs/<tag>/cite-check-pairs.json for the cite-checker agent.
    """
    from hyperresearch.core.citation_contracts import CitationContractError
    from hyperresearch.core.citecheck import write_pairs_file
    from hyperresearch.core.vault import InvalidRunTagError, Vault, VaultError, validate_run_tag

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    try:
        validate_run_tag(vault_tag)
    except InvalidRunTagError as e:
        if json_output:
            output(error(str(e), "INVALID_TAG"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    # Reject legacy extraction before auto_sync can open/migrate its database.
    from hyperresearch.core.runs import RunError, is_current_run, load_manifest, manifest_path

    try:
        if manifest_path(vault, vault_tag).exists() and not is_current_run(load_manifest(vault, vault_tag)):
            raise RunError("legacy/unknown finalization contract: read-only diagnostic; extraction refused")
    except (RunError, OSError, ValueError) as exc:
        if json_output:
            output(error(str(exc), "LEGACY_DIAGNOSTIC"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(1) from exc
    vault.auto_sync()
    report_path = Path(report) if report else (
        vault.notes_dir / f"final_report_{vault_tag}.md"
    )
    if not report_path.exists():
        msg = f"report not found: {report_path}"
        if json_output:
            output(error(msg, "NO_REPORT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {msg}")
        raise typer.Exit(1)

    try:
        result = write_pairs_file(
            vault, vault_tag, report_path, sample_rate=sample_rate, coverage_mode=coverage_mode,
            final=final,
        )
    except (CitationContractError, OSError, UnicodeError) as exc:
        if json_output:
            output(error(str(exc), "INVALID_CITATION_INPUT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(1) from exc
    summary = result["summary"]
    data = {
        "pairs_file": str(vault.run_dir(vault_tag) / ("final-cite-check-pairs.json" if final else "cite-check-pairs.json")),
        "summary": summary,
        "sampled_for_llm": len(result["sampled_for_llm"]),
        "dangling": len(result["dangling"]),
        "coverage_mode": result["coverage_mode"],
        "unreviewed": len(result["unreviewed_pair_ids"]),
    }
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(
            f"[green]Cite-check triage:[/] {summary['total']} pairs — "
            f"{summary['evidence_candidates']} evidence candidates, "
            f"{data['sampled_for_llm']} selected for LLM verification, "
            f"{data['unreviewed']} unreviewed ({data['coverage_mode']}), "
            f"{summary['dangling']} dangling"
        )
