#!/usr/bin/env bash
set -euo pipefail
for tool in docker python3 openssl flock tar readlink; do
    command -v "$tool" >/dev/null || { echo "Missing server dependency: $tool" >&2; exit 1; }
done
docker info >/dev/null
[[ $(docker info --format '{{.Architecture}}') =~ ^(x86_64|amd64)$ ]] || { echo 'Attendee requires an x86_64 server.' >&2; exit 1; }
docker network inspect echooo_proxy >/dev/null
[[ -r /opt/echooo/app.env && -f /opt/echooo/current/compose.sh ]]
[[ -w /opt/echooo ]]
version=$(docker compose version --short)
python3 - "$version" <<'PY'
import re, sys
match = re.match(r'v?(\d+)\.(\d+)\.(\d+)', sys.argv[1])
assert match and tuple(map(int, match.groups())) >= (2, 24, 0), 'Docker Compose v2.24+ is required.'
PY
bash /opt/echooo/current/compose.sh exec -T app python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)'
echo 'Attendee server prerequisites passed.'
