#!/usr/bin/env bash
# No service mutations: safe to run before building or deploying.
set -euo pipefail
for tool in docker python3 curl flock tar readlink; do
    command -v "$tool" >/dev/null || { echo "Missing server dependency: $tool" >&2; exit 1; }
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 6) else "Python 3.6+ is required on the host.")'
docker info >/dev/null
version=$(docker compose version --short)
python3 - "$version" <<'PY'
import re, sys
match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", sys.argv[1])
if not match or tuple(map(int, match.groups())) < (2, 24, 0):
    sys.exit("Docker Compose v2.24+ is required.")
PY
for file in /opt/echooo/deploy.env /opt/echooo/app.env; do
    [[ -r "$file" ]] || { echo "Missing or unreadable $file" >&2; exit 1; }
done
[[ -w /opt/echooo ]] || { echo '/opt/echooo must be writable by the SSH deployment user.' >&2; exit 1; }
printf 'Server prerequisites passed (Compose %s).\n' "$version"
