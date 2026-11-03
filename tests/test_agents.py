import json

import pytest

from doesitfire.agents import Codex, Observation, make_agent
from doesitfire.config import AgentConfig
from doesitfire.providers import get_provider

SKILLS = {"regex-explainer", "commit-message"}


def agent(name, provider="ollama", model="qwen3:4b-16k"):
    return make_agent(AgentConfig(name, provider, model), get_provider(provider), 2)


@pytest.mark.parametrize("name", ["claude-code", "codex", "opencode"])
def test_detects_activation_in_real_cli_output(events, name):
    a = agent(name)
    fired = a.parse(events(f"{name}-fire"), SKILLS)
    assert fired.activated == ["regex-explainer"]
    assert fired.error is None
    assert fired.usage_seen and fired.input_tokens > 0
    quiet = a.parse(events(f"{name}-nofire"), SKILLS)
    assert quiet.activated == []
    assert quiet.error is None


def test_claude_build_ollama():
    inv = agent("claude-code").build("hello")
    assert inv.argv[:3] == ["claude", "-p", "hello"]
    assert "--max-turns" in inv.argv and inv.argv[inv.argv.index("--max-turns") + 1] == "2"
    assert "Bash" in inv.argv[inv.argv.index("--disallowedTools") + 1]
    assert inv.env["ANTHROPIC_BASE_URL"] == "http://host.docker.internal:11434"
    assert inv.env["SLASH_COMMAND_TOOL_CHAR_BUDGET"] == "8000"
    assert "CLAUDE_CODE_EXTRA_BODY" not in inv.env  # model defaults: thinking stays on
    assert inv.secret_env == {}
    assert inv.allow == ["http://host.docker.internal:11434"]


def test_secrets_never_in_argv_or_plain_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-value")
    for name in ("claude-code", "codex", "opencode"):
        inv = agent(name, provider="openrouter", model="anthropic/claude-haiku-5.5").build("hi")
        blob = json.dumps(inv.argv) + json.dumps(inv.env)
        assert "sk-or-secret-value" not in blob, name
        assert "sk-or-secret-value" in inv.secret_env.values(), name


def test_claude_with_real_claude_model_keeps_defaults(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    inv = agent("claude-code", provider="anthropic", model="claude-haiku-5-5").build("hi")
    assert "SLASH_COMMAND_TOOL_CHAR_BUDGET" not in inv.env
    assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in inv.env
    assert inv.secret_env == {"ANTHROPIC_API_KEY": "k"}


def test_claude_oauth_token_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    inv = agent("claude-code", provider="anthropic", model="claude-haiku-5-5").build("hi")
    assert inv.secret_env == {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}


def test_codex_build_uses_responses_provider():
    inv = agent("codex").build("hi")
    joined = " ".join(inv.argv)
    assert 'wire_api="responses"' in joined
    assert 'base_url="http://host.docker.internal:11434/v1"' in joined
    assert "analytics.enabled=false" in joined
    assert inv.argv[-1] == "hi"


def test_opencode_config_denies_side_effects():
    inv = agent("opencode").build("hi")
    cfg = json.loads(inv.env["OPENCODE_CONFIG_CONTENT"])
    assert cfg["permission"] == {"edit": "deny", "bash": "deny", "webfetch": "deny"}
    assert cfg["agent"]["build"]["steps"] == 2
    assert inv.argv[-3:] == ["-m", "doesitfire/qwen3:4b-16k", "hi"]


def test_opencode_paid_key_is_env_reference(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")
    inv = agent("opencode", provider="mistral", model="mistral-small-latest").build("hi")
    cfg = json.loads(inv.env["OPENCODE_CONFIG_CONTENT"])
    assert cfg["provider"]["doesitfire"]["options"]["apiKey"] == "{env:MISTRAL_API_KEY}"
    assert cfg["provider"]["doesitfire"]["options"]["baseURL"] == "https://api.mistral.ai/v1"


def test_codex_skill_path_detection():
    found = Codex.skills_in_command("bash -lc 'cat r1/commit-message/SKILL.md && cat x/SKILL.md'", SKILLS)
    assert found == ["commit-message", "x"]
    assert Codex.skills_in_command("ls .agents/skills", SKILLS) == []


def test_claude_skill_name_normalization():
    a = agent("claude-code")
    obs = Observation()
    line = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "/Commit-Message"}}]},
        }
    )
    a.feed(line, obs, SKILLS)
    assert obs.activated == ["commit-message"]


def test_feed_ignores_garbage():
    a = agent("opencode")
    obs = Observation()
    for line in ["", "not json", "{broken", "[1,2]", '{"type": "unknown"}']:
        a.feed(line, obs, SKILLS)
    assert obs.activated == [] and obs.error is None


def test_early_stop_only_for_local_models(monkeypatch):
    local = agent("codex")
    obs = Observation(activated=["regex-explainer"])
    assert local.should_stop(obs, SKILLS)
    assert not local.should_stop(Observation(), SKILLS)
    assert local.should_stop(Observation(tool_calls=3), SKILLS)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    paid = agent("codex", provider="openai", model="gpt-x")
    assert not paid.should_stop(obs, SKILLS)


def test_errors_are_captured():
    a = agent("opencode")
    obs = Observation()
    a.feed(
        json.dumps({"type": "error", "error": {"name": "APIError", "data": {"message": "model not found"}}}),
        obs,
        SKILLS,
    )
    assert obs.error == "model not found"
    c = agent("codex")
    obs = Observation()
    c.feed(json.dumps({"type": "error", "message": "Reconnecting... 1/5"}), obs, SKILLS)
    assert obs.error is None
    c.feed(json.dumps({"type": "turn.failed", "error": {"message": "boom"}}), obs, SKILLS)
    assert obs.error == "boom"
