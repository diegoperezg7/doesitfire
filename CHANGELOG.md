# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-03

### Added
- `doesitfire run`: runs Claude Code 2.1.317, Codex 0.166.0 and OpenCode 1.19.5 headless in Docker,
  N repeats per prompt (default 3), and reports activation per agent and skill: recall, false-fire
  rate and precision.
- Activation detection: Claude Code `Skill` tool call, OpenCode `skill` tool call, Codex reading the
  skill's `SKILL.md` (experimental: Codex has no activation event).
- Sandbox: internal Docker network with an egress proxy that only lets the model API through,
  side-effect tools denied, turn cap, CPU, memory, pids and time limits, read-only root filesystem.
- Providers: Ollama (free, local), Anthropic, OpenAI, OpenRouter and Mistral, keys from env vars only.
- `--max-cost` budget guard (default 1 USD), checked before every run.
- Outputs: terminal matrix, `results.json`, JUnit XML, static HTML report (EN/ES, light/dark),
  badge SVG and shields.io endpoint JSON.
- `doesitfire init` scaffolds `doesitfire.yaml` from the skills found in a repo.
- `doesitfire demo` shows a recorded real run of three example skills.
- Composite GitHub Action and an example workflow.

[0.1.0]: https://github.com/diegoperezg7/doesitfire/releases/tag/v0.1.0
