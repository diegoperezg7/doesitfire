---
name: test-skill-activation
description: Measure whether agent skills (SKILL.md) actually activate in Claude Code, Codex and OpenCode with doesitfire, then improve the descriptions of skills that do not fire or fire when they should not. Use when the user asks if a skill triggers, why a skill is ignored, to test or benchmark skill activation, or to tune a skill's description.
---

# Test skill activation with doesitfire

doesitfire runs each coding agent in a Docker sandbox on prompts that should and should not trigger
each skill, and reports recall (fires when it should) and false-fire rate per agent and skill.

## Before anything runs

1. Check the tools: `uv --version` and `docker info` must work. If Docker is not running, say so and stop.
2. Use this command prefix everywhere (until doesitfire is on PyPI):
   `uvx --from git+https://github.com/diegoperezg7/doesitfire@v0.1.1 doesitfire`
3. To show the user what a result looks like first, with no keys, no Docker and no cost, run `... doesitfire demo`.

## Steps

1. **Find the skills.** Run `... doesitfire init <dir>` on the directory that holds the skills (for
   example `.claude/skills`). It writes `doesitfire.yaml` with one entry per `SKILL.md`.
2. **Write the prompts.** For each skill, read its `SKILL.md` and fill `should_fire` with 3 to 6
   realistic requests a user would type, phrased the way people talk and not copying the description
   wording, and `should_not_fire` with 3 to 6 near misses: requests on a related topic that the skill
   should not handle. Show the prompts to the user before running.
3. **Choose agents and models.** Ask which agents to test and with which provider. Claude Code needs
   `ANTHROPIC_API_KEY`, or `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` to use a Claude
   subscription. Ollama is free but slow on a laptop. Never print or write key values.
4. **Agree on the budget.** Runs = agents x skills x prompts x `repeats`. Tell the user that number and
   pass `--max-cost` (default 1 USD). Do not start a paid run without the user's explicit OK.
5. **Run.** `... doesitfire run --max-cost <usd>`. Results go to `doesitfire-results/`
   (`results.json`, `report.html`, JUnit and a badge).
6. **Read the results.** Report per agent and skill: recall, false-fire rate, and the prompts that
   missed. Quote numbers from `results.json`; do not estimate them.
7. **Fix descriptions.** For skills with low recall, rewrite the `description` in the frontmatter so it
   says when to use the skill, with the words users actually use; for false fires, add when not to use
   it. Change only the description unless the user asks for more, then re-run only those skills with
   `--skills <name>` to confirm the change helped. Report before and after.

## Notes

- Activation is not deterministic: with `repeats: 1` a single run decides the cell. Prefer 3 when the
  budget allows and say how many runs each number rests on.
- For CI, `--min-recall 0.75 --max-false-fire 0.25` makes the run exit 1 when a cell misses, and the
  repository ships a GitHub Action (`uses: diegoperezg7/doesitfire@v0.1.1`).
