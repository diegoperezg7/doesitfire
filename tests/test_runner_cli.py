import json
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

import doesitfire.runner as runner
from doesitfire import cli
from doesitfire.agents import Observation
from doesitfire.config import AgentConfig, parse_config
from doesitfire.errors import BudgetExceeded, DoesItFireError
from doesitfire.providers import get_provider
from doesitfire.sandbox import RunOutput

ROOT = Path(__file__).resolve().parent.parent


def cfg_for(tmp_path, agents):
    skill = ROOT / "examples" / "skills" / "commit-message"
    return parse_config(
        {
            "repeats": 2,
            "agents": agents,
            "skills": [{"path": str(skill), "should_fire": ["a", "b"], "should_not_fire": ["c"]}],
        },
        tmp_path,
    )


def test_run_cost_rules(monkeypatch):
    local = get_provider("ollama")
    assert runner.run_cost(local, AgentConfig("codex", "ollama", "m"), Observation(input_tokens=10**6)) == 0
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    paid = get_provider("openai")
    a = AgentConfig("codex", "openai", "m", price_input=1.0, price_output=10.0)
    used = Observation(input_tokens=1_000_000, output_tokens=100_000, usage_seen=True)
    assert runner.run_cost(paid, a, used) == pytest.approx(2.0)
    unknown = Observation()  # killed before usage: charged the estimate, never zero
    assert runner.run_cost(paid, a, unknown) == pytest.approx(0.02 + 0.01)
    reported = Observation(usage_seen=True, reported_cost=5.0)
    assert runner.run_cost(paid, a, reported) == 5.0


def test_paid_provider_requires_price(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    cfg = cfg_for(tmp_path, {"codex": {"provider": "openai", "model": "gpt-x"}})
    with pytest.raises(DoesItFireError, match="has no price"):
        runner.preflight(cfg)


def test_missing_key_preflight(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = cfg_for(tmp_path, {"opencode": {"provider": "openrouter", "model": "x", "price": {"input": 1, "output": 1}}})
    with pytest.raises(DoesItFireError, match="OPENROUTER_API_KEY"):
        runner.preflight(cfg)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_ollama_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", f"http://127.0.0.1:{_free_port()}")
    cfg = cfg_for(tmp_path, {"codex": {"provider": "ollama", "model": "m"}})
    with pytest.raises(DoesItFireError, match="Ollama is not reachable"):
        runner.preflight(cfg)


def test_ollama_model_not_found(tmp_path, monkeypatch):
    from mockmodel import serve

    srv = serve(0, "127.0.0.1")
    try:
        monkeypatch.setenv("OLLAMA_HOST", f"http://127.0.0.1:{srv.server_address[1]}")
        cfg = cfg_for(tmp_path, {"codex": {"provider": "ollama", "model": "missing-model"}})
        with pytest.raises(DoesItFireError, match="not found in Ollama"):
            runner.preflight(cfg)
        ok = cfg_for(tmp_path, {"codex": {"provider": "ollama", "model": "mock-model"}})
        runner.preflight(ok)
    finally:
        srv.shutdown()


class FakeBox:
    def __init__(self, allow, image=None):
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def proxy_denials(self):
        return ["deny CONNECT example.com:443"]

    def run(self, inv, skills_dir, staged, timeout, cpus, memory, on_line):
        self.calls += 1
        prompt = inv.argv[-1]
        lines = []
        if prompt in ("a", "c"):  # fires on "a" and on the should-not prompt "c"
            lines.append(
                json.dumps(
                    {"type": "tool_use", "part": {"tool": "skill", "state": {"input": {"name": "commit-message"}}}}
                )
            )
        lines.append(
            json.dumps({"type": "step_finish", "part": {"tokens": {"input": 20000, "output": 500}, "cost": 0}})
        )
        for ln in lines:
            on_line(ln)
        return RunOutput("\n".join(lines), "", 0, False, False, 0.1)


@pytest.fixture
def fake_docker(monkeypatch):
    monkeypatch.setattr(runner, "Sandbox", FakeBox)
    monkeypatch.setattr(runner, "check_docker", lambda: "29.0")
    monkeypatch.setattr(runner, "image_exists", lambda image: True)


def test_run_matrix_with_fake_sandbox(tmp_path, fake_docker, monkeypatch):
    monkeypatch.setattr(runner, "check_ollama_model", lambda p, m: None)
    cfg = cfg_for(tmp_path, {"opencode": {"provider": "ollama", "model": "m"}})
    seen = []
    results = runner.run_matrix(cfg, checkpoint=lambda r: seen.append(len(r["trials"])))
    assert len(results["trials"]) == 6 and seen == [1, 2, 3, 4, 5, 6]
    fired = {(t["prompt"], t["fired"]) for t in results["trials"]}
    assert fired == {("a", True), ("b", False), ("c", True)}
    assert results["cost_usd"] == 0 and results["blocked_egress"] == ["deny CONNECT example.com:443"]


def test_budget_stops_with_partial_results(tmp_path, fake_docker, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    cfg = cfg_for(
        tmp_path, {"opencode": {"provider": "openrouter", "model": "x", "price": {"input": 10.0, "output": 10.0}}}
    )
    # each run: 20k in + 0.5k out at 10 USD/M = 0.205 USD
    with pytest.raises(BudgetExceeded) as info:
        runner.run_matrix(cfg, max_cost=0.5)
    partial = info.value.results
    assert len(partial["trials"]) == 2
    assert partial["partial"] is True and partial["cost_usd"] == pytest.approx(0.41)
    assert "--max-cost" in partial["stop_reason"]


def test_cli_run_budget_exit_code(tmp_path, fake_docker, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    skill = ROOT / "examples" / "skills" / "commit-message"
    (tmp_path / "doesitfire.yaml").write_text(
        "agents:\n  opencode: {provider: openrouter, model: x, price: {input: 10, output: 10}}\n"
        f"skills:\n  - path: {skill}\n    should_fire: [a, b]\n    should_not_fire: [c]\n",
        encoding="utf-8",
    )
    res = CliRunner().invoke(
        cli.app,
        ["run", "-c", str(tmp_path / "doesitfire.yaml"), "-o", str(tmp_path / "out"), "--max-cost", "0.3", "--no-open"],
    )
    assert res.exit_code == 3
    assert (tmp_path / "out" / "results.json").exists()
    assert json.loads((tmp_path / "out" / "results.json").read_text())["partial"] is True


def test_cli_thresholds_exit_1(tmp_path, fake_docker, monkeypatch):
    monkeypatch.setattr(runner, "check_ollama_model", lambda p, m: None)
    skill = ROOT / "examples" / "skills" / "commit-message"
    (tmp_path / "doesitfire.yaml").write_text(
        "agents:\n  opencode: {provider: ollama, model: m}\n"
        f"skills:\n  - path: {skill}\n    should_fire: [a, b]\n    should_not_fire: [c]\n",
        encoding="utf-8",
    )
    args = ["run", "-c", str(tmp_path / "doesitfire.yaml"), "-o", str(tmp_path / "o"), "--no-open", "--repeats", "1"]
    assert CliRunner().invoke(cli.app, args).exit_code == 0
    res = CliRunner().invoke(cli.app, [*args, "--min-recall", "0.9"])
    assert res.exit_code == 1
    for name in ("results.json", "report.html", "junit.xml", "badge.svg", "badge.json"):
        assert (tmp_path / "o" / name).exists()


def run_main(monkeypatch, capsys, argv):
    monkeypatch.setattr("sys.argv", ["doesitfire", *argv])
    with pytest.raises(SystemExit) as info:
        cli.main()
    return info.value.code, capsys.readouterr()


def test_main_prints_clean_errors(monkeypatch, capsys, tmp_path):
    code, out = run_main(monkeypatch, capsys, ["run", "-c", str(tmp_path / "missing.yaml")])
    assert code == 2 and "doesitfire init" in out.err and "Traceback" not in out.err


def test_docker_not_installed_error(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(runner, "check_ollama_model", lambda p, m: None)
    monkeypatch.setenv("PATH", str(tmp_path))  # no docker binary anywhere
    code, out = run_main(monkeypatch, capsys, ["run", "-c", str(ROOT / "examples" / "doesitfire.yaml"), "--no-open"])
    assert code == 2 and "Docker is not installed" in out.err


def test_docker_not_running_error(monkeypatch, tmp_path):
    import doesitfire.sandbox as sandbox

    fake = tmp_path / "docker"
    fake.write_text("#!/bin/sh\necho 'Cannot connect to the Docker daemon' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(DoesItFireError, match="Docker is not running"):
        sandbox.check_docker()


def test_init_and_demo(tmp_path):
    (tmp_path / "skills" / "x").mkdir(parents=True)
    (tmp_path / "skills" / "x" / "SKILL.md").write_text('---\nname: x\ndescription: "d"\n---\n')
    r = CliRunner().invoke(cli.app, ["init", str(tmp_path)])
    assert r.exit_code == 0 and (tmp_path / "doesitfire.yaml").exists()
    assert CliRunner().invoke(cli.app, ["init", str(tmp_path)]).exit_code != 0
    r = CliRunner().invoke(cli.app, ["demo", "--no-open", "-o", str(tmp_path / "demo")])
    assert r.exit_code == 0, r.output
    assert "RECORDED" in r.output
    data = json.loads((tmp_path / "demo" / "results.json").read_text())
    assert data["recorded"] is True and len(data["trials"]) > 0


def test_report_rejects_foreign_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"hello": 1}')
    r = CliRunner().invoke(cli.app, ["report", str(p)])
    assert r.exit_code != 0
