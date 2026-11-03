"""doesitfire command line: init, run, report, demo."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import webbrowser
from importlib import resources
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from . import __version__
from .config import CONFIG_NAME, find_skill_dirs, load_config, render_template
from .errors import BudgetExceeded, DoesItFireError
from .metrics import check_thresholds, summarize

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Does your SKILL.md actually fire? Test skill activation in Claude Code, Codex and OpenCode.",
)
console = Console()
err = Console(stderr=True)


def _version(value: bool) -> None:
    if value:
        console.print(f"doesitfire {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version.")
    ] = False,
) -> None:
    pass


def write_outputs(results: dict, out: Path) -> dict[str, Path]:
    from .html import write_html
    from .report import write_badges, write_junit

    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": out / "results.json",
        "html": out / "report.html",
        "junit": out / "junit.xml",
        "badge": out / "badge.svg",
        "badge_json": out / "badge.json",
    }
    paths["json"].write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_html(results, paths["html"])
    write_junit(results, paths["junit"])
    write_badges(results, out)
    return paths


def _open(path: Path) -> None:
    if os.environ.get("CI") or not sys.stdout.isatty():
        return
    with contextlib.suppress(Exception):  # opening a browser is best effort
        webbrowser.open(path.resolve().as_uri())


@app.command()
def init(
    directory: Annotated[Path, typer.Argument(help="Project root to scan for skills.")] = Path("."),
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing doesitfire.yaml.")] = False,
) -> None:
    """Create a doesitfire.yaml for the skills found under DIRECTORY."""
    directory = directory.resolve()
    target = directory / CONFIG_NAME
    if target.exists() and not force:
        raise DoesItFireError(f"{target} already exists. Use --force to overwrite it.")
    skills = find_skill_dirs(directory)
    target.write_text(render_template(skills, directory), encoding="utf-8")
    console.print(f"Wrote [bold]{target}[/bold] with {len(skills) or 'a placeholder for'} skill(s).")
    console.print("Next: replace the TODO prompts, then run [bold]doesitfire run[/bold].")


@app.command()
def run(
    config: Annotated[Path, typer.Option("--config", "-c", help="Path to doesitfire.yaml.")] = Path(CONFIG_NAME),
    out: Annotated[Path, typer.Option("--out", "-o", help="Output directory.")] = Path("doesitfire-results"),
    agents: Annotated[str | None, typer.Option(help="Comma-separated subset of agents to run.")] = None,
    skills: Annotated[str | None, typer.Option(help="Comma-separated subset of skills to run.")] = None,
    repeats: Annotated[int | None, typer.Option(help="Runs per prompt and agent (overrides the config).")] = None,
    max_cost: Annotated[float, typer.Option("--max-cost", help="Stop before spending more than this many USD.")] = 1.0,
    min_recall: Annotated[
        float | None, typer.Option(help="Exit 1 if any agent x skill recall is below this (0-1).")
    ] = None,
    max_false_fire: Annotated[
        float | None, typer.Option(help="Exit 1 if any false-fire rate is above this (0-1).")
    ] = None,
    rebuild: Annotated[bool, typer.Option(help="Rebuild the agent Docker image.")] = False,
    open_report: Annotated[bool, typer.Option("--open/--no-open", help="Open the HTML report when done.")] = True,
) -> None:
    """Run every agent on every prompt and report how often each skill fires."""
    from .runner import run_matrix

    cfg = load_config(config)
    if agents:
        wanted = {a.strip() for a in agents.split(",") if a.strip()}
        unknown = wanted - {a.name for a in cfg.agents}
        if unknown:
            raise DoesItFireError(f"Not configured in {config}: {', '.join(sorted(unknown))}.")
        cfg.agents = [a for a in cfg.agents if a.name in wanted]
    if skills:
        wanted = {s.strip() for s in skills.split(",") if s.strip()}
        unknown = wanted - {s.name for s in cfg.skills}
        if unknown:
            raise DoesItFireError(f"Not in {config}: {', '.join(sorted(unknown))}.")
        cfg.skills = [s for s in cfg.skills if s.name in wanted]
    if repeats is not None:
        if repeats < 1:
            raise DoesItFireError("--repeats must be at least 1.")
        cfg.repeats = repeats
    if max_cost < 0:
        raise DoesItFireError("--max-cost cannot be negative.")

    n = cfg.repeats * len(cfg.agents) * sum(len(s.should_fire) + len(s.should_not_fire) for s in cfg.skills)
    console.print(
        f"doesitfire {__version__}: {len(cfg.skills)} skill(s) x {len(cfg.agents)} agent(s), "
        f"{cfg.repeats} repeat(s) = {n} sandboxed runs. Budget {max_cost:.2f} USD."
    )

    def progress(p: dict) -> None:
        t = p["trial"]
        mark = (
            "[red]error[/red]" if t["error"] else ("[magenta]fired[/magenta]" if t["fired"] else "[dim]no fire[/dim]")
        )
        good = (t["fired"] == (t["expect"] == "fire")) and not t["error"]
        tick = "[green]ok[/green]" if good else "[yellow]!![/yellow]"
        console.print(
            f"[dim]{p['done']:>4}/{p['total']}[/dim] {tick} {t['agent']:<11} {t['skill']:<20} {mark:<22} "
            f"[dim]{t['duration_s']:>5.0f}s  {escape(' '.join(t['prompt'].split())[:60])}[/dim]"
            + (f"\n          [red]{escape(t['error'])}[/red]" if t["error"] else "")
        )

    out.mkdir(parents=True, exist_ok=True)
    partial_file = out / "results.partial.json"

    def checkpoint(results: dict) -> None:
        partial_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    partial = None
    try:
        results = run_matrix(
            cfg,
            max_cost=max_cost,
            log=console.print,
            progress=progress,
            checkpoint=checkpoint,
            logs_dir=out / "logs",
            rebuild=rebuild,
        )
    except BudgetExceeded as exc:
        partial = exc
        results = exc.results or {}
    if not results:
        raise DoesItFireError("No results.")
    from .report import print_matrix

    paths = write_outputs(results, out)
    partial_file.unlink(missing_ok=True)
    summary = print_matrix(results, console)
    console.print(f"Report: {paths['html']}  JSON: {paths['json']}  JUnit: {paths['junit']}  Badge: {paths['badge']}")
    if open_report:
        _open(paths["html"])
    if partial is not None:
        err.print(f"[bold red]Budget limit reached, results are partial:[/bold red] {partial}")
        raise typer.Exit(partial.exit_code)
    failures = check_thresholds(summary, min_recall, max_false_fire)
    if failures:
        err.print("[bold red]Thresholds not met:[/bold red]\n  " + "\n  ".join(failures))
        raise typer.Exit(1)


@app.command()
def report(
    results_file: Annotated[Path, typer.Argument(help="A results.json written by 'doesitfire run'.")],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Output directory (default: next to the JSON).")
    ] = None,
    open_report: Annotated[bool, typer.Option("--open/--no-open")] = False,
) -> None:
    """Re-render the matrix, HTML, JUnit and badge from a results.json."""
    from .report import print_matrix

    results = _load_results(results_file)
    paths = write_outputs(results, out or results_file.parent)
    print_matrix(results, console)
    console.print(f"Report: {paths['html']}")
    if open_report:
        _open(paths["html"])


def _load_results(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DoesItFireError(f"{path} not found.") from None
    except json.JSONDecodeError as exc:
        raise DoesItFireError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(data, dict) or data.get("tool") != "doesitfire":
        raise DoesItFireError(f"{path} is not a doesitfire results file.")
    summarize(data)  # validates the structure early
    return data


@app.command()
def demo(
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Where to write the report (default: a temp dir).")
    ] = None,
    open_report: Annotated[bool, typer.Option("--open/--no-open", help="Open the HTML report.")] = True,
) -> None:
    """Show a RECORDED real run of the three example skills. No keys, no Docker, no model."""
    from .report import print_matrix

    data = resources.files("doesitfire") / "data" / "demo-results.json"
    results = json.loads(data.read_text(encoding="utf-8"))
    target = out or Path(tempfile.mkdtemp(prefix="doesitfire-demo-"))
    paths = write_outputs(results, target)
    print_matrix(results, console)
    console.print(f"Report: {paths['html']}")
    console.print("Run it yourself: [bold]doesitfire run -c examples/doesitfire.yaml[/bold] (Docker + Ollama).")
    if open_report:
        _open(paths["html"])


def main() -> None:
    try:
        app()
    except DoesItFireError as exc:
        err.print(f"[bold red]Error:[/bold red] {escape(str(exc))}")
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        err.print("[yellow]Interrupted.[/yellow]")
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()

__all__ = ["app", "main"]
