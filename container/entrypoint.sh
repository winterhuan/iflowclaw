#!/bin/bash
# Entrypoint for iFlowClaw agent container
# Reads secrets from stdin JSON and stores them temporarily

# Read stdin to temp file (contains secrets)
cat > /tmp/input.json

# Start iFlow in background if not already running
if ! pgrep -x "iflow" > /dev/null; then
    iflow --experimental-acp --port 8090 &
    sleep 2
fi

# Execute the agent runner
exec "$@"
