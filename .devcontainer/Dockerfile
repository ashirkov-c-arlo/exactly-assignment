FROM mcr.microsoft.com/devcontainers/python:3.12

ARG CLAUDE_CODE_VERSION=latest

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /uvx /usr/local/bin/

RUN curl -fsSL https://deb.nodesource.com/setup_24.x -o /tmp/nodesource-setup.sh \
    && bash /tmp/nodesource-setup.sh \
    && rm /tmp/nodesource-setup.sh \
    && apt-get install -y --no-install-recommends \
    libopus0 \
    nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && chmod 1777 /tmp

# Ensure vscode user has access to npm global dir
RUN mkdir -p /usr/local/share/npm-global && \
    chown -R vscode:vscode /usr/local/share/npm-global
RUN OBSCURA_VERSION=v0.1.7 && \
    curl -fsSL "https://github.com/h4ckf0r0day/obscura/releases/download/${OBSCURA_VERSION}/obscura-x86_64-linux.tar.gz" \
    | tar -xz -C /usr/local/bin

USER vscode

# Install coding agents globally via npm
ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV PATH=$PATH:/usr/local/share/npm-global/bin
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} @openai/codex && \
    npm install -g --ignore-scripts @earendil-works/pi-coding-agent

USER vscode
