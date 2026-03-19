#!/bin/bash
# Build iFlow agent container image
#
# Usage:
#   ./container/build.sh [tag] [options]
#
# Examples:
#   ./container/build.sh                    # Build with tag 'latest'
#   ./container/build.sh v1.0.0             # Build with specific tag
#   ./container/build.sh --no-build         # Skip npm build step
#   ./container/build.sh --push             # Build and push to registry
#
# Environment Variables:
#   CONTAINER_RUNTIME  - Docker or Podman (default: docker)
#   IMAGE_NAME         - Image name (default: iflow-agent)
#   REGISTRY           - Docker registry (optional)

set -e

# ---- Configuration ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

IMAGE_NAME="${IMAGE_NAME:-iflow-agent}"
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-docker}"

# ---- Parse Arguments ----
TAG="latest"
SKIP_BUILD=false
PUSH=false
NO_CACHE=false

for arg in "$@"; do
    case $arg in
        --no-build)
            SKIP_BUILD=true
            shift
            ;;
        --push)
            PUSH=true
            shift
            ;;
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [tag] [options]"
            echo ""
            echo "Options:"
            echo "  --no-build    Skip npm run build step"
            echo "  --push        Push image to registry after build"
            echo "  --no-cache    Build without cache"
            echo "  --help, -h    Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  CONTAINER_RUNTIME  Container runtime (docker/podman)"
            echo "  IMAGE_NAME         Image name (default: iflow-agent)"
            echo "  REGISTRY           Docker registry URL"
            exit 0
            ;;
        *)
            # Assume it's the tag if not a known option
            if [[ ! "$arg" =~ ^-- ]]; then
                TAG="$arg"
            fi
            ;;
    esac
done

# ---- Functions ----
log_info() {
    echo -e "\033[0;34m[INFO]\033[0m $1"
}

log_success() {
    echo -e "\033[0;32m[SUCCESS]\033[0m $1"
}

log_error() {
    echo -e "\033[0;31m[ERROR]\033[0m $1"
}

check_prerequisites() {
    # Check container runtime
    if ! command -v "$CONTAINER_RUNTIME" &> /dev/null; then
        log_error "Container runtime '$CONTAINER_RUNTIME' not found"
        log_info "Install Docker or Podman, or set CONTAINER_RUNTIME environment variable"
        exit 1
    fi

    # Check Node.js
    if ! command -v node &> /dev/null; then
        log_error "Node.js not found"
        exit 1
    fi

    # Check npm
    if ! command -v npm &> /dev/null; then
        log_error "npm not found"
        exit 1
    fi

    log_info "Prerequisites checked: $CONTAINER_RUNTIME, node $(node --version), npm $(npm --version)"
}

build_project() {
    if [ "$SKIP_BUILD" = true ]; then
        log_info "Skipping npm build (--no-build)"
        return
    fi

    log_info "Building TypeScript project..."
    npm run build

    if [ ! -d "dist" ]; then
        log_error "Build failed: dist/ directory not created"
        exit 1
    fi

    log_success "TypeScript build complete"
}

build_image() {
    local full_image_name="${IMAGE_NAME}:${TAG}"

    # Add registry prefix if specified
    if [ -n "$REGISTRY" ]; then
        full_image_name="${REGISTRY}/${full_image_name}"
    fi

    log_info "Building container image: ${full_image_name}"

    local build_args=(
        -t "${full_image_name}"
        -f container/Dockerfile
    )

    if [ "$NO_CACHE" = true ]; then
        build_args+=(--no-cache)
    fi

    # Build with context
    ${CONTAINER_RUNTIME} build "${build_args[@]}" .

    if [ $? -eq 0 ]; then
        log_success "Image built: ${full_image_name}"
    else
        log_error "Failed to build image"
        exit 1
    fi

    # Show image size
    local image_size
    image_size=$(${CONTAINER_RUNTIME} images "${full_image_name}" --format "{{.Size}}")
    log_info "Image size: ${image_size}"
}

push_image() {
    if [ "$PUSH" = true ]; then
        local full_image_name="${IMAGE_NAME}:${TAG}"
        if [ -n "$REGISTRY" ]; then
            full_image_name="${REGISTRY}/${full_image_name}"
        fi

        log_info "Pushing image: ${full_image_name}"
        ${CONTAINER_RUNTIME} push "${full_image_name}"

        if [ $? -eq 0 ]; then
            log_success "Image pushed: ${full_image_name}"
        else
            log_error "Failed to push image"
            exit 1
        fi
    fi
}

show_test_instructions() {
    local full_image_name="${IMAGE_NAME}:${TAG}"
    if [ -n "$REGISTRY" ]; then
        full_image_name="${REGISTRY}/${full_image_name}"
    fi

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Build Complete!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  Image: ${full_image_name}"
    echo ""
    echo "  Test with:"
    echo "    ${CONTAINER_RUNTIME} run -it --rm \\"
    echo "      -v \$(pwd)/groups/main:/workspace/group:rw \\"
    echo "      -v ~/.iflow:/home/node/.iflow-shared:ro \\"
    echo "      ${full_image_name}"
    echo ""
    echo "  Or with echo mode (no iFlow CLI required):"
    echo "    echo '{\"prompt\":\"hello\",\"groupFolder\":\"test\",\"chatJid\":\"test\",\"isMain\":false}' | \\"
    echo "      ${CONTAINER_RUNTIME} run -i --rm ${full_image_name}"
    echo ""
}

# ---- Main ----
main() {
    log_info "iFlow Agent Container Build"
    log_info "============================"
    log_info "Project root: ${PROJECT_ROOT}"
    log_info "Image: ${IMAGE_NAME}:${TAG}"
    log_info "Runtime: ${CONTAINER_RUNTIME}"
    echo ""

    check_prerequisites
    build_project
    build_image
    push_image
    show_test_instructions
}

main