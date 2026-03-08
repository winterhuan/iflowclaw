#!/bin/bash
# Build the iFlowClaw agent container image

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="${IFLOWCLAW_IMAGE:-iflowclaw-agent}"
IMAGE_TAG="${IFLOWCLAW_TAG:-latest}"

echo "Building $IMAGE_NAME:$IMAGE_TAG..."

# Build the image
docker build \
    -t "$IMAGE_NAME:$IMAGE_TAG" \
    -f "$SCRIPT_DIR/Dockerfile" \
    "$SCRIPT_DIR"

echo "Build complete: $IMAGE_NAME:$IMAGE_TAG"
