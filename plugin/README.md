# doesitfire for Claude Code

This plugin adds one skill, `test-skill-activation`, that walks Claude through measuring whether your
agent skills (`SKILL.md`) actually activate in Claude Code, Codex and OpenCode, and through fixing the
descriptions of the ones that do not.

Ask in plain words, for example "does my commit-message skill ever fire?". Claude then finds your
skills, writes prompts that should and should not trigger each one, shows them to you, agrees the
agents, models and budget with you, runs the open-source
[doesitfire](https://github.com/diegoperezg7/doesitfire) CLI and reports recall and false-fire rate
per agent and skill. For skills that miss, it proposes a new description and measures again.

## What it runs and sends

- It runs `uvx --from git+https://github.com/diegoperezg7/doesitfire@v0.1.1 doesitfire`, pinned to a
  release tag. The CLI runs each agent inside a Docker container with CPU, memory and time limits.
- The prompts and your skills go only to the model provider you choose for each agent (Anthropic,
  OpenAI, OpenRouter, Mistral or a local Ollama). Keys are read from environment variables and are never
  written to files.
- The skill tells Claude to ask before any paid run, and `--max-cost` (1 USD by default) stops the run
  before it spends more. Nothing is sent anywhere else: no telemetry.

License: MIT.
