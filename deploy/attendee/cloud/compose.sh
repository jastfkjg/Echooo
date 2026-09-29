#!/usr/bin/env bash
set -euo pipefail
release=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec docker compose --project-name echooo-attendee-cloud --env-file "$release/image.env" -f "$release/compose.yaml" "$@"
