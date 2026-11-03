"""Turn a finished `doesitfire run` into the bundled demo: data, README tables, raw logs.

usage: uv run python scripts/finalize_demo.py <run-output-dir>
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from doesitfire.metrics import pct, summarize

ROOT = Path(__file__).resolve().parent.parent


def main(run_dir: Path) -> None:
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    results["recorded"] = True
    total = sum(t["duration_s"] for t in results["trials"])
    results["duration_s"] = round(max(results.get("duration_s") or 0, total), 1)
    logs_out = ROOT / "examples" / "recorded" / "logs"
    if logs_out.exists():
        shutil.rmtree(logs_out)
    logs_out.mkdir(parents=True)
    for t in results["trials"]:
        log = t.get("log")
        if log and (run_dir / log).exists():
            shutil.copy(run_dir / log, logs_out / Path(log).name)
            t["log"] = f"examples/recorded/logs/{Path(log).name}"
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
        ["Agente", "CLI", "Modelo", "Skills", "Prompts", "Repeticiones", "Ejecuciones", "Errores de infraestructura"]
        if es
        else ["Agent", "CLI", "Model", "Skills", "Prompts", "Repeats", "Runs", "Infrastructure errors"]
    )
    lines = [head, "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for a in results["agents"]:
        name = a["name"] + (" (experimental)" if a.get("experimental") else "")
        n_sk = len({t["skill"] for t in results["trials"] if t["agent"] == a["name"]})
        n_pr = len({(t["skill"], t["prompt"]) for t in results["trials"] if t["agent"] == a["name"]})
        lines.append(
            f"| {name} | {a['cli_version']} | {a['provider']}/{a['model']} | {n_sk} | {n_pr} | "
            f"{results['repeats']} | {runs[a['name']]} | {infra[a['name']]} |"
        )
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
    main(Path(sys.argv[1]))
