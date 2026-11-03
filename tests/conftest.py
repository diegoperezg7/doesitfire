import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def events():
    def load(name: str) -> str:
        return (FIXTURES / "events" / f"{name}.jsonl").read_text(encoding="utf-8")

    return load


def make_results(trials, agents=("claude-code", "codex"), skills=("commit-message", "regex-explainer")):
    return {
        "schema": 1,
        "tool": "doesitfire",
        "version": "0.1.0",
        "started_at": "2026-11-03T10:00:00+00:00",
        "duration_s": 12.0,
        "repeats": 1,
        "max_turns": 2,
        "host": {"os": "Linux"},
        "agents": [
            {"name": a, "cli_version": "x", "provider": "ollama", "model": "m", "experimental": a == "codex"}
            for a in agents
        ],
        "skills": [{"name": s, "description": f"{s} description"} for s in skills],
        "trials": trials,
        "cost_usd": 0.0,
        "recorded": False,
    }


def trial(agent, skill, expect, fired, error=None, prompt=None, activated=None):
    return {
        "agent": agent,
        "skill": skill,
        "prompt": prompt or f"{expect} prompt",
        "expect": expect,
        "repeat": 0,
        "fired": fired,
        "activated": activated if activated is not None else ([skill] if fired else []),
        "error": error,
        "duration_s": 1.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
    }


@pytest.fixture
def sample_results():
    return make_results(
        [
            trial("claude-code", "commit-message", "fire", True),
            trial("claude-code", "commit-message", "fire", False, prompt="other"),
            trial("claude-code", "commit-message", "no_fire", True),
            trial("claude-code", "commit-message", "no_fire", False, prompt="other no"),
            trial("claude-code", "regex-explainer", "fire", True),
            trial("claude-code", "regex-explainer", "no_fire", False, error="timeout after 300s"),
            trial("codex", "commit-message", "fire", True),
            trial("codex", "commit-message", "no_fire", False, activated=["regex-explainer"]),
            trial("codex", "regex-explainer", "fire", False),
            trial("codex", "regex-explainer", "no_fire", False),
        ]
    )


def dump(obj) -> str:
    return json.dumps(obj)
