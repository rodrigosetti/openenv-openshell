#!/bin/sh
# S5a: OpenShell 0.1.2 gateway (Docker driver, mTLS) on a disposable GCE VM.
set -eu
DOMAIN="$1"
VERSION=0.1.2
DATA=/var/lib/openshell
until docker info >/dev/null 2>&1; do sleep 3; done
mkdir -p "$DATA"
if [ ! -f "$DATA/tls/ca.crt" ]; then
  docker run --rm -v "$DATA:$DATA" -e HOME="$DATA" -e XDG_CONFIG_HOME="$DATA/config" \
    --user 0 ghcr.io/nvidia/openshell/gateway:$VERSION generate-certs \
    --output-dir "$DATA/tls" \
    --server-san "$DOMAIN" --server-san "*.$DOMAIN" \
    --server-san 127.0.0.1 --server-san localhost
fi
cat > "$DATA/gateway.toml" <<EOF
[openshell]
version = 2

[openshell.gateway]
name                = "openenv-s5a"
bind_address        = "0.0.0.0:8080"
health_bind_address = "127.0.0.1:8081"
log_level           = "info"
compute_driver      = "docker"
server_sans         = ["$DOMAIN", "*.$DOMAIN", "127.0.0.1", "localhost"]
disable_tls         = false
guest_tls_ca        = "$DATA/tls/ca.crt"
guest_tls_cert      = "$DATA/tls/client/tls.crt"
guest_tls_key       = "$DATA/tls/client/tls.key"

[openshell.gateway.tls]
cert_path      = "$DATA/tls/server/tls.crt"
key_path       = "$DATA/tls/server/tls.key"
client_ca_path = "$DATA/tls/ca.crt"

[openshell.gateway.gateway_jwt]
signing_key_path = "$DATA/tls/jwt/signing.pem"
public_key_path  = "$DATA/tls/jwt/public.pem"
kid_path         = "$DATA/tls/jwt/kid"
gateway_id       = "openenv-s5a"

[openshell.gateway.mtls_auth]
enabled = true

[openshell.drivers.docker]
image_pull_policy     = "if_not_present"
sandbox_label         = "openenv-s5a"
grpc_endpoint         = "https://127.0.0.1:8080"
sandbox_runtime_image = "ghcr.io/nvidia/openshell/sandbox:$VERSION"
supervisor_image      = "ghcr.io/nvidia/openshell/supervisor:$VERSION"
app_armor_profile     = "Unconfined"
EOF
docker rm -f openshell-gateway >/dev/null 2>&1 || true
docker run -d --name openshell-gateway --restart unless-stopped --user 0 \
  --network host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$DATA:$DATA" \
  -e OPENSHELL_GATEWAY_CONFIG="$DATA/gateway.toml" \
  -e OPENSHELL_DB_URL="sqlite:$DATA/gateway.db?mode=rwc" \
  -e XDG_DATA_HOME="$DATA" -e HOME="$DATA" \
  ghcr.io/nvidia/openshell/gateway:$VERSION
sleep 5
docker ps --filter name=openshell-gateway --format '{{.Status}}'
docker logs --tail 20 openshell-gateway 2>&1
