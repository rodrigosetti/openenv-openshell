#!/bin/sh
# S5b: disposable OIDC gateway; run only on an IP-restricted test VM.
# Keycloak is loopback-only. The fixed secret is a public test fixture.
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
mkdir -p "$DATA/keycloak"
cat > "$DATA/keycloak/realm.json" <<'JSON'
{
  "realm": "openshell", "enabled": true, "accessTokenLifespan": 3600,
  "roles": {"realm": [{"name": "openshell-admin"}]},
  "clients": [{
    "clientId": "openshell-cli", "secret": "disposable-s5b-test-secret",
    "serviceAccountsEnabled": true, "publicClient": false,
    "protocol": "openid-connect",
    "protocolMappers": [{
      "name": "gateway-audience", "protocol": "openid-connect",
      "protocolMapper": "oidc-audience-mapper",
      "config": {"included.client.audience": "openshell-cli", "access.token.claim": "true"}
    }]
  }],
  "users": [{
    "username": "service-account-openshell-cli", "enabled": true,
    "serviceAccountClientId": "openshell-cli", "realmRoles": ["openshell-admin"]
  }]
}
JSON
docker rm -f s5b-keycloak >/dev/null 2>&1 || true
docker run -d --name s5b-keycloak --restart unless-stopped \
  -p 127.0.0.1:8180:8080 \
  -v "$DATA/keycloak:/opt/keycloak/data/import:ro" \
  quay.io/keycloak/keycloak:26.0.8 start-dev --import-realm \
  --hostname=http://127.0.0.1:8180
attempt=0
until curl -fsS http://127.0.0.1:8180/realms/openshell/.well-known/openid-configuration >/dev/null; do
  attempt=$((attempt + 1))
  [ "$attempt" -lt 90 ] || exit 1
  sleep 2
done
umask 077
curl -fsS http://127.0.0.1:8180/realms/openshell/protocol/openid-connect/token \
  -d grant_type=client_credentials -d client_id=openshell-cli \
  -d client_secret=disposable-s5b-test-secret > "$DATA/s5b-token.json"
cat > "$DATA/gateway.toml" <<EOF
[openshell]
version = 2

[openshell.gateway]
name                = "openenv-s5b"
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
gateway_id       = "openenv-s5b"

[openshell.gateway.mtls_auth]
enabled = false

[openshell.gateway.oidc]
issuer = "http://127.0.0.1:8180/realms/openshell"
audience = "openshell-cli"
dangerously_allow_insecure_http = true

[openshell.drivers.docker]
image_pull_policy     = "if_not_present"
sandbox_label         = "openenv-s5b"
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
