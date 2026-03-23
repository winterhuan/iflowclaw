#!/bin/bash
# Build the iFlowClaw agent container image

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

IMAGE_NAME="iflowclaw-agent"
TAG="${1:-latest}"
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-docker}"

# Prepare build context
BUILD_DIR=$(mktemp -d)
trap 'rm -rf "$BUILD_DIR"' EXIT

# Copy agent runner
mkdir -p "$BUILD_DIR/agent-runner/src"
cp agent-runner/src/*.py "$BUILD_DIR/agent-runner/src/"

# Copy iflowclaw package for container
mkdir -p "$BUILD_DIR/iflowclaw-package"
SCRIPT_DIR_ABS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR_ABS")"
cp "$PROJECT_ROOT/pyproject.toml" "$BUILD_DIR/iflowclaw-package/"
cp -r "$PROJECT_ROOT/src/iflowclaw" "$BUILD_DIR/iflowclaw-package/src/" 2>/dev/null || mkdir -p "$BUILD_DIR/iflowclaw-package/src/iflowclaw"
if [ -d "$PROJECT_ROOT/src" ]; then
    cp -r "$PROJECT_ROOT/src" "$BUILD_DIR/iflowclaw-package/"
fi

echo "Building iFlowClaw agent container image..."
echo "Image: ${IMAGE_NAME}:${TAG}"

${CONTAINER_RUNTIME} build -t "${IMAGE_NAME}:${TAG}" -f Dockerfile "$BUILD_DIR"

echo ""
echo "Build complete!"
echo "Image: ${IMAGE_NAME}:${TAG}"
echo ""
echo "Test with:"
echo "  echo '{\"prompt\":\"What is 2+2?\",\"groupFolder\":\"test\",\"chatJid\":\"test@g.us\",\"isMain\":false}' | ${CONTAINER_RUNTIME} run -i ${IMAGE_NAME}:${TAG}"
