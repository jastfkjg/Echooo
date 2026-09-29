#!/usr/bin/env bash
# Disposable local/CI Docker integration test; never uses the deployment volumes.
set -euo pipefail
suffix="${RANDOM}-$$"
network="echooo-smoke-$suffix"
db="echooo-smoke-db-$suffix"
app="echooo-smoke-app-$suffix"
image="echooo-smoke:$suffix"
cleanup() {
    docker rm -f -v "$app" "$db" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    docker image rm "$image" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker build -t "$image" .
docker network create "$network" >/dev/null
docker run -d --name "$db" --network "$network" -e POSTGRES_PASSWORD=smoke -e POSTGRES_USER=echooo -e POSTGRES_DB=echooo postgres:17-bookworm >/dev/null
ready=false
for attempt in {1..30}; do
    if docker exec "$db" pg_isready -U echooo -d echooo >/dev/null 2>&1; then ready=true; break; fi
    sleep 2
done
[[ "$ready" == true ]]
docker run -d --name "$app" --network "$network" --read-only --tmpfs /tmp:size=128m,mode=1777 --cap-drop ALL --security-opt no-new-privileges:true \
    -e "DATABASE_URL=postgresql+psycopg://echooo:smoke@$db:5432/echooo" \
    -e STT_PROVIDER=mock -e LLM_PROVIDER=mock -e TTS_PROVIDER=browser "$image" >/dev/null
ready=false
for attempt in {1..30}; do
    if docker exec "$app" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" 2>/dev/null; then ready=true; break; fi
    sleep 2
done
if [[ "$ready" != true ]]; then docker logs "$app"; exit 1; fi
docker exec "$app" python -c "import urllib.request; assert b'<html' in urllib.request.urlopen('http://127.0.0.1:8000/').read().lower()"
docker exec "$app" python -c "from echooo.config import Settings; from echooo.database import Store; from echooo.auth import Auth; s=Store(Settings.load().database_url); a=Auth(s); a.setup('smoke', 'smoke-test-password'); assert not a.needs_setup(); s.close()"
