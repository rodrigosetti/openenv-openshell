# Remote OpenShell gateway testing (S5a/S5b)

This page reproduces the disposable remote gateway used for
[S5a remote validation](protocol-spike.md#remote-gateway-validation-s5a-2026-09-30).
It is a test fixture, not a production deployment guide. Use a cloud project
you are authorized to bill, and delete everything afterwards.

## 1. Provision a VM

The S5a run used GCE, with the firewall limited to the tester's public address:

```bash
MY_IP="$(curl -s https://api.ipify.org)"
gcloud compute firewall-rules create openenv-s5a-gateway --network=default \
  --direction=INGRESS --allow=tcp:8080 --source-ranges="$MY_IP/32" \
  --target-tags=openenv-s5a
gcloud compute instances create openenv-s5a-gateway --zone=us-east1-b \
  --machine-type=e2-standard-2 --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud --boot-disk-size=30GB --tags=openenv-s5a \
  --metadata=startup-script='#!/bin/sh
apt-get update && apt-get install -y docker.io && systemctl enable --now docker'
```

## 2. Start the gateway

[`remote-gateway-bootstrap.sh`](examples/remote-gateway-bootstrap.sh) runs the
pinned 0.1.2 gateway container with the Docker driver on the host network. It
generates an mTLS PKI whose server certificate covers the routing domain and
its wildcard. It uses [sslip.io](https://sslip.io), so `*.A-B-C-D.sslip.io`
resolves to `A.B.C.D` without owning a domain:

```bash
IP="$(gcloud compute instances describe openenv-s5a-gateway --zone=us-east1-b \
  --format='value(networkInterfaces[0].accessConfigs[0].natIP)')"
DOMAIN="$(echo "$IP" | tr . -).sslip.io"
gcloud compute scp docs/examples/remote-gateway-bootstrap.sh \
  openenv-s5a-gateway:/tmp/ --zone=us-east1-b
gcloud compute ssh openenv-s5a-gateway --zone=us-east1-b \
  --command="sudo sh /tmp/remote-gateway-bootstrap.sh $DOMAIN"
```

The gateway derives sandbox service URLs of the form
`https://<workspace>--<sandbox>.<domain>:8080/` from the wildcard SAN.

## 3. Register it without changing the active gateway

Copy the generated client bundle into the CLI's gateway directory with
owner-only permissions:

```bash
MTLS=~/.config/openshell/gateways/openenv-s5a/mtls
mkdir -p "$MTLS" && chmod 700 "$MTLS" "$(dirname "$MTLS")"
for f in ca.crt client/tls.crt client/tls.key; do
  gcloud compute ssh openenv-s5a-gateway --zone=us-east1-b \
    --command="sudo cat /var/lib/openshell/tls/$f" > "$MTLS/$(basename "$f")"
done
chmod 600 "$MTLS"/*
openshell gateway add "https://$DOMAIN:8080" --name openenv-s5a --remote "$USER@$IP"
openshell gateway select openshell   # `add` activates the new gateway
OPENSHELL_GATEWAY=openenv-s5a openshell status
```

Select tests with `OPENSHELL_GATEWAY=openenv-s5a`. Trust the private CA without
dropping the public roots by combining the two:

```bash
cat "$(uv run python -c 'import certifi; print(certifi.where())')" "$MTLS/ca.crt" \
  > /tmp/openenv-s5a-bundle.pem
export SSL_CERT_FILE=/tmp/openenv-s5a-bundle.pem
```

Run the tests with the commands in
[protocol evidence](protocol-spike.md#commands).

## 4. Tear down

```bash
openshell gateway remove openenv-s5a
gcloud compute instances delete openenv-s5a-gateway --zone=us-east1-b --quiet
gcloud compute firewall-rules delete openenv-s5a-gateway --quiet
```

## OIDC variant (S5b)

Use separate `openenv-s5b-gateway` VM/firewall names and the `openenv-s5b` tag
in the provisioning commands above. Run
[`remote-oidc-gateway-bootstrap.sh`](examples/remote-oidc-gateway-bootstrap.sh)
instead of the mTLS bootstrap, passing the VM's wildcard routing domain.
It runs OpenShell 0.1.2 and Keycloak 26.0.8. The imported test realm issues
an `openshell-cli` audience token with the `openshell-admin` role.

Keycloak listens only on `127.0.0.1:8180` on the VM. The gateway acknowledges
numeric-loopback HTTP discovery with `dangerously_allow_insecure_http = true`;
remote gateway and service traffic still use verified TLS. mTLS user auth is
disabled, while the guest PKI remains configured. This disposable fixture
uses a public fixed test secret and must never serve as a production realm.
The firewall must remain restricted to the tester's public IP.

Use an isolated configuration directory instead of changing the active gateway:

```bash
export XDG_CONFIG_HOME="$(mktemp -d /tmp/openenv-s5b-config.XXXXXX)"
GATEWAY_DIR="$XDG_CONFIG_HOME/openshell/gateways/openenv-s5b"
mkdir -p "$GATEWAY_DIR/mtls"
umask 077
gcloud compute ssh openenv-s5b-gateway --zone=us-east1-b \
  --command='sudo cat /var/lib/openshell/tls/ca.crt' > "$GATEWAY_DIR/mtls/ca.crt"
gcloud compute ssh openenv-s5b-gateway --zone=us-east1-b \
  --command='sudo cat /var/lib/openshell/s5b-token.json' > "$GATEWAY_DIR/oidc_token.json"
cat > "$GATEWAY_DIR/metadata.json" <<JSON
{"gateway_endpoint":"https://$DOMAIN:8080","auth_mode":"oidc",
 "oidc_issuer":"http://127.0.0.1:8180/realms/openshell",
 "oidc_client_id":"openshell-cli","oidc_audience":"openshell-cli"}
JSON
cat "$(uv run python -c 'import certifi; print(certifi.where())')" \
  "$GATEWAY_DIR/mtls/ca.crt" > "$XDG_CONFIG_HOME/ca-bundle.pem"
export SSL_CERT_FILE="$XDG_CONFIG_HOME/ca-bundle.pem"
export OPENSHELL_GATEWAY=openenv-s5b
export OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(cat tests/integration/images/echo/remote-image-ref.txt)"
unset OPENENV_OPENSHELL_PROBE_CLIENT_CERT_DIR
uv run pytest -m integration --no-cov tests/integration/test_protocol_spike.py \
  tests/integration/test_openenv_client.py -v --log-cli-level=INFO
```

The token expires after one hour; obtain a fresh client-credentials token on the
VM if needed. Do not print or commit it. The isolated gateway directory contains
only the public CA, metadata, and bearer token; no client certificate or key.
The bearer is used by the OpenShell SDK, not by the OpenEnv HTTP/WebSocket client.

After verifying no sandboxes remain, delete the VM and firewall as in section 4,
using the S5b names, and remove the isolated configuration directory. No
`openshell gateway remove` is needed because the active gateway was never changed.
