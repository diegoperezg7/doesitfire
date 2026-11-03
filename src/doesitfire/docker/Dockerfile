# Agent sandbox image for doesitfire. CLI versions are pinned on purpose:
# their JSON event formats change between releases.
FROM node:22.21.1-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.317
ARG CODEX_VERSION=0.166.0
ARG OPENCODE_VERSION=1.19.5

RUN npm install -g --no-audit --no-fund \
      @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
      @openai/codex@${CODEX_VERSION} \
      opencode-ai@${OPENCODE_VERSION} \
    && npm cache clean --force \
    && apt-get update && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY egress-proxy.mjs /opt/doesitfire/egress-proxy.mjs
COPY entrypoint.sh /opt/doesitfire/entrypoint.sh
RUN chmod 0755 /opt/doesitfire/entrypoint.sh

RUN mkdir -p /home/node/work && chown -R node:node /home/node
USER node
WORKDIR /home/node
ENTRYPOINT ["/opt/doesitfire/entrypoint.sh"]
