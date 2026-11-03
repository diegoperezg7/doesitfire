"""How to run each agent CLI headless and how to tell, from its JSON events,
whether it activated a skill.

- Claude Code: a ``Skill`` tool_use in ``claude -p --output-format stream-json``.
- OpenCode: its native ``skill`` tool in ``opencode run --format json``.
- Codex: no activation event exists, so we look for the agent reading
  ``<skill>/SKILL.md`` in the ``command_execution`` items of ``codex exec --json``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .config import AgentConfig
from .providers import Provider, container_url, resolve_key

CLI_VERSIONS = {"claude-code": "2.1.317", "codex": "0.166.0", "opencode": "1.19.5"}
SKILLS_DIRS = {"claude-code": ".claude/skills", "codex": ".agents/skills", "opencode": ".opencode/skills"}
EXPERIMENTAL = {"codex"}  # activation is inferred from a file read, not reported by the CLI


@dataclass
class Invocation:
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)  # plain values (no secrets)
    secret_env: dict[str, str] = field(default_factory=dict)  # passed to docker by name only
    allow: list[str] = field(default_factory=list)  # base URLs the egress proxy must allow


@dataclass
class Observation:
    activated: list[str] = field(default_factory=list)  # skill names, in order, deduplicated
    input_tokens: int = 0
    output_tokens: int = 0
    reported_cost: float | None = None
    error: str | None = None
    tool_calls: int = 0
    usage_seen: bool = False

    def add(self, skill: str) -> None:
        if skill not in self.activated:
            self.activated.append(skill)


class Agent:
    name = ""

    def __init__(self, cfg: AgentConfig, provider: Provider, max_turns: int):
        self.cfg = cfg
        self.provider = provider
        self.max_turns = max_turns

    @property
    def skills_dir(self) -> str:
        return SKILLS_DIRS[self.name]

    def build(self, prompt: str) -> Invocation:  # pragma: no cover - abstract
        raise NotImplementedError

    def feed(self, line: str, obs: Observation, skills: set[str]) -> None:
        """Update the observation with one line of the agent's stdout."""
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if isinstance(event, dict):
            self.on_event(event, obs, skills)

    def on_event(self, event: dict, obs: Observation, skills: set[str]) -> None:  # pragma: no cover
        raise NotImplementedError

    def parse(self, stdout: str, skills: set[str]) -> Observation:
        obs = Observation()
        for line in stdout.splitlines():
            self.feed(line, obs, skills)
        return obs

    def should_stop(self, obs: Observation, skills: set[str]) -> bool:
        """Stop early once the outcome is known: a tested skill fired, or the turn cap was hit.

        Only for local models; with paid providers we let the CLI finish so it reports usage.
        """
        if not self.provider.local:
            return False
        return any(s in skills for s in obs.activated) or obs.tool_calls > self.max_turns


def _norm_skill(value) -> str:
    name = str(value or "").strip().lstrip("/").lower()
    return name.split(":")[-1].split()[0] if name else ""


class ClaudeCode(Agent):
    name = "claude-code"

    def build(self, prompt: str) -> Invocation:
        p = self.provider
        base = container_url(p.anthropic_base or "")
        env = {
            "ANTHROPIC_BASE_URL": base,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "API_TIMEOUT_MS": "900000",
        }
        secret: dict[str, str] = {}
        key = resolve_key(self.name, p)
        if p.name == "ollama":
            env["ANTHROPIC_AUTH_TOKEN"] = "ollama"
        elif p.name == "openrouter" and key:
            secret["ANTHROPIC_AUTH_TOKEN"] = key[1]
            env["ANTHROPIC_API_KEY"] = ""
        elif key:
            secret[key[0]] = key[1]
        if "claude" not in self.cfg.model.lower():
            # Non-Claude models: route every internal model slot to the same model, and give
            # the skill listing the budget a 200k-context Claude model would get. Without it
            # Claude Code lists skills by name only, which no real user would see.
            for slot in (
                "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "CLAUDE_CODE_SUBAGENT_MODEL",
            ):
                env[slot] = self.cfg.model
            env["SLASH_COMMAND_TOOL_CHAR_BUDGET"] = "8000"
        tools = "Skill,Read,Glob,Grep"
        argv = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self.cfg.model,
            "--max-turns",
            str(self.max_turns),
            "--tools",
            tools,
            "--allowedTools",
            tools,
            "--disallowedTools",
            "Bash,Write,Edit,NotebookEdit,WebFetch,WebSearch,Task",
            "--strict-mcp-config",
        ]
        return Invocation(argv, env, secret, [base])

    def on_event(self, event: dict, obs: Observation, skills: set[str]) -> None:
        etype = event.get("type")
        if etype == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    obs.tool_calls += 1
                    if block.get("name") == "Skill":
                        args = block.get("input") or {}
                        name = _norm_skill(args.get("skill") or args.get("command") or args.get("name"))
                        if name:
                            obs.add(name)
        elif etype == "result":
            usage = event.get("usage") or {}
            obs.usage_seen = True
            obs.input_tokens += (
                int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_read_input_tokens") or 0)
                + int(usage.get("cache_creation_input_tokens") or 0)
            )
            obs.output_tokens += int(usage.get("output_tokens") or 0)
            if event.get("total_cost_usd") is not None:
                obs.reported_cost = float(event["total_cost_usd"])
            if event.get("is_error") and event.get("subtype") not in ("error_max_turns",):
                obs.error = str(event.get("result") or event.get("subtype") or "error")[:300]
        elif etype == "system" and event.get("subtype") == "api_retry" and event.get("attempt", 0) >= 3:
            obs.error = f"model API retrying (status {event.get('error_status')}, {event.get('error')})"


class Codex(Agent):
    name = "codex"

    def build(self, prompt: str) -> Invocation:
        p = self.provider
        base = container_url(p.openai_base)
        provider_toml = f'{{name="doesitfire",base_url="{base}",wire_api="responses"'
        secret: dict[str, str] = {}
        key = resolve_key(self.name, p)
        if key:
            secret[key[0]] = key[1]
            provider_toml += f',env_key="{key[0]}"'
        provider_toml += "}"
        argv = [
            "codex",
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--ephemeral",
            # Codex's own sandbox (bubblewrap) cannot start in an unprivileged container. The
            # container is the sandbox: read-only root, no capabilities, no network but the model.
            "--dangerously-bypass-approvals-and-sandbox",
            "-c",
            "analytics.enabled=false",
            "-c",
            "model_provider=doesitfire",
            "-c",
            f"model_providers.doesitfire={provider_toml}",
            "-m",
            self.cfg.model,
        ]
        argv.append(prompt)
        return Invocation(argv, {"NO_COLOR": "1"}, secret, [base])

    @staticmethod
    def skills_in_command(command: str, skills: set[str]) -> list[str]:
        found: list[str] = []
        for match in re.finditer(r"([A-Za-z0-9_.-]+)/SKILL\.md", command):
            name = match.group(1).lower()
            if name not in found:
                found.append(name)
        return found

    def on_event(self, event: dict, obs: Observation, skills: set[str]) -> None:
        etype = event.get("type")
        item = event.get("item") or {}
        if etype == "item.started" and item.get("type") in ("command_execution", "mcp_tool_call"):
            obs.tool_calls += 1
            text = item.get("command") or json.dumps(item.get("arguments") or "")
            for name in self.skills_in_command(str(text), skills):
                obs.add(name)
        elif etype == "turn.completed":
            usage = event.get("usage") or {}
            obs.usage_seen = True
            obs.input_tokens += int(usage.get("input_tokens") or 0)
            obs.output_tokens += int(usage.get("output_tokens") or 0)
        elif etype in ("turn.failed", "error") and not str(event.get("message", "")).startswith("Reconnecting"):
            msg = (event.get("error") or {}).get("message") if etype == "turn.failed" else event.get("message")
            obs.error = str(msg or etype)[:300]


class OpenCode(Agent):
    name = "opencode"

    def build(self, prompt: str) -> Invocation:
        p = self.provider
        secret: dict[str, str] = {}
        key = resolve_key(self.name, p)
        if p.name == "anthropic":
            npm, base = "@ai-sdk/anthropic", container_url((p.anthropic_base or "") + "/v1")
        else:
            npm, base = "@ai-sdk/openai-compatible", container_url(p.openai_base)
        options = {"baseURL": base, "apiKey": "ollama"}
        if key:
            secret[key[0]] = key[1]
            options["apiKey"] = "{env:" + key[0] + "}"
        model_cfg: dict = {"name": self.cfg.model}
        config = {
            "$schema": "https://opencode.ai/config.json",
            "autoupdate": False,
            "share": "disabled",
            "provider": {
                "doesitfire": {
                    "npm": npm,
                    "name": "doesitfire",
                    "options": options,
                    "models": {self.cfg.model: model_cfg},
                }
            },
            "permission": {"edit": "deny", "bash": "deny", "webfetch": "deny"},
            "agent": {"build": {"steps": self.max_turns}, "title": {"disable": True}},
        }
        env = {
            "OPENCODE_CONFIG_CONTENT": json.dumps(config),
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
        }
        argv = ["opencode", "run", "--format", "json", "-m", f"doesitfire/{self.cfg.model}", prompt]
        return Invocation(argv, env, secret, [base])

    def on_event(self, event: dict, obs: Observation, skills: set[str]) -> None:
        etype = event.get("type")
        part = event.get("part") or {}
        if etype == "tool_use":
            obs.tool_calls += 1
            if part.get("tool") == "skill":
                name = _norm_skill(((part.get("state") or {}).get("input") or {}).get("name"))
                if name:
                    obs.add(name)
        elif etype == "step_finish":
            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            obs.usage_seen = True
            obs.input_tokens += int(tokens.get("input") or 0) + int(cache.get("read") or 0)
            obs.output_tokens += int(tokens.get("output") or 0) + int(tokens.get("reasoning") or 0)
            if part.get("cost") is not None:
                obs.reported_cost = (obs.reported_cost or 0.0) + float(part["cost"])
        elif etype == "error":
            err = event.get("error") or {}
            obs.error = str((err.get("data") or {}).get("message") or err.get("name") or "error")[:300]


AGENT_CLASSES: dict[str, type[Agent]] = {"claude-code": ClaudeCode, "codex": Codex, "opencode": OpenCode}


def make_agent(cfg: AgentConfig, provider: Provider, max_turns: int) -> Agent:
    return AGENT_CLASSES[cfg.name](cfg, provider, max_turns)
