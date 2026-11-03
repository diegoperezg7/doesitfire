"""Static, self-contained HTML report (one file, no external JS)."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from .metrics import overall, summarize


def render_html(results: dict) -> str:
    summary = summarize(results)
    payload = {
        "meta": {k: v for k, v in results.items() if k != "trials"},
        "summary": summary,
        "overall": overall(summary),
        "runs": len(results.get("trials", [])),
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    template = (resources.files("doesitfire") / "templates" / "report.html").read_text(encoding="utf-8")
    return template.replace("__DOESITFIRE_DATA__", data)


def write_html(results: dict, path: Path) -> None:
    path.write_text(render_html(results), encoding="utf-8")
