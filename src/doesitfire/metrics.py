"""Turn raw trials into the activation matrix.

Per agent x skill:
- recall          = fired runs / valid runs, over should-fire prompts
- false-fire rate = fired runs / valid runs, over should-not-fire prompts
- precision       = true fires / (true fires + false fires)
Runs that errored (timeout, API error) are excluded from every denominator and counted apart.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Cell:
    agent: str
    skill: str
    fire_runs: int = 0  # valid runs on should-fire prompts
    true_fires: int = 0
    nofire_runs: int = 0  # valid runs on should-not-fire prompts
    false_fires: int = 0
    errors: int = 0
    prompts: list[dict] = field(default_factory=list)

    @property
    def recall(self) -> float | None:
        return self.true_fires / self.fire_runs if self.fire_runs else None

    @property
    def false_fire_rate(self) -> float | None:
        return self.false_fires / self.nofire_runs if self.nofire_runs else None

    @property
    def precision(self) -> float | None:
        fired = self.true_fires + self.false_fires
        return self.true_fires / fired if fired else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(recall=self.recall, false_fire_rate=self.false_fire_rate, precision=self.precision)
        return d


def _add(cell: Cell, t: dict) -> None:
    if t.get("error"):
        cell.errors += 1
        return
    if t["expect"] == "fire":
        cell.fire_runs += 1
        cell.true_fires += bool(t["fired"])
    else:
        cell.nofire_runs += 1
        cell.false_fires += bool(t["fired"])


def summarize(results: dict) -> dict:
    agents = [a["name"] for a in results["agents"]]
    skills = [s["name"] for s in results["skills"]]
    cells = {(a, s): Cell(a, s) for a in agents for s in skills}
    totals = {a: Cell(a, "*") for a in agents}
    per_prompt: dict[tuple, dict] = {}
    for t in results["trials"]:
        key = (t["agent"], t["skill"])
        if key not in cells:
            continue
        _add(cells[key], t)
        _add(totals[t["agent"]], t)
        pk = (t["agent"], t["skill"], t["expect"], t["prompt"])
        row = per_prompt.setdefault(
            pk, {"prompt": t["prompt"], "expect": t["expect"], "fired": 0, "runs": 0, "errors": 0, "other": []}
        )
        if t.get("error"):
            row["errors"] += 1
        else:
            row["runs"] += 1
            row["fired"] += bool(t["fired"])
        for other in t.get("activated") or []:
            if other != t["skill"] and other not in row["other"]:
                row["other"].append(other)
    for (a, s, _e, _p), row in per_prompt.items():
        cells[(a, s)].prompts.append(row)
    return {
        "agents": agents,
        "skills": skills,
        "cells": {f"{a}|{s}": c.to_dict() for (a, s), c in cells.items()},
        "totals": {a: c.to_dict() for a, c in totals.items()},
    }


def overall(summary: dict) -> dict:
    """Pooled figures across agents and skills (used by the badge)."""
    tf = sum(c["true_fires"] for c in summary["totals"].values())
    fr = sum(c["fire_runs"] for c in summary["totals"].values())
    ff = sum(c["false_fires"] for c in summary["totals"].values())
    nr = sum(c["nofire_runs"] for c in summary["totals"].values())
    return {
        "recall": tf / fr if fr else None,
        "false_fire_rate": ff / nr if nr else None,
        "precision": tf / (tf + ff) if (tf + ff) else None,
    }


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value * 100):d}%"


def check_thresholds(summary: dict, min_recall: float | None, max_false_fire: float | None) -> list[str]:
    """Return human-readable failures for cells below the thresholds."""
    failures = []
    for key, c in summary["cells"].items():
        agent, skill = key.split("|", 1)
        if min_recall is not None and c["recall"] is not None and c["recall"] < min_recall:
            failures.append(f"{skill} on {agent}: recall {pct(c['recall'])} < {pct(min_recall)}")
        if max_false_fire is not None and c["false_fire_rate"] is not None and c["false_fire_rate"] > max_false_fire:
            failures.append(f"{skill} on {agent}: false-fire rate {pct(c['false_fire_rate'])} > {pct(max_false_fire)}")
    return failures
