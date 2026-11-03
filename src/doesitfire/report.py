"""Terminal matrix, JUnit XML, badge SVG and shields.io endpoint JSON."""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .metrics import overall, pct, summarize

OK, WARN, ERR = "#11813c", "#a45e00", "#c22826"
ACCENT = "#a1319b"


def recall_color(v: float | None) -> str:
    if v is None:
        return "dim"
    return "green" if v >= 0.8 else "yellow" if v >= 0.5 else "red"


def false_color(v: float | None) -> str:
    if v is None:
        return "dim"
    return "green" if v <= 0.1 else "yellow" if v <= 0.3 else "red"


def recorded_banner(results: dict) -> str:
    models = ", ".join(sorted({f"{a['provider']}/{a['model']}" for a in results["agents"]}))
    host = results.get("host") or {}
    when = (results.get("started_at") or "")[:10]
    parts = [f"{when}", f"doesitfire {results.get('version')}", models]
    if host.get("hardware"):
        parts.append(host["hardware"])
    return " | ".join(p for p in parts if p)


def print_matrix(results: dict, console: Console | None = None) -> dict:
    console = console or Console()
    summary = summarize(results)
    if results.get("recorded"):
        console.print(Text(f"RECORDED RESULT, not a live run: {recorded_banner(results)}", style="bold magenta"))
    table = Table(title="Skill activation (fired runs / valid runs)", title_justify="left", expand=False)
    table.add_column("skill", style="bold")
    for agent in results["agents"]:
        label = agent["name"] + (" (experimental)" if agent.get("experimental") else "")
        table.add_column(f"{label}\n[dim]{agent['model']}[/dim]", justify="left")
    for skill in summary["skills"]:
        row: list[Text | str] = [skill]
        for agent in summary["agents"]:
            c = summary["cells"][f"{agent}|{skill}"]
            t = Text()
            t.append(f"fires {c['true_fires']}/{c['fire_runs']}", style=recall_color(c["recall"]))
            t.append("\n")
            t.append(f"false {c['false_fires']}/{c['nofire_runs']}", style=false_color(c["false_fire_rate"]))
            if c["errors"]:
                t.append(f"\nerrors {c['errors']}", style="red")
            row.append(t)
        table.add_row(*row)
    table.add_section()
    for label, key, colorer in (
        ("recall", "recall", recall_color),
        ("false-fire rate", "false_fire_rate", false_color),
        ("precision", "precision", recall_color),
    ):
        row = [Text(label, style="dim")]
        for agent in summary["agents"]:
            v = summary["totals"][agent][key]
            row.append(Text(pct(v), style=colorer(v)))
        table.add_row(*row)
    console.print(table)
    cost = results.get("cost_usd") or 0.0
    console.print(
        f"[dim]{len(results['trials'])} runs, {results.get('repeats')} repeat(s) per prompt, "
        f"{results.get('duration_s') or 0:.0f}s, cost {cost:.4f} USD[/dim]"
    )
    if any(a.get("experimental") for a in results["agents"]):
        console.print(
            "[dim]Codex is experimental: it reports no activation event, so a run counts as fired "
            "when Codex reads the skill's SKILL.md.[/dim]"
        )
    return summary


def write_junit(results: dict, path: Path) -> None:
    summary = summarize(results)
    suites, total = [], {"tests": 0, "failures": 0, "errors": 0}
    for agent in summary["agents"]:
        cases, counts = [], {"tests": 0, "failures": 0, "errors": 0}
        for skill in summary["skills"]:
            for row in summary["cells"][f"{agent}|{skill}"]["prompts"]:
                counts["tests"] += 1
                label = "should fire" if row["expect"] == "fire" else "should not fire"
                name = f"[{label}] {row['prompt']}"
                body = ""
                result = f"fired {row['fired']}/{row['runs']} valid runs"
                if row["runs"] == 0:
                    counts["errors"] += 1
                    errored = f"all {row['errors']} runs errored"
                    body = f"<error message={quoteattr(errored)}/>"
                else:
                    majority = row["fired"] * 2 > row["runs"]
                    ok = majority if row["expect"] == "fire" else not majority
                    if not ok:
                        counts["failures"] += 1
                        body = f"<failure message={quoteattr(result)}/>"
                cases.append(
                    f"    <testcase classname={quoteattr(f'{agent}.{skill}')} name={quoteattr(name)}>"
                    f"{body}<system-out>{escape(result)}</system-out></testcase>"
                )
        for k in total:
            total[k] += counts[k]
        suites.append(
            f'  <testsuite name={quoteattr(agent)} tests="{counts["tests"]}" failures="{counts["failures"]}" '
            f'errors="{counts["errors"]}">\n' + "\n".join(cases) + "\n  </testsuite>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuites name="doesitfire" tests="{total["tests"]}" failures="{total["failures"]}" '
        f'errors="{total["errors"]}">\n' + "\n".join(suites) + "\n</testsuites>\n"
    )
    path.write_text(xml, encoding="utf-8")


def _badge_parts(results: dict) -> tuple[str, str]:
    o = overall(summarize(results))
    message = f"fires {pct(o['recall'])} · false {pct(o['false_fire_rate'])}"
    r = o["recall"]
    color = OK if r is not None and r >= 0.8 else WARN if r is not None and r >= 0.5 else ERR
    return message, color


def _text_width(s: str) -> int:
    # Approximate Verdana 11px advance widths, enough for a badge.
    narrow, wide = set("fijlrt ·:|!.,'"), set("mwMW%")
    return int(sum(4 if c in narrow else 10 if c in wide else 7 for c in s)) + 10


def badge_svg(results: dict, label: str = "doesitfire") -> str:
    message, color = _badge_parts(results)
    lw, mw = _text_width(label), _text_width(message)
    w = lw + mw
    aria = f"{escape(label)}: {escape(message)}"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{aria}">
  <title>{escape(label)}: {escape(message)}</title>
  <clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{lw}" height="20" fill="{ACCENT}"/>
    <rect x="{lw}" width="{mw}" height="20" fill="{color}"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="{lw / 2:.1f}" y="14">{escape(label)}</text>
    <text x="{lw + mw / 2:.1f}" y="14">{escape(message)}</text>
  </g>
</svg>
"""


def badge_endpoint(results: dict, label: str = "doesitfire") -> dict:
    message, color = _badge_parts(results)
    return {"schemaVersion": 1, "label": label, "message": message, "color": color.lstrip("#")}


def write_badges(results: dict, out: Path) -> None:
    (out / "badge.svg").write_text(badge_svg(results), encoding="utf-8")
    (out / "badge.json").write_text(json.dumps(badge_endpoint(results), indent=2) + "\n", encoding="utf-8")
