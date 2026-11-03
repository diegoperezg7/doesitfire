#!/bin/sh
# Copies the skills mounted read-only at /skills into the discovery directory
# of the agent under test (DOESITFIRE_SKILLS_DIR, relative to a fresh
# workspace), writes optional agent config, then runs the agent command.
set -eu
WORK=/home/node/work
mkdir -p "$WORK"
cd "$WORK"
git init -q . >/dev/null 2>&1 || true
if [ -d /skills ] && [ -n "${DOESITFIRE_SKILLS_DIR:-}" ]; then
  mkdir -p "$WORK/$DOESITFIRE_SKILLS_DIR"
  cp -R /skills/. "$WORK/$DOESITFIRE_SKILLS_DIR/"
fi
exec "$@"
