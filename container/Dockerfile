# iFlowClaw Agent Container
# Based on Node.js with iFlow CLI pre-installed

FROM node:22-bookworm-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install iFlow CLI globally
RUN npm install -g @iflow-ai/iflow-cli

# Create app directory
WORKDIR /app

# Copy agent-runner package
COPY agent-runner/package*.json ./
RUN npm ci --omit=dev

# Copy agent-runner source and build
COPY agent-runner/tsconfig.json ./
COPY agent-runner/src ./src
RUN npm run build

# Create workspace directories
RUN mkdir -p /workspace/group /workspace/global /workspace/ipc/input /workspace/ipc/output

# Create iFlow config directory (will be mounted from host for OAuth)
RUN mkdir -p /home/node/.iflow

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set up environment
ENV NODE_ENV=production
ENV IFLOW_EXPERIMENTAL_ACP=1

# Entrypoint handles secrets injection from stdin
ENTRYPOINT ["/entrypoint.sh"]
CMD ["node", "dist/index.js"]
