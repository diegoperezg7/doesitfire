# Security policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub security advisories](https://github.com/diegoperezg7/doesitfire/security/advisories/new),
not in public issues. You should get an answer within a week.

## What doesitfire does to contain agents

doesitfire runs third-party agent CLIs that a language model drives, so it treats them as untrusted:

- Every run happens in a fresh Docker container: non-root user, read-only root filesystem, tmpfs
  home, all Linux capabilities dropped, `no-new-privileges`, CPU, memory, pids and time limits.
- Containers sit on an internal Docker network with no route out. The only peer is an egress proxy
  that forwards to the model API host and port and answers 403 to everything else.
- Side-effect tools are denied: Bash, Write, Edit and web tools in Claude Code; edit, bash and
  webfetch in OpenCode. Turns are capped (default 2).
- Codex has no read-only file tool and its own sandbox cannot start in an unprivileged container,
  so its shell runs unsandboxed inside the container. The container limits above still apply.
- API keys come from environment variables only. They reach the container by variable name, never
  on a command line, and are never written to disk or to the results.
- The tool itself sends no telemetry. Codex analytics are switched off; other outbound calls the
  agents attempt are blocked by the proxy and listed in the report.

Skills you test are copied into the container. Do not test skills you do not trust with your API key.
