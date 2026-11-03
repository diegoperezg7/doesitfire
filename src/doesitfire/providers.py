"""Model provider presets and which agent can talk to which provider.

Keys are read from environment variables only and are never written to disk,
printed, or passed on a command line: Docker receives the variable *name* and
copies the value from this process's environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from .errors import DoesItFireError


@dataclass(frozen=True)
class Provider:
    name: str
    openai_base: str  # OpenAI-compatible base URL (".../v1")
    key_env: str | None  # env var holding the API key; None for local models
    anthropic_base: str | None = None  # Anthropic Messages-compatible base, if any
    responses_api: bool = False  # serves the OpenAI Responses API (needed by Codex)
    local: bool = False

    @property
    def paid(self) -> bool:
        return not self.local


def _ollama_root() -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")
    if "://" not in host:
        host = "http://" + host
    parsed = urlparse(host)
    if parsed.hostname in ("0.0.0.0", "", None):
        host = f"{parsed.scheme}://localhost:{parsed.port or 11434}"
    return host


def get_provider(name: str) -> Provider:
    if name == "ollama":
        root = _ollama_root()
        return Provider("ollama", root + "/v1", None, anthropic_base=root, responses_api=True, local=True)
    if name == "openrouter":
        return Provider(
            "openrouter",
            "https://openrouter.ai/api/v1",
            "OPENROUTER_API_KEY",
            anthropic_base="https://openrouter.ai/api",
            responses_api=True,
        )
    if name == "openai":
        return Provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY", responses_api=True)
    if name == "mistral":
        return Provider("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY")
    if name == "anthropic":
        return Provider(
            "anthropic",
            "https://api.anthropic.com/v1",
            "ANTHROPIC_API_KEY",
            anthropic_base="https://api.anthropic.com",
        )
    raise DoesItFireError(f"Unknown provider '{name}'. Use one of: {', '.join(PROVIDER_NAMES)}.")


PROVIDER_NAMES = ("ollama", "openrouter", "openai", "mistral", "anthropic")

# Which providers each agent CLI can use, and through which API.
SUPPORTED = {
    "claude-code": ("anthropic", "ollama", "openrouter"),  # Anthropic Messages API
    "codex": ("ollama", "openai", "openrouter"),  # OpenAI Responses API
    "opencode": ("ollama", "openrouter", "openai", "mistral", "anthropic"),
}


def check_supported(agent: str, provider: str) -> None:
    if provider not in SUPPORTED[agent]:
        why = {
            "claude-code": "Claude Code speaks the Anthropic Messages API",
            "codex": "Codex needs the OpenAI Responses API",
        }.get(agent, "")
        raise DoesItFireError(
            f"Agent '{agent}' cannot use provider '{provider}'"
            + (f" ({why})" if why else "")
            + f". Supported: {', '.join(SUPPORTED[agent])}."
        )


def resolve_key(agent: str, provider: Provider) -> tuple[str, str] | None:
    """Return (env var name, value) for the key this agent needs, or None for local models."""
    if provider.key_env is None:
        return None
    candidates = [provider.key_env]
    if agent == "claude-code" and provider.name == "anthropic":
        # A Claude subscription token from `claude setup-token` works too.
        candidates.append("CLAUDE_CODE_OAUTH_TOKEN")
    for var in candidates:
        value = os.environ.get(var, "").strip()
        if value:
            return var, value
    raise DoesItFireError(
        f"Missing API key for provider '{provider.name}' (agent '{agent}'). "
        f"Set the {' or '.join(candidates)} environment variable, or switch the agent to "
        "provider 'ollama' in doesitfire.yaml."
    )


def container_url(url: str) -> str:
    """Rewrite localhost URLs so they work from inside a container."""
    parsed = urlparse(url)
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        netloc = "host.docker.internal" + (f":{parsed.port}" if parsed.port else "")
        return parsed._replace(netloc=netloc).geturl()
    return url


def host_port(url: str) -> str:
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{parsed.hostname}:{port}"
