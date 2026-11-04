"""Turn a finished `doesitfire run` into the bundled demo: data, README tables, raw logs.

usage: uv run python scripts/finalize_demo.py <run-output-dir> [<run-output-dir> ...]

Several directories are merged (for example one run per provider): trials and agents are
concatenated, costs summed, durations summed, and each agent keeps its own repeats count.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from doesitfire.metrics import pct, summarize

ROOT = Path(__file__).resolve().parent.parent


def load_merged(run_dirs: list[Path]) -> dict:
    merged: dict | None = None
    for d in run_dirs:
        r = json.loads((d / "results.json").read_text(encoding="utf-8"))
        for a in r["agents"]:
            a["repeats"] = r["repeats"]
        for t in r["trials"]:
            if t.get("log"):
                t["log"] = str((d / t["log"]).resolve())
        if merged is None:
            merged = r
            merged["sessions"] = r.get("sessions", 1)
            continue
        known = {a["name"] for a in merged["agents"]}
        merged["agents"] += [a for a in r["agents"] if a["name"] not in known]
        merged["trials"] += r["trials"]
        merged["cost_usd"] = round(merged["cost_usd"] + r["cost_usd"], 6)
        merged["duration_s"] = round((merged.get("duration_s") or 0) + (r.get("duration_s") or 0), 1)
        merged["started_at"] = min(merged["started_at"], r["started_at"])
        merged["sessions"] += r.get("sessions", 1)
        merged["blocked_egress"] = sorted(set(merged.get("blocked_egress", [])) | set(r.get("blocked_egress", [])))
        known_s = {s["name"] for s in merged["skills"]}
        merged["skills"] += [s for s in r["skills"] if s["name"] not in known_s]
    used = {t["agent"] for t in merged["trials"]}
    merged["agents"] = [a for a in merged["agents"] if a["name"] in used]
    merged["repeats"] = max(a["repeats"] for a in merged["agents"])
    order = {s: i for i, s in enumerate(["commit-message", "regex-explainer", "dockerfile-review"])}
    merged["skills"].sort(key=lambda s: order.get(s["name"], 99))
    agent_order = {a: i for i, a in enumerate(["claude-code", "codex", "opencode"])}
    merged["agents"].sort(key=lambda a: agent_order.get(a["name"], 99))
    return merged


def main(run_dirs: list[Path]) -> None:
    results = load_merged(run_dirs)
    results["recorded"] = True
    total = sum(t["duration_s"] for t in results["trials"])
    results["duration_s"] = round(max(results.get("duration_s") or 0, total), 1)
    results["trials"].sort(key=lambda t: (t["agent"], t["repeat"]))
    logs_out = ROOT / "examples" / "recorded" / "logs"
    if logs_out.exists():
        shutil.rmtree(logs_out)
    logs_out.mkdir(parents=True)
    for t in results["trials"]:
        log = t.get("log")
        if log and Path(log).exists():
            name = f"{t['agent']}-{t['skill']}-{t['expect']}-r{t['repeat']}-{hashlib.sha1(t['prompt'].encode()).hexdigest()[:8]}.jsonl"
            shutil.copy(log, logs_out / name)
            t["log"] = f"examples/recorded/logs/{name}"
    data = json.dumps(results, indent=2, ensure_ascii=False) + "\n"
    (ROOT / "src" / "doesitfire" / "data" / "demo-results.json").write_text(data, encoding="utf-8")
    (ROOT / "examples" / "recorded" / "results.json").write_text(data, encoding="utf-8")
    write_readmes(results)


def tables(results: dict, lang: str) -> str:
    s = summarize(results)
    es = lang == "es"
    infra = {a: sum(1 for t in results["trials"] if t["agent"] == a and t["error"]) for a in s["agents"]}
    runs = {a: sum(1 for t in results["trials"] if t["agent"] == a) for a in s["agents"]}
    when = results["started_at"][:10]
    hw = (results.get("host") or {}).get("hardware") or ""
    head = (
        f"Grabado el {when} en un {hw}, con doesitfire {results['version']}. "
        f"Cada agente usó **su propio CLI** con el modelo indicado; los modelos y repeticiones pueden diferir, "
        "así que no compares agentes como si fueran el mismo experimento."
        if es
        else f"Recorded on {when} on an {hw} with doesitfire {results['version']}. "
        "Each agent ran **its own CLI** with the model shown; read each column on its own, not as a ranking of agents."
    )
    cols = (
        ["Agente", "CLI", "Modelo", "Skills", "Prompts", "Repeticiones", "Ejecuciones", "Con error (excluidas)"]
        if es
        else ["Agent", "CLI", "Model", "Skills", "Prompts", "Repeats", "Runs", "Errored (excluded)"]
    )
    lines = [head, "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for a in results["agents"]:
        name = a["name"] + (" (experimental)" if a.get("experimental") else "")
        n_sk = len({t["skill"] for t in results["trials"] if t["agent"] == a["name"]})
        n_pr = len({(t["skill"], t["prompt"]) for t in results["trials"] if t["agent"] == a["name"]})
        all_pr = len({(t["skill"], t["prompt"]) for t in results["trials"]})
        of = (" de " if es else " of ") + str(all_pr) if n_pr < all_pr else ""
        lines.append(
            f"| {name} | {a['cli_version']} | {a['provider']}/{a['model']} | {n_sk} | {n_pr}{of} | "
            f"{a.get('repeats', results['repeats'])} | {runs[a['name']]} | {infra[a['name']]} |"
        )
    kinds: dict = {}
    for t in results["trials"]:
        if t["error"]:
            k = (t["agent"], t["error"].split(":")[0][:60])
            kinds[k] = kinds.get(k, 0) + 1
    if kinds:
        lines += ["", ("Errores: " if es else "Errors: ") + "; ".join(f"{a}: {n} x `{e}`" for (a, e), n in kinds.items())]
    lines += [
        "",
        (
            "Activaciones / ejecuciones válidas. *debe* = prompts que deben activar la skill; "
            "*no debe* = casi-aciertos que no."
            if es
            else "Fired runs / valid runs. *should* = prompts that should load the skill; *should not* = near misses."
        ),
    ]
    hdr = ["Skill"] + [
        f"{a} · {'debe' if es else 'should'}" + f" / {'no debe' if es else 'should not'}" for a in s["agents"]
    ]
    lines += ["", "| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for sk in s["skills"] + ["*"]:
        row = ["**" + ("todas" if es else "all") + "**" if sk == "*" else f"`{sk}`"]
        for a in s["agents"]:
            c = s["totals"][a] if sk == "*" else s["cells"][f"{a}|{sk}"]
            row.append(f"{c['true_fires']}/{c['fire_runs']} / {c['false_fires']}/{c['nofire_runs']}")
        lines.append("| " + " | ".join(row) + " |")
    o = {a: s["totals"][a] for a in s["agents"]}
    lines += [
        "",
        ("Recall por agente: " if es else "Recall per agent: ")
        + ", ".join(f"{a} {pct(o[a]['recall'])}" for a in s["agents"])
        + (". Tasa de falsos disparos: " if es else ". False-fire rate: ")
        + ", ".join(f"{a} {pct(o[a]['false_fire_rate'])}" for a in s["agents"])
        + ".",
    ]
    lines += [
        "",
        (
            "Los eventos JSON en bruto de cada ejecución están en [`examples/recorded/logs/`](examples/recorded/logs)."
            if es
            else "The raw JSON events of every run are in [`examples/recorded/logs/`](examples/recorded/logs)."
        ),
    ]
    lines += ["", '<p align="center"><img src="docs/assets/report-light.png" alt="HTML report" width="820"></p>']
    return "\n".join(lines)


def write_readmes(results: dict) -> None:
    for name, lang in (("README.md", "en"), ("README.es.md", "es")):
        p = ROOT / name
        text = p.read_text(encoding="utf-8")
        block = "<!-- results:start -->\n" + tables(results, lang) + "\n<!-- results:end -->"
        text = re.sub(r"<!-- results:start -->.*?<!-- results:end -->", lambda m, b=block: b, text, flags=re.S)
        p.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main([Path(p) for p in sys.argv[1:]])
