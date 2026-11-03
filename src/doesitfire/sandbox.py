"""Docker isolation: every agent run happens in a throwaway container.

Layout per `doesitfire run`:

    [agent container] --internal network--> [egress proxy] --bridge--> model API only

- The internal network has no route out. The only peer is the egress proxy,
  which allows exactly the model API host:port and returns 403 for anything else.
- Agent containers: non-root, read-only root filesystem, tmpfs home, all Linux
  capabilities dropped, no-new-privileges, CPU/memory/pids limits, hard timeout.
- Skills are mounted read-only and copied into the agent's discovery directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from . import __version__
from .agents import Invocation
from .errors import DoesItFireError
from .providers import host_port

IMAGE = f"doesitfire-agents:{__version__}"
LABEL = "io.github.doesitfire.run"


def _docker(*args: str, timeout: float = 120, check: bool = True) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise DoesItFireError(
            "Docker is not installed. doesitfire runs every agent inside a container and refuses to run "
            "without one. Install Docker Desktop (macOS/Windows) or Docker Engine (Linux)."
        ) from None
    except subprocess.TimeoutExpired:
        raise DoesItFireError(
            f"'docker {args[0]}' timed out after {timeout:.0f}s. Is the Docker daemon healthy?"
        ) from None
    if check and proc.returncode != 0:
        raise DoesItFireError(f"'docker {' '.join(args[:2])}' failed: {proc.stderr.strip()[:400]}")
    return proc


def check_docker() -> str:
    """Return the Docker server version, or raise a clear error if Docker is not usable."""
    proc = _docker("info", "--format", "{{.ServerVersion}}", timeout=30, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise DoesItFireError(
            "Docker is not running. Start Docker Desktop (or the Docker daemon) and try again. "
            "doesitfire runs every agent inside a container and will not run without it."
        )
    return proc.stdout.strip()


def image_exists(image: str = IMAGE) -> bool:
    return _docker("image", "inspect", image, check=False).returncode == 0


def build_image(image: str = IMAGE, log: Callable[[str], None] = print) -> None:
    log(f"Building the agent image {image} (first run only, a few minutes)...")
    with ExitStack() as stack:
        ctx = stack.enter_context(resources.as_file(resources.files("doesitfire") / "docker"))
        proc = subprocess.run(["docker", "build", "-t", image, str(ctx)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise DoesItFireError(f"Building {image} failed:\n{proc.stderr.strip()[-1500:]}")


def stage_skills(skill_dirs: list[tuple[str, Path]], dest: Path) -> Path:
    """Copy each skill directory to dest/<name> (what gets mounted read-only at /skills)."""
    dest.mkdir(parents=True, exist_ok=True)
    for name, src in skill_dirs:
        shutil.copytree(
            src,
            dest / name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".venv"),
        )
    return dest


@dataclass
class RunOutput:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool
    stopped_early: bool
    duration_s: float


class Sandbox:
    """An internal Docker network plus an egress proxy, for one `doesitfire run`."""

    def __init__(self, allow_urls: list[str], image: str = IMAGE):
        self.run_id = uuid.uuid4().hex[:10]
        self.image = image
        self.network = f"doesitfire-{self.run_id}"
        self.proxy = f"doesitfire-{self.run_id}-egress"
        self.allow = sorted({host_port(u) for u in allow_urls})

    def __enter__(self) -> Sandbox:
        _docker("network", "create", "--internal", "--label", f"{LABEL}={self.run_id}", self.network)
        try:
            _docker(
                "run",
                "-d",
                "--name",
                self.proxy,
                "--label",
                f"{LABEL}={self.run_id}",
                "--network",
                "bridge",
                "--add-host",
                "host.docker.internal:host-gateway",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "128m",
                "--cpus",
                "0.5",
                "--pids-limit",
                "64",
                "-e",
                f"DOESITFIRE_ALLOW={','.join(self.allow)}",
                "--entrypoint",
                "node",
                self.image,
                "/opt/doesitfire/egress-proxy.mjs",
            )
            _docker("network", "connect", "--alias", "egress", self.network, self.proxy)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                logs = _docker("logs", self.proxy, check=False)
                if "egress proxy on" in logs.stderr + logs.stdout:
                    break
                time.sleep(0.3)
            else:
                raise DoesItFireError("The egress proxy container did not start.")
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        ids = _docker("ps", "-aq", "--filter", f"label={LABEL}={self.run_id}", check=False).stdout.split()
        if ids:
            _docker("rm", "-f", *ids, check=False)
        _docker("network", "rm", self.network, check=False)

    def proxy_denials(self) -> list[str]:
        logs = _docker("logs", self.proxy, check=False)
        return [ln for ln in (logs.stderr + logs.stdout).splitlines() if ln.startswith("deny ")]

    def run(
        self,
        inv: Invocation,
        skills_dir: str,
        staged: Path,
        timeout: int,
        cpus: float = 1.0,
        memory: str = "1g",
        on_line: Callable[[str], bool] | None = None,
    ) -> RunOutput:
        name = f"doesitfire-{self.run_id}-{uuid.uuid4().hex[:8]}"
        proxy = "http://egress:8888"
        args = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--label",
            f"{LABEL}={self.run_id}",
            "--network",
            self.network,
            "--read-only",
            "--tmpfs",
            "/home/node:rw,exec,uid=1000,gid=1000,size=512m",
            "--tmpfs",
            "/tmp:rw,exec,size=256m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--cpus",
            str(cpus),
            "--memory",
            memory,
            "--pids-limit",
            "512",
            "-v",
            f"{staged}:/skills:ro",
            "-e",
            f"DOESITFIRE_SKILLS_DIR={skills_dir}",
        ]
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            args += ["-e", f"{var}={proxy}"]
        args += ["-e", "NO_PROXY=", "-e", "no_proxy="]
        for key, value in inv.env.items():
            args += ["-e", f"{key}={value}"]
        child_env = dict(os.environ)
        for key, value in inv.secret_env.items():
            args += ["-e", key]  # value travels through the environment, never argv
            child_env[key] = value
        args += [self.image, "timeout", "-s", "KILL", str(timeout + 5), *inv.argv]

        start = time.monotonic()
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        )
        out_lines: list[str] = []
        err_chunks: list[str] = []
        stopped = threading.Event()

        def read_stderr() -> None:
            assert proc.stderr is not None
            err_chunks.append(proc.stderr.read())

        def kill() -> None:
            _docker("kill", name, check=False, timeout=30)

        t_err = threading.Thread(target=read_stderr, daemon=True)
        t_err.start()
        timer = threading.Timer(timeout, kill)
        timer.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                out_lines.append(line)
                if on_line and not stopped.is_set() and on_line(line):
                    stopped.set()
                    kill()
            proc.wait()
        except KeyboardInterrupt:
            kill()
            raise
        finally:
            timed_out = not timer.is_alive() and not stopped.is_set() and proc.returncode not in (0,)
            timer.cancel()
            t_err.join(timeout=5)
        duration = time.monotonic() - start
        return RunOutput(
            stdout="".join(out_lines),
            stderr="".join(err_chunks),
            returncode=proc.returncode,
            timed_out=timed_out and duration >= timeout,
            stopped_early=stopped.is_set(),
            duration_s=round(duration, 2),
        )
