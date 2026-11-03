import pytest

from doesitfire.errors import DoesItFireError
from doesitfire.providers import container_url, get_provider, host_port, resolve_key


def test_missing_key_names_the_variable(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(DoesItFireError, match="MISTRAL_API_KEY"):
        resolve_key("opencode", get_provider("mistral"))


def test_local_needs_no_key():
    assert resolve_key("codex", get_provider("ollama")) is None


def test_ollama_host_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11500")
    p = get_provider("ollama")
    assert p.openai_base == "http://localhost:11500/v1"
    assert container_url(p.openai_base) == "http://host.docker.internal:11500/v1"


def test_urls():
    assert host_port("https://api.mistral.ai/v1") == "api.mistral.ai:443"
    assert host_port("http://host.docker.internal:11434/v1") == "host.docker.internal:11434"
    assert container_url("https://openrouter.ai/api/v1") == "https://openrouter.ai/api/v1"


def test_unknown_provider():
    with pytest.raises(DoesItFireError, match="Unknown provider"):
        get_provider("acme")
