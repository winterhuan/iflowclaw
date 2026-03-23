# iFlowClaw Agent Container
# Runs Claude Agent SDK in isolated Linux VM with browser automation

FROM python:3.11-slim

# Install system dependencies for Chromium and git
RUN apt-get update && apt-get install -y \
    chromium \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    libgbm1 \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libasound2 \
    libpangocairo-1.0-0 \
    libcups2 \
    libdrm2 \
    libxshmfence1 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set Chromium path
ENV AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium

# Install Python dependencies
RUN pip install --no-cache-dir \
    croniter \
    httpx \
    mcp \
    pydantic \
    claude-agent-sdk \
    anthropic

# Create app directory
WORKDIR /app

# Copy and install the iflowclaw package
COPY iflowclaw-package/ ./iflowclaw-package/
RUN pip install --no-cache-dir ./iflowclaw-package/

# Create workspace directories
RUN mkdir -p /workspace/group /workspace/global /workspace/extra \
             /workspace/ipc/messages /workspace/ipc/tasks /workspace/ipc/input

# Create entrypoint script
# Container input (prompt, group info) is passed via stdin JSON.
# Credentials are injected by the host's credential proxy -- never passed here.
# Follow-up messages arrive via IPC files in /workspace/ipc/input/
RUN printf '#!/bin/bash\nset -e\npython -m iflowclaw.agents.container_entry\n' > /app/entrypoint.sh \
    && chmod +x /app/entrypoint.sh

# Set ownership for writable directories
RUN useradd -m -s /bin/bash node 2>/dev/null || true \
    && chown -R node:node /workspace /home/node

# Switch to non-root user
USER node

# Set working directory to group workspace
WORKDIR /workspace/group

# Entry point reads JSON from stdin, outputs JSON to stdout
ENTRYPOINT ["/app/entrypoint.sh"]
