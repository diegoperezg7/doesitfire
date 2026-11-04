# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.2] - 2026-11-04

### Added
- Claude Code plugin (`/plugin install doesitfire --marketplace diegoperezg7/doesitfire`) with the `test-skill-activation` skill.

## [0.1.1] - 2026-11-04

### Changed
- HTML report: numbers, percentages and money are formatted with `Intl.NumberFormat` for the active language
  (EN `$0.05`, ES `0,05 US$`).
- The report lists the price used for each paid agent, with its source and the date it was checked.
- `results.json` records the configured price per agent.

### Fixed
- Recorded demo cost. v0.1.0 used an unverified price of 0.10 USD per million tokens for Mistral
  `ministral-8b-latest`. The verified price is 0.15 USD per million input and output tokens
  (`ministral-8b-latest` is `ministral-8b-2512`; [docs.mistral.ai](https://docs.mistral.ai/models/ministral-3-8b-25-12),
  checked 2026-11-04). Recomputed from the recorded token usage without re-running: 361,490 tokens, **0.054 USD**
  (v0.1.0 said 0.036 USD). The activation results do not change.
- `examples/doesitfire.mistral.yaml` uses the verified price.

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

[0.1.2]: https://github.com/diegoperezg7/doesitfire/releases/tag/v0.1.2
[0.1.1]: https://github.com/diegoperezg7/doesitfire/releases/tag/v0.1.1
[0.1.0]: https://github.com/diegoperezg7/doesitfire/releases/tag/v0.1.0
