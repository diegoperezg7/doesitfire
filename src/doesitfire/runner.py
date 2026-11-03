"""Run the activation matrix: skills x prompts x agents x repeats."""

from __future__ import annotations

import datetime as dt
import platform
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .agents import CLI_VERSIONS, EXPERIMENTAL, Agent, Observation, make_agent
from .config import Config
from .errors import BudgetExceeded, DoesItFireError
from .providers import Provider, get_provider, resolve_key
from .sandbox import IMAGE, Sandbox, build_image, check_docker, image_exists, stage_skills

# Used for budgeting before the first real usage figure is known (doesitfire's plan
# assumed ~20k input tokens per CLI run).
EST_INPUT_TOKENS = 20_000
EST_OUTPUT_TOKENS = 1_000


def run_cost(provider: Provider, agent_cfg, obs: Observation) -> float:
    if provider.local:
        return 0.0
    pin, pout = agent_cfg.price_input or 0.0, agent_cfg.price_output or 0.0
    computed = obs.input_tokens * pin / 1e6 + obs.output_tokens * pout / 1e6
    if not obs.usage_seen:  # killed before reporting usage: charge the estimate, never zero
        computed = max(computed, EST_INPUT_TOKENS * pin / 1e6 + EST_OUTPUT_TOKENS * pout / 1e6)
    return round(max(computed, obs.reported_cost or 0.0), 6)


def preflight(cfg: Config) -> dict[str, Provider]:
    """Validate keys, prices and model availability before any container starts."""
    providers: dict[str, Provider] = {}
    for a in cfg.agents:
        p = get_provider(a.provider)
        resolve_key(a.name, p)  # raises a clear error naming the missing variable
        if p.paid and (a.price_input is None or a.price_output is None):
            raise DoesItFireError(
                f"Agent '{a.name}' uses paid provider '{p.name}' but has no price. Add "
                "'price: {input: <USD per 1M tokens>, output: <USD per 1M tokens>}' to it in "
                "doesitfire.yaml so --max-cost can be enforced."
            )
        if p.name == "ollama":
            check_ollama_model(p, a.model)
        providers[a.name] = p
    return providers


def check_ollama_model(p: Provider, model: str) -> None:
    import openai

    client = openai.OpenAI(base_url=p.openai_base, api_key="ollama", timeout=10, max_retries=0)
    try:
        ids = {m.id for m in client.models.list()}
    except (openai.APIConnectionError, openai.APITimeoutError):
        raise DoesItFireError(
            f"Ollama is not reachable at {p.openai_base.removesuffix('/v1')}. Start it with 'ollama serve' "
            "or set OLLAMA_HOST. On Linux, make it listen on all interfaces (OLLAMA_HOST=0.0.0.0) so "
            "containers can reach it."
        ) from None
    except openai.APIError as exc:
        raise DoesItFireError(f"Ollama answered with an error while listing models: {exc}") from None
    if model not in ids and f"{model}:latest" not in ids:
        raise DoesItFireError(
            f"Model '{model}' not found in Ollama. Available: {', '.join(sorted(ids)) or 'none'}. "
            "Agent prompts need a 16k context; create the model with: "
            "ollama pull qwen3:4b && ollama create doesitfire-qwen3:4b-16k -f ollama/Modelfile"
        )


def hardware() -> str | None:
    """A short CPU and memory label, e.g. 'Apple M4, 16 GB'. Best effort, no network."""
    import os
    import subprocess

    cpu, mem = None, None
    try:
        if platform.system() == "Darwin":
            cpu = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            mem = int(
                subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout.strip()
                or 0
            )
        elif platform.system() == "Linux":
            with open("/proc/cpuinfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        cpu = line.split(":", 1)[1].strip()
                        break
            mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    parts = [p for p in (cpu, f"{round(mem / 2**30)} GB" if mem else None) if p]
    return ", ".join(parts) or None


def host_info(docker_version: str | None) -> dict:
    return {
        "os": platform.system(),
        "arch": platform.machine(),
        "hardware": hardware(),
        "python": platform.python_version(),
        "docker": docker_version,
    }


def run_matrix(
    cfg: Config,
    max_cost: float = 1.0,
    log: Callable[[str], None] = print,
    progress: Callable[[dict], None] | None = None,
    checkpoint: Callable[[dict], None] | None = None,
    logs_dir: Path | None = None,
    resume: dict | None = None,
    image: str = IMAGE,
    rebuild: bool = False,
) -> dict:
    providers = preflight(cfg)
    docker_version = check_docker()
    if rebuild or not image_exists(image):
        build_image(image, log)

    agents: list[Agent] = [make_agent(a, providers[a.name], cfg.max_turns) for a in cfg.agents]
    skill_names = {s.name for s in cfg.skills}
    started = dt.datetime.now(dt.UTC)
    results: dict = {
        "schema": 1,
        "tool": "doesitfire",
        "version": __version__,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_s": None,
        "repeats": cfg.repeats,
        "max_turns": cfg.max_turns,
        "host": host_info(docker_version),
        "agents": [
            {
                "name": a.cfg.name,
                "cli_version": CLI_VERSIONS[a.cfg.name],
                "provider": a.provider.name,
                "model": a.cfg.model,
                "experimental": a.cfg.name in EXPERIMENTAL,
            }
            for a in agents
        ],
        "skills": [{"name": s.name, "description": s.description} for s in cfg.skills],
        "trials": [],
        "cost_usd": 0.0,
        "partial": False,
        "stop_reason": None,
        "sessions": 1,
        "recorded": False,
    }

    plan = [
        (rep, agent, skill, prompt, expect)
        for rep in range(cfg.repeats)
        for agent in agents
        for skill in cfg.skills
        for expect, prompts in (("fire", skill.should_fire), ("no_fire", skill.should_not_fire))
        for prompt in prompts
    ]
    previous_duration = 0.0
    if resume:
        # Keep finished trials of an interrupted run with the same plan, run only the rest.
        keys = {(a.cfg.name, s.name, p, e, r) for r, a, s, p, e in plan}
        kept = [
            t
            for t in resume.get("trials", [])
            if (t["agent"], t["skill"], t["prompt"], t["expect"], t["repeat"]) in keys
        ]
        done = {(t["agent"], t["skill"], t["prompt"], t["expect"], t["repeat"]) for t in kept}
        plan = [x for x in plan if (x[1].cfg.name, x[2].name, x[3], x[4], x[0]) not in done]
        results["trials"] = kept
        results["cost_usd"] = round(sum(t.get("cost_usd") or 0.0 for t in kept), 6)
        results["started_at"] = resume.get("started_at") or results["started_at"]
        results["sessions"] = int(resume.get("sessions") or 1) + 1
        previous_duration = float(resume.get("duration_s") or 0.0)
        log(f"Resuming: {len(kept)} runs already done, {len(plan)} to go.")
    max_seen: dict[str, float] = {}
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="doesitfire-") as tmp:
        staged = stage_skills([(s.name, s.path) for s in cfg.skills], Path(tmp) / "skills")
        allow = [u for a in agents for u in a.build("x").allow]
        developer_as_system = any(a.cfg.name == "codex" and a.provider.name == "ollama" for a in agents)
        with Sandbox(allow, image=image, developer_as_system=developer_as_system) as box:
            for i, (rep, agent, skill, prompt, expect) in enumerate(plan, 1):
                spent = results["cost_usd"]
                if agent.provider.paid:
                    pin, pout = agent.cfg.price_input or 0, agent.cfg.price_output or 0
                    estimate = max_seen.get(
                        agent.cfg.name, EST_INPUT_TOKENS * pin / 1e6 + EST_OUTPUT_TOKENS * pout / 1e6
                    )
                    if spent + estimate > max_cost:
                        results["partial"] = True
                        results["stop_reason"] = (
                            f"budget: spent {spent:.4f} USD, next {agent.cfg.name} run would cost about "
                            f"{estimate:.4f} USD, --max-cost is {max_cost:.2f} USD"
                        )
                        break
                trial = run_trial(box, agent, skill.name, prompt, expect, rep, staged, cfg, skill_names)
                raw = trial.pop("_raw")
                if logs_dir is not None:
                    logs_dir.mkdir(parents=True, exist_ok=True)
                    n = len(results["trials"]) + 1
                    name = f"{n:04d}-{agent.cfg.name}-{skill.name}-{expect}-r{rep}.jsonl"
                    (logs_dir / name).write_text(raw, encoding="utf-8")
                    trial["log"] = f"logs/{name}"
                cost = run_cost(agent.provider, agent.cfg, trial.pop("_obs"))
                trial["cost_usd"] = cost
                max_seen[agent.cfg.name] = max(max_seen.get(agent.cfg.name, 0.0), cost)
                results["cost_usd"] = round(results["cost_usd"] + cost, 6)
                results["trials"].append(trial)
                if progress:
                    progress({"done": i, "total": len(plan), "trial": trial})
                if checkpoint:
                    results["duration_s"] = round(previous_duration + time.monotonic() - t0, 1)
                    checkpoint(results)
            denials = box.proxy_denials()
    results["blocked_egress"] = sorted(set(denials))
    finished = dt.datetime.now(dt.UTC)
    results["finished_at"] = finished.isoformat(timespec="seconds")
    results["duration_s"] = round(previous_duration + time.monotonic() - t0, 1)
    if results["partial"]:
        raise BudgetExceeded(results["stop_reason"], results)
    return results


def run_trial(
    box: Sandbox,
    agent: Agent,
    skill: str,
    prompt: str,
    expect: str,
    rep: int,
    staged: Path,
    cfg: Config,
    skill_names: set[str],
) -> dict:
    inv = agent.build(prompt)
    obs = Observation()

    def on_line(line: str) -> bool:
        agent.feed(line, obs, skill_names)
        return agent.should_stop(obs, skill_names)

    out = box.run(inv, agent.skills_dir, staged, cfg.timeout, cfg.cpus, cfg.memory, on_line)
    fired = skill in obs.activated
    error = None
    if not fired:
        if out.timed_out:
            error = f"timeout after {cfg.timeout}s"
        elif obs.error:
            error = obs.error
        elif out.returncode not in (0,) and not out.stopped_early and not out.stdout.strip():
            tail = out.stderr.strip().splitlines()[-3:]
            error = f"exit {out.returncode}: {' | '.join(tail)[:300]}" if tail else f"exit {out.returncode}"
    return {
        "agent": agent.cfg.name,
        "skill": skill,
        "prompt": prompt,
        "expect": expect,
        "repeat": rep,
        "fired": fired,
        "activated": obs.activated,
        "error": error,
        "duration_s": out.duration_s,
        "input_tokens": obs.input_tokens,
        "output_tokens": obs.output_tokens,
        "_obs": obs,
        "_raw": out.stdout + (f"\n# stderr\n{out.stderr[-4000:]}" if out.stderr.strip() else ""),
    }
