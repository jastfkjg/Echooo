#!/usr/bin/env bash
set -euo pipefail
umask 077
release=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ $# == 4 ]] || { echo 'Usage: deploy.sh ATTENDEE_DIGEST POSTGRES_DIGEST REDIS_DIGEST CADDY_DIGEST' >&2; exit 1; }
for reference in "$@"; do
    [[ "$reference" =~ ^[a-z0-9][a-z0-9.-]*\.aliyuncs\.com/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*@sha256:[a-f0-9]{64}$ ]] || { echo 'Immutable ACR digests are required.' >&2; exit 1; }
done
exec 9>/opt/echooo/deploy.lock
flock -n 9 || { echo 'Another Echooo/Attendee deployment is running.' >&2; exit 1; }
bash "$release/preflight.sh"
[[ ! -e "$release/image.env" ]] || { echo 'Use a fresh release directory.' >&2; exit 1; }
printf 'ATTENDEE_IMAGE=%s\nPOSTGRES_IMAGE=%s\nREDIS_IMAGE=%s\nCADDY_IMAGE=%s\n' "$@" > "$release/image.env"
python3 "$release/configure.py" prepare
home=/opt/echooo/attendee
mkdir -p "$home/tls" "$home/backups"
if [[ ! -f "$home/tls/server.crt" ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
        -keyout "$home/tls/server.key" -out "$home/tls/server.crt" \
        -subj /CN=echooo-attendee-gateway -addext subjectAltName=DNS:echooo-attendee-gateway >/dev/null 2>&1
    chmod 600 "$home/tls/server.key"
    chmod 644 "$home/tls/server.crt"
fi
openssl x509 -checkend 604800 -noout -in "$home/tls/server.crt" >/dev/null || { echo 'Renew the private callback certificate before deploying (see docs/ATTENDEE_CLOUD.md).' >&2; exit 1; }
compose() { bash "$release/compose.sh" "$@"; }
app() { bash /opt/echooo/current/compose.sh "$@"; }
previous=$(readlink -f "$home/current" 2>/dev/null || true)
compose config --quiet
compose pull
if [[ -n "$previous" ]]; then
    bash "$previous/compose.sh" exec -T api python manage.py shell < "$release/check_idle.py"
elif [[ -n $(compose ps -a -q) ]]; then
    echo 'An incomplete first deployment exists. Inspect it before recovery; see docs/ATTENDEE_CLOUD.md.' >&2
    exit 1
fi
backup="$home/backups/$(basename "$release")"
cp /opt/echooo/app.env "$backup.app.env"
app_stopped=false
config_changed=false
recover() {
    code=$?
    if [[ $code != 0 ]]; then
        if [[ $config_changed == true ]]; then
            cp "$backup.app.env" /opt/echooo/app.env
        fi
        if [[ $app_stopped == true ]]; then
            app up -d --no-deps --force-recreate --wait --wait-timeout 180 app || true
        fi
        echo "Attendee deployment failed; release not promoted. Preserve $backup and inspect services before retrying." >&2
    fi
    exit "$code"
}
trap recover EXIT
# Pause invitations during the update; application shutdown also ends local recording.
app_stopped=true
app stop app
if [[ -n "$previous" ]]; then
    bash "$previous/compose.sh" exec -T api python manage.py shell < "$release/check_idle.py"
    compose stop api worker
    compose exec -T postgres pg_dump -U attendee -d attendee -Fc > "$backup.dump.tmp"
    mv "$backup.dump.tmp" "$backup.dump"
fi
compose up -d --wait --wait-timeout 120 postgres redis
compose run --rm --no-deps --user root api chown 1000:1000 /attendee/local-debug /attendee/staticfiles
compose run --rm --no-deps api python manage.py migrate --noinput
compose run --rm --no-deps api python manage.py shell -c 'exec(open("echooo_bootstrap.py").read())'
compose run --rm --no-deps api python manage.py collectstatic --noinput
compose up -d --wait --wait-timeout 240 api gateway worker
# Probe the candidate from Echooo's own Docker network before changing app.env.
app run --rm --no-deps -T app python -c 'import urllib.request; urllib.request.urlopen("http://attendee-api:8000", timeout=15)'
config_changed=true
python3 "$release/configure.py" connect
app up -d --no-deps --force-recreate --wait --wait-timeout 180 app
app exec -T app python -c 'import asyncio; from echooo.config import Settings; from echooo.meeting_bots import AttendeeClient; asyncio.run(AttendeeClient(Settings.load()).request("GET", "bots")); print("Echooo to Attendee authentication passed.")'
compose exec -T worker python < "$release/check_callback.py"
if [[ -n "$previous" ]]; then ln -sfn "$previous" "$home/previous"; fi
ln -sfn "$release" "$home/current"
trap - EXIT
echo 'Attendee deployed and connected to Echooo. Dashboard: SSH tunnel to 127.0.0.1:8011.'
