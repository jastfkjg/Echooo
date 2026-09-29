#!/usr/bin/env bash
# Isolated runner-only database, volumes and Docker network; never uses server state.
set -euo pipefail
umask 077
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
work=$(mktemp -d)
project="attendee-smoke-${GITHUB_RUN_ID:-$$}-${GITHUB_RUN_ATTEMPT:-1}"
compose() { docker compose --project-name "$project" -f "$work/compose.yaml" "$@"; }
cleanup() {
    compose down -v >/dev/null 2>&1 || true
    docker network rm "$project" >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT
python3 - "$source_dir" "$work" "$project" <<'PY'
import importlib.util, pathlib, sys
source, work = map(pathlib.Path, sys.argv[1:3])
spec = importlib.util.spec_from_file_location('configure', source / 'configure.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
module.prepare(work)
text = (source / 'compose.yaml').read_text().replace('/opt/echooo/attendee', str(work / 'attendee'))
text = text.replace('name: echooo_proxy', 'name: ' + sys.argv[3])
text = text.replace("    ports: ['127.0.0.1:8011:8000']\n", '')
(work / 'compose.yaml').write_text(text)
PY
cp "$source_dir/Caddyfile" "$work/Caddyfile"
mkdir -p "$work/attendee/tls"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -keyout "$work/attendee/tls/server.key" -out "$work/attendee/tls/server.crt" -subj /CN=echooo-attendee-gateway -addext subjectAltName=DNS:echooo-attendee-gateway >/dev/null 2>&1
chmod 644 "$work/attendee/tls/server.crt"
docker network create "$project" >/dev/null
compose up -d --wait --wait-timeout 120 postgres redis
compose run --rm --no-deps --user root api chown 1000:1000 /attendee/local-debug /attendee/staticfiles
compose run --rm --no-deps api python manage.py check
compose run --rm --no-deps api python manage.py migrate --noinput
compose run --rm --no-deps api python manage.py shell -c 'exec(open("echooo_bootstrap.py").read())'
compose run --rm --no-deps api python manage.py collectstatic --noinput
compose up -d --wait --wait-timeout 240 api gateway worker
compose exec -T api python manage.py shell < "$source_dir/check_idle.py"
echo 'Attendee API authentication, worker and database smoke test passed.'
