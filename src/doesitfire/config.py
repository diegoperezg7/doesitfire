"""doesitfire.yaml: which skills to test, with which prompts, on which agents."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .errors import DoesItFireError
from .providers import PROVIDER_NAMES, SUPPORTED, check_supported

AGENTS = ("claude-code", "codex", "opencode")
CONFIG_NAME = "doesitfire.yaml"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    should_fire: list[str]
    should_not_fire: list[str]


@dataclass
class AgentConfig:
    name: str
    provider: str
    model: str
    price_input: float | None = None  # USD per million input tokens
    price_output: float | None = None  # USD per million output tokens


@dataclass
class Config:
    skills: list[Skill]
    agents: list[AgentConfig]
    repeats: int = 3
    timeout: int = 300
    max_turns: int = 2
    cpus: float = 1.0
    memory: str = "1g"
    base_dir: Path = field(default_factory=Path.cwd)


def parse_frontmatter(text: str) -> dict:
    """Return the YAML frontmatter of a SKILL.md as a dict (empty if none).

    Raises ValueError when the frontmatter exists but is not valid YAML.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError as exc:
        raise ValueError(str(exc).splitlines()[0]) from None
    return data if isinstance(data, dict) else {}


def load_skill_dir(path: Path) -> tuple[str, str]:
    skill_md = path / "SKILL.md"
    if not skill_md.is_file():
        raise DoesItFireError(f"No SKILL.md in {path}. Each skill entry must point to a skill directory.")
    try:
        meta = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DoesItFireError(
            f"The frontmatter of {skill_md} is not valid YAML ({exc}). Quote values that contain "
            "': ', for example description: \"...\"."
        ) from None
    name = str(meta.get("name") or path.name).strip()
    description = str(meta.get("description") or "").strip()
    if not description:
        raise DoesItFireError(
            f"{skill_md} has no 'description' in its frontmatter. Agents decide whether to use a "
            "skill from that description, so it is required."
        )
    if not _NAME_RE.match(name):
        raise DoesItFireError(f"Skill name '{name}' in {skill_md} must be lowercase letters, digits and hyphens.")
    return name, description


def _str_list(value, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise DoesItFireError(f"{where} must be a list of non-empty strings.")
    return [v.strip() for v in value]


def _positive(data: dict, key: str, default, kind=int):
    value = data.get(key, default)
    try:
        value = kind(value)
    except (TypeError, ValueError):
        raise DoesItFireError(f"'{key}' must be a number.") from None
    if value <= 0:
        raise DoesItFireError(f"'{key}' must be greater than 0.")
    return value


def parse_config(data: dict, base_dir: Path) -> Config:
    if not isinstance(data, dict):
        raise DoesItFireError(f"{CONFIG_NAME} must be a YAML mapping.")

    raw_agents = data.get("agents") or {}
    if not isinstance(raw_agents, dict) or not raw_agents:
        raise DoesItFireError(f"{CONFIG_NAME}: 'agents' must map agent names ({', '.join(AGENTS)}) to settings.")
    agents: list[AgentConfig] = []
    for name, spec in raw_agents.items():
        if name not in AGENTS:
            raise DoesItFireError(f"Unknown agent '{name}'. Supported in v0.1: {', '.join(AGENTS)}.")
        if spec is False or (isinstance(spec, dict) and spec.get("enabled") is False):
            continue
        if not isinstance(spec, dict) or not spec.get("provider") or not spec.get("model"):
            raise DoesItFireError(f"Agent '{name}' needs 'provider' and 'model'.")
        provider = str(spec["provider"])
        if provider not in PROVIDER_NAMES:
            raise DoesItFireError(
                f"Agent '{name}': unknown provider '{provider}'. Use one of: {', '.join(PROVIDER_NAMES)}."
            )
        check_supported(name, provider)
        price = spec.get("price") or {}
        agents.append(
            AgentConfig(
                name=name,
                provider=provider,
                model=str(spec["model"]),
                price_input=float(price["input"]) if "input" in price else None,
                price_output=float(price["output"]) if "output" in price else None,
            )
        )
    if not agents:
        raise DoesItFireError("All agents are disabled. Enable at least one.")

    raw_skills = data.get("skills")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise DoesItFireError(f"{CONFIG_NAME}: 'skills' must be a non-empty list.")
    skills: list[Skill] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw_skills):
        if not isinstance(entry, dict) or "path" not in entry:
            raise DoesItFireError(f"skills[{i}] needs a 'path' to a skill directory.")
        path = (base_dir / str(entry["path"])).resolve()
        name, description = load_skill_dir(path)
        if name in seen:
            raise DoesItFireError(f"Skill '{name}' is listed twice.")
        seen.add(name)
        should = _str_list(entry.get("should_fire"), f"skills[{i}].should_fire")
        should_not = _str_list(entry.get("should_not_fire"), f"skills[{i}].should_not_fire")
        if not should and not should_not:
            raise DoesItFireError(f"Skill '{name}' has no prompts. Add should_fire and/or should_not_fire.")
        skills.append(Skill(name, description, path, should, should_not))

    return Config(
        skills=skills,
        agents=agents,
        repeats=_positive(data, "repeats", 3),
        timeout=_positive(data, "timeout", 300),
        max_turns=_positive(data, "max_turns", 2),
        cpus=_positive(data, "cpus", 1.0, float),
        memory=str(data.get("memory", "1g")),
        base_dir=base_dir,
    )


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise DoesItFireError(f"{path} not found. Run 'doesitfire init' to create one.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DoesItFireError(f"{path} is not valid YAML: {exc}") from None
    return parse_config(data, path.parent.resolve())


TEMPLATE = """\
# doesitfire.yaml - which skills to test, and on which agents.
# Docs: https://github.com/diegoperezg7/doesitfire#configuration

repeats: 3        # runs per prompt and agent; activation is not deterministic
timeout: 300      # seconds per agent run
max_turns: 2      # agent turns per run; activation happens in the first one

agents:
  # Local and free: needs Ollama (https://ollama.com) with a 16k context model,
  # see the README. Paid providers read keys from env vars only.
  claude-code: {{provider: ollama, model: doesitfire-qwen3:4b-16k}}   # or provider: anthropic, model: claude-haiku-5-5
  codex:       {{provider: ollama, model: doesitfire-qwen3:4b-16k}}   # or provider: openai
  opencode:    {{provider: ollama, model: doesitfire-qwen3:4b-16k}}   # or provider: mistral / openrouter

skills:
{skills}
"""

SKILL_TEMPLATE = """\
  - path: {path}
    should_fire:          # prompts that SHOULD load this skill
      - "TODO: a request this skill is made for"
      - "TODO: the same need, phrased differently"
    should_not_fire:      # near misses that should NOT load it
      - "TODO: a related request the skill does not cover"
      - "TODO: an unrelated coding question"
"""


def render_template(skill_dirs: list[Path], base_dir: Path) -> str:
    if skill_dirs:
        parts = []
        for d in skill_dirs:
            try:
                rel = d.relative_to(base_dir)
            except ValueError:
                rel = d
            parts.append(SKILL_TEMPLATE.format(path=rel.as_posix()))
        skills = "".join(parts).rstrip("\n")
    else:
        skills = SKILL_TEMPLATE.format(path="path/to/my-skill").rstrip("\n")
    return TEMPLATE.format(skills=skills)


def find_skill_dirs(root: Path) -> list[Path]:
    """Skill directories under root (anything containing a SKILL.md), skipping hidden and venv dirs."""
    found = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        rel_parts = skill_md.relative_to(root).parts
        if any(p in ("node_modules", ".venv", "venv", ".git") for p in rel_parts):
            continue
        found.append(skill_md.parent)
    return found


__all__ = [
    "AGENTS",
    "AgentConfig",
    "CONFIG_NAME",
    "Config",
    "SUPPORTED",
    "Skill",
    "find_skill_dirs",
    "load_config",
    "parse_config",
    "parse_frontmatter",
    "render_template",
]
