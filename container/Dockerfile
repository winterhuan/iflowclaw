# iFlow Agent Container
# Runs iFlow SDK in isolated Linux container with browser automation support
#
# Build: ./container/build.sh [tag]
# Test:  docker run -it --rm \
#          -v $(pwd)/groups/main:/workspace/group:rw \
#          -v ~/.iflow:/home/node/.iflow:ro \
#          iflow-agent:latest

# ---- Stage 1: Build TypeScript ----
FROM node:20-slim AS builder

WORKDIR /build

# Copy package files and install all dependencies (including devDependencies for build)
COPY package*.json ./
RUN npm ci

# Copy TypeScript config and source
COPY tsconfig.json ./
COPY src/ ./src/

# Build TypeScript
RUN npm run build

# ---- Stage 2: Runtime Image ----
FROM node:20-slim

# Install system dependencies for Chromium (for agent-browser skill)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
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
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set Chromium path for agent-browser skill
ENV AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

# Install iFlow CLI (required for iFlow SDK)
RUN npm install -g @iflow-ai/iflow-cli

# Create app directory
WORKDIR /app

# Copy package files and install production dependencies
COPY package*.json ./
RUN npm ci --only=production

# Copy compiled code from builder
COPY --from=builder /build/dist/ ./dist/

# Create workspace directories
RUN mkdir -p /workspace/group \
             /workspace/global \
             /workspace/extra \
             /workspace/ipc/messages \
             /workspace/ipc/tasks \
             /workspace/ipc/input

# Copy entrypoint script
COPY container/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Set ownership to node user (non-root) for writable directories
RUN chown -R node:node /workspace \
    && chown -R node:node /app \
    && chown -R node:node /home/node

# Switch to non-root user
USER node

# Set working directory to group workspace
WORKDIR /workspace/group

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD node -e "console.log('healthy')" || exit 1

# Use the entrypoint script (MUST be last)
ENTRYPOINT ["/app/entrypoint.sh"]
