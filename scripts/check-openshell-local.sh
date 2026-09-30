#!/bin/sh
set -eu

workspace="${OPENSHELL_WORKSPACE:-default}"
image="${OPENENV_OPENSHELL_SMOKE_IMAGE:-openenv-openshell-prerequisites:0.0.116}"
target_port="${OPENENV_OPENSHELL_SMOKE_PORT:-8000}"
expected_version="${OPENENV_OPENSHELL_VERSION:-0.1.2}"
run_smoke=false
sandbox_name=""

usage() {
    cat <<'EOF'
Usage: scripts/check-openshell-local.sh [--smoke]

Check the CLI, gateway, workspace, and local container runtime. With --smoke,
also create a disposable sandbox and verify an OpenShell-managed HTTP route.

Environment:
  OPENSHELL_WORKSPACE                Workspace to test (default: default)
  OPENENV_OPENSHELL_SMOKE_IMAGE      OCI image (default: local prerequisite image)
  OPENENV_OPENSHELL_SMOKE_PORT       Target port (default: 8000)
  OPENENV_OPENSHELL_VERSION          Required CLI version (default: 0.1.2)
EOF
}

case "${1:-}" in
    "") ;;
    --smoke) run_smoke=true ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "error: required command not found: $1" >&2
        return 1
    fi
}

cleanup() {
    if [ -n "$sandbox_name" ]; then
        echo "Cleaning up sandbox $sandbox_name"
        if ! openshell sandbox delete --workspace "$workspace" "$sandbox_name"; then
            echo "error: sandbox cleanup failed: $sandbox_name" >&2
            return 1
        fi
        # A successful delete request alone does not establish disappearance.
        cleanup_attempt=1
        while [ "$cleanup_attempt" -le 30 ]; do
            remaining="$(openshell sandbox list --workspace "$workspace" \
                --selector "openenv-smoke=$sandbox_name" --names)" || return 1
            if [ -z "$remaining" ]; then
                echo "Deletion verified: $sandbox_name is absent."
                sandbox_name=""
                return 0
            fi
            sleep 1
            cleanup_attempt=$((cleanup_attempt + 1))
        done
        echo "error: sandbox deletion not confirmed: $sandbox_name" >&2
        return 1
    fi
}

require_command openshell
require_command curl

cli_version="$(openshell --version)"
echo "OpenShell CLI: $cli_version"
case "$cli_version" in
    "openshell $expected_version") ;;
    *)
        echo "error: expected OpenShell CLI version $expected_version" >&2
        echo "       override OPENENV_OPENSHELL_VERSION only for compatibility testing" >&2
        exit 1
        ;;
esac
echo "Checking active gateway"
gateway_status="$(openshell status --output json)"
printf '%s\n' "$gateway_status"
gateway_version="$(printf '%s\n' "$gateway_status" \
    | sed -n 's/^[[:space:]]*"version": "\([^"]*\)".*$/\1/p')"
if [ "$gateway_version" != "$expected_version" ]; then
    echo "error: expected gateway version $expected_version, got $gateway_version" >&2
    exit 1
fi

echo "Checking workspace access: $workspace"
openshell sandbox list --workspace "$workspace" --output json >/dev/null

runtime_found=false
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "Docker runtime: reachable ($(docker version --format '{{.Server.Version}}'))"
    runtime_found=true
fi
if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
    echo "Podman runtime: reachable ($(podman version --format '{{.Server.Version}}'))"
    runtime_found=true
fi
if [ "$runtime_found" = false ]; then
    echo "warning: no reachable local Docker or Podman runtime detected" >&2
    echo "         a remote gateway or VM/Kubernetes driver may still work" >&2
fi

if [ "$run_smoke" = false ]; then
    echo "Prerequisites passed; use --smoke to verify compute and service routing."
    exit 0
fi

trap cleanup EXIT
trap 'exit 130' HUP INT TERM
sandbox_name="oe-smoke-$$"

echo "Creating smoke-test sandbox: $sandbox_name"
openshell sandbox create \
    --workspace "$workspace" \
    --name "$sandbox_name" \
    --label "openenv-smoke=$sandbox_name" \
    --from "$image" \
    --detach \
    -- python3 -m http.server "$target_port" --bind 127.0.0.1 \
    >/dev/null

echo "Exposing sandbox service on target port $target_port"
openshell service expose \
    --workspace "$workspace" \
    "$sandbox_name" \
    "$target_port" \
    openenv-smoke \
    >/dev/null
service_details="$(
    openshell service get --workspace "$workspace" "$sandbox_name" openenv-smoke
)"
service_url="$(
    printf '%s\n' "$service_details" \
        | grep -Eo 'https?://[[:alnum:].:/?&=_~-]+' \
        | head -n 1
)"
if [ -z "$service_url" ]; then
    echo "error: OpenShell service output did not contain a routed URL" >&2
    printf '%s\n' "$service_details" >&2
    exit 1
fi
echo "Service route: $service_url"

attempt=1
while [ "$attempt" -le 30 ]; do
    if curl --fail --silent --show-error --max-time 2 "$service_url" >/dev/null; then
        cleanup
        echo "Smoke test passed: compute, HTTP routing, and deletion verified."
        exit 0
    fi
    sleep 1
    attempt=$((attempt + 1))
done

echo "error: routed service failed after 30 bounded HTTP attempts: $service_url" >&2
exit 1
