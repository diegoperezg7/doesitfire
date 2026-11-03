# Contributing

Thanks for helping. Bug reports with a `results.json` attached are the most useful thing you can send.

## Setup

```bash
git clone https://github.com/diegoperezg7/doesitfire && cd doesitfire
uv sync
uv run pytest            # unit tests, no Docker needed
uv run pytest -m docker  # real agent CLIs in Docker against a scripted mock model
uv run ruff check .
```

The Docker tests build the agent image (about 1.9 GB) on first run. They never call a real model:
`tests/mockmodel.py` speaks just enough of the Anthropic Messages, OpenAI Responses and Chat
Completions APIs to drive each CLI.

## Adding or updating an agent

Agent CLIs change their JSON event formats often, so their versions are pinned in
`src/doesitfire/docker/Dockerfile` and `CLI_VERSIONS` in `src/doesitfire/agents.py`. When you bump one:

1. Rebuild the image (`doesitfire run --rebuild`).
2. Re-record the event fixtures in `tests/fixtures/events/` against the mock model.
3. Run both test suites.

## Pull requests

- One change per pull request, with a test when behaviour changes.
- Keep dependencies pinned with `==` and run `uv lock`.
- No telemetry, ever.
