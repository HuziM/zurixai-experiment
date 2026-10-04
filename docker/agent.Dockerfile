# One fresh container per run. The agent works in an empty /work as a non-root user.
FROM python:3.12-bookworm@sha256:e91fec3d1ac69f04e4eddcd29c327e630ce34658cf31075bfa7e8b0e052bafea

COPY --from=node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

ARG CLAUDE_CODE_VERSION=2.1.289
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force

RUN useradd --create-home --shell /bin/bash agent \
 && mkdir /work /out && chown agent:agent /work /out
USER agent
# npm -g and pip work without root, as they would on a developer's machine.
ENV NPM_CONFIG_PREFIX=/home/agent/.npm-global \
    PATH=/home/agent/.npm-global/bin:/home/agent/.local/bin:$PATH \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /work

COPY --chown=agent:agent agent_entry.sh /usr/local/bin/agent_entry.sh
ENTRYPOINT ["bash", "/usr/local/bin/agent_entry.sh"]
