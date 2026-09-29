#!/usr/bin/env bash
set -euo pipefail
umask 077
release=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
image=${1:?Usage: deploy.sh APP_DIGEST POSTGRES_DIGEST}
postgres_image=${2:?Pass the mirrored PostgreSQL image digest}
for reference in "$image" "$postgres_image"; do
    [[ "$reference" =~ ^[a-z0-9][a-z0-9.-]*\.aliyuncs\.com/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*@sha256:[a-f0-9]{64}$ ]] || { echo 'An immutable Alibaba Cloud ACR image digest is required.' >&2; exit 1; }
done
bash "$release/preflight.sh"
exec 9>/opt/echooo/deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
[[ -f /opt/echooo/deploy.env && -f /opt/echooo/app.env ]] || { echo 'Configure deploy.env and app.env first.' >&2; exit 1; }
# Never reuse a release directory: it also records the configuration for rollback.
[[ ! -e "$release/image.env" ]] || { echo 'Use a fresh release directory for each deployment.' >&2; exit 1; }
printf 'ECHOOO_IMAGE=%s\nPOSTGRES_IMAGE=%s\n' "$image" "$postgres_image" > "$release/image.env"
compose() { bash "$release/compose.sh" "$@"; }
compose config --quiet
origin=$(compose config --format json | python3 "$release/validate_config.py")

compose pull
# Validate candidate settings without connecting to or migrating the database.
compose run --rm --no-deps app python -c 'from echooo.config import Settings; Settings.load().validate(); print("Application configuration passed.")'
# Check configured database credentials before interrupting a healthy release.
if [[ -n "$(compose ps --status running -q db)" ]]; then
    compose run --rm --no-deps app python -c 'from sqlalchemy import create_engine, text; from echooo.config import Settings; engine=create_engine(Settings.load().database_url); connection=engine.connect(); connection.execute(text("SELECT 1")); connection.close(); engine.dispose(); print("Database credentials passed.")'
fi
# GNU readlink -f can succeed for a missing final path component.
previous=""
if [[ -f /opt/echooo/current/compose.sh ]]; then
    previous=$(readlink -f /opt/echooo/current)
elif [[ -e /opt/echooo/current || -L /opt/echooo/current ]]; then
    echo 'Existing Echooo deployment is incomplete; inspect current before retrying.' >&2
    exit 1
fi
# Quiesce writes before backup and startup migrations. Do not overlap app workers.
compose stop app
# Back up the existing database before recreating it with a new image.
# First deployment (or a stopped DB) needs a running DB for pg_dump.
if [[ -z "$(compose ps --status running -q db)" ]]; then
    compose up -d --wait --wait-timeout 120 db
fi
mkdir -p /opt/echooo/backups
backup="/opt/echooo/backups/$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$release").dump"
if ! compose exec -T db pg_dump -U echooo -d echooo -Fc > "$backup.tmp"; then
    rm -f "$backup.tmp"
    echo 'Backup failed; application is stopped. Investigate before restarting.' >&2
    exit 1
fi
mv "$backup.tmp" "$backup"
if ! compose up -d --wait --wait-timeout 180; then
    echo "Deployment failed. Backup: $backup. Check compose logs. No automatic database rollback was attempted." >&2
    exit 1
fi
# Verify the configured public route; HTTPS also verifies certificate trust.
healthy=false
for attempt in {1..13}; do
    if curl --fail --silent --show-error --connect-timeout 5 --max-time 10 "$origin/health" > /dev/null; then
        healthy=true
        break
    fi
    if (( attempt < 13 )); then sleep 5; fi
done
if [[ "$healthy" != true ]]; then
    echo "Public health check failed after 13 attempts: $origin/health. Release was not promoted." >&2
    exit 1
fi
if [[ -n "$previous" && -d "$previous" ]]; then
    ln -sfn "$previous" /opt/echooo/previous
fi
ln -sfn "$release" /opt/echooo/current
printf 'Deployed %s\nBackup: %s\n' "$image" "$backup"
