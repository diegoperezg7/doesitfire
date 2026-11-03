"""End to end: the real Claude Code, Codex and OpenCode CLIs in Docker, talking to
the scripted mock model through the egress proxy. Needs Docker; runs on Linux CI."""

from pathlib import Path

import pytest

from doesitfire.config import load_config
from doesitfire.metrics import summarize
from doesitfire.runner import run_matrix

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.docker
def test_real_clis_against_mock_model(monkeypatch):
    from mockmodel import serve

    srv = serve(0, "0.0.0.0")
    try:
        monkeypatch.setenv("OLLAMA_HOST", f"http://localhost:{srv.server_address[1]}")
        cfg = load_config(ROOT / "tests" / "fixtures" / "mock-suite.yaml")
        results = run_matrix(cfg, max_cost=0)
    finally:
        srv.shutdown()
    errors = [t for t in results["trials"] if t["error"]]
    assert not errors, errors
    s = summarize(results)
    for agent in ("claude-code", "codex", "opencode"):
        total = s["totals"][agent]
        assert total["recall"] == 1.0, agent
        assert total["false_fire_rate"] == 0.0, agent
    # the "fire:regex-explainer" prompt under commit-message loads the other skill, not the tested one
    row = [p for p in s["cells"]["opencode|commit-message"]["prompts"] if "regex" in p["prompt"]][0]
    assert row["other"] == ["regex-explainer"]
