from pathlib import Path

import pytest
import yaml

from doesitfire.config import find_skill_dirs, load_config, parse_config, parse_frontmatter, render_template
from doesitfire.errors import DoesItFireError

ROOT = Path(__file__).resolve().parent.parent


def write_skill(root: Path, name: str, description: str | None = "Does a thing. Use when asked.") -> Path:
    d = root / name
    d.mkdir(parents=True)
    fm = f"name: {name}\n" + (f'description: "{description}"\n' if description is not None else "")
    (d / "SKILL.md").write_text(f"---\n{fm}---\n\n# {name}\n", encoding="utf-8")
    return d


def base(tmp_path, **over):
    write_skill(tmp_path, "my-skill")
    data = {
        "agents": {"claude-code": {"provider": "ollama", "model": "m"}},
        "skills": [{"path": "my-skill", "should_fire": ["a"], "should_not_fire": ["b"]}],
    }
    data.update(over)
    return data


def test_example_config_loads():
    cfg = load_config(ROOT / "examples" / "doesitfire.yaml")
    assert [s.name for s in cfg.skills] == ["commit-message", "regex-explainer", "dockerfile-review"]
    assert all(len(s.should_fire) == 4 and len(s.should_not_fire) == 4 for s in cfg.skills)
    assert {a.name for a in cfg.agents} == {"claude-code", "codex", "opencode"}
    assert cfg.repeats == 3
    assert "\n" in cfg.skills[2].should_fire[0]  # real newlines in the Dockerfile prompts


def test_defaults_and_parse(tmp_path):
    cfg = parse_config(base(tmp_path), tmp_path)
    assert cfg.repeats == 3 and cfg.timeout == 300 and cfg.max_turns == 2
    assert cfg.skills[0].description.startswith("Does a thing")


def test_missing_file(tmp_path):
    with pytest.raises(DoesItFireError, match="doesitfire init"):
        load_config(tmp_path / "doesitfire.yaml")


def test_invalid_yaml(tmp_path):
    p = tmp_path / "doesitfire.yaml"
    p.write_text("agents: [unclosed", encoding="utf-8")
    with pytest.raises(DoesItFireError, match="not valid YAML"):
        load_config(p)


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"agents": {"cursor": {"provider": "ollama", "model": "m"}}}, "Unknown agent"),
        ({"agents": {"claude-code": {"provider": "mistral", "model": "m"}}}, "Anthropic Messages API"),
        ({"agents": {"codex": {"provider": "mistral", "model": "m"}}}, "Responses API"),
        ({"agents": {"opencode": {"provider": "acme", "model": "m"}}}, "unknown provider"),
        ({"agents": {"opencode": {"provider": "ollama"}}}, "needs 'provider' and 'model'"),
        ({"agents": {"opencode": False}}, "All agents are disabled"),
        ({"skills": []}, "non-empty list"),
        ({"skills": [{"path": "my-skill"}]}, "no prompts"),
        ({"skills": [{"path": "nope", "should_fire": ["x"]}]}, "No SKILL.md"),
        ({"skills": [{"path": "my-skill", "should_fire": "x"}]}, "list of non-empty strings"),
        ({"repeats": 0}, "greater than 0"),
        ({"timeout": "soon"}, "must be a number"),
    ],
)
def test_validation_errors(tmp_path, over, message):
    with pytest.raises(DoesItFireError, match=message):
        parse_config(base(tmp_path, **over), tmp_path)


def test_duplicate_skill(tmp_path):
    data = base(tmp_path)
    data["skills"].append(dict(data["skills"][0]))
    with pytest.raises(DoesItFireError, match="listed twice"):
        parse_config(data, tmp_path)


def test_skill_without_description(tmp_path):
    write_skill(tmp_path, "bare", description=None)
    data = base(tmp_path, skills=[{"path": "bare", "should_fire": ["x"]}])
    with pytest.raises(DoesItFireError, match="no 'description'"):
        parse_config(data, tmp_path)


def test_unquoted_colon_in_frontmatter_is_reported(tmp_path):
    d = tmp_path / "colon"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: colon\ndescription: Format: type(scope): x\n---\n", encoding="utf-8")
    data = base(tmp_path, skills=[{"path": "colon", "should_fire": ["x"]}])
    with pytest.raises(DoesItFireError, match="not valid YAML"):
        parse_config(data, tmp_path)


def test_frontmatter_absent():
    assert parse_frontmatter("# no frontmatter") == {}


def test_init_template_roundtrip(tmp_path):
    write_skill(tmp_path / ".claude" / "skills", "alpha")
    write_skill(tmp_path / "skills", "beta")
    write_skill(tmp_path / "node_modules" / "x", "ignored")
    dirs = find_skill_dirs(tmp_path)
    assert [d.name for d in dirs] == ["alpha", "beta"]
    text = render_template(dirs, tmp_path)
    data = yaml.safe_load(text)
    assert [s["path"] for s in data["skills"]] == [".claude/skills/alpha", "skills/beta"]
    cfg = parse_config(data, tmp_path)
    assert [s.name for s in cfg.skills] == ["alpha", "beta"]


def test_init_template_without_skills(tmp_path):
    data = yaml.safe_load(render_template([], tmp_path))
    assert data["skills"][0]["path"] == "path/to/my-skill"
