#!/usr/bin/env bash
set -euo pipefail
cat /etc/ssl/certs/ca-certificates.crt /echooo-ca.crt > /tmp/echooo-ca-bundle.pem
export SSL_CERT_FILE=/tmp/echooo-ca-bundle.pem
exec /usr/local/bin/entrypoint.sh "$@"
