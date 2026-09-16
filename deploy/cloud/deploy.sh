#!/usr/bin/env bash
set -euo pipefail
umask 077
release=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
image=${1:?Usage: deploy.sh registry.cn-hangzhou.aliyuncs.com/namespace/repo@sha256:digest}
[[ "$image" =~ ^[a-z0-9][a-z0-9.-]*\.aliyuncs\.com/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*@sha256:[a-f0-9]{64}$ ]] || { echo 'An immutable Alibaba Cloud ACR image digest is required.' >&2; exit 1; }
exec 9>/opt/echooo/deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
[[ -f /opt/echooo/deploy.env && -f /opt/echooo/app.env ]] || { echo 'Configure deploy.env and app.env first.' >&2; exit 1; }
# Never reuse a release directory: it also records the configuration for rollback.
[[ ! -e "$release/image.env" ]] || { echo 'Use a fresh release directory for each deployment.' >&2; exit 1; }
printf 'ECHOOO_IMAGE=%s\n' "$image" > "$release/image.env"
compose() { bash "$release/compose.sh" "$@"; }
compose config --quiet
origin=$(compose config --format json | python3 "$release/validate_config.py")

compose pull
compose up -d --wait --wait-timeout 120 db
previous=$(readlink -f /opt/echooo/current 2>/dev/null || true)
# Quiesce writes before backup and startup migrations. Do not overlap app workers.
compose stop app
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
curl --fail --silent --show-error --retry 12 --retry-all-errors --retry-delay 5 --max-time 10 "$origin/health" > /dev/null
if [[ -n "$previous" && -d "$previous" ]]; then
    ln -sfn "$previous" /opt/echooo/previous
fi
ln -sfn "$release" /opt/echooo/current
printf 'Deployed %s\nBackup: %s\n' "$image" "$backup"
