#!/bin/bash
set -e

# Log startup info
echo "[entrypoint] iFlow Agent Container starting..."
echo "[entrypoint] Node: $(node --version)"
echo "[entrypoint] Working directory: $(pwd)"

# Check if iFlow settings exist (mounted from host)
if [ -f /home/node/.iflow/settings.json ]; then
    echo "[entrypoint] Found iFlow settings"
else
    echo "[entrypoint] WARNING: No iFlow settings found, authentication may fail"
fi

# Debug: check if agent-wrapper exists
if [ -f /app/dist/container/agent-wrapper.js ]; then
    echo "[entrypoint] Found agent-wrapper at /app/dist/container/agent-wrapper.js"
else
    echo "[entrypoint] ERROR: agent-wrapper NOT FOUND at /app/dist/container/agent-wrapper.js"
    echo "[entrypoint] Contents of /app/dist/container:"
    ls -la /app/dist/container 2>/dev/null || echo "Directory /app/dist/container does not exist"
    echo "[entrypoint] Contents of /app/dist:"
    ls -la /app/dist
fi

# Run agent wrapper
echo "[entrypoint] Executing agent-wrapper..."
exec node /app/dist/container/agent-wrapper.js
