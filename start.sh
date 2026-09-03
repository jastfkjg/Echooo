#!/usr/bin/env bash
# Run Echooo locally from any working directory. Requires Python 3.11+.
set -euo pipefail

echooo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$echooo_root"

usage() {
  cat <<'EOF'
Usage: ./start.sh [--mock] [--port PORT] [--install]

  --mock       Use demo STT/LLM and browser speech for this run.
  --port PORT  Run on http://127.0.0.1:PORT with matching local cookie/origin settings.
  --install    Reinstall project and development dependencies before starting.
  -h, --help   Show this help.

Creates .venv and a demo .env when missing. Existing .env files are preserved.
Dependencies are installed on first use and when pyproject.toml changes.
Set PYTHON to a Python 3.11+ executable when creating the virtual environment.
Stop the server with Ctrl+C.
EOF
}

echooo_install=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mock)
      export STT_PROVIDER=mock LLM_PROVIDER=mock TTS_PROVIDER=browser
      shift
      ;;
    --port)
      if [[ $# -lt 2 || ! "$2" =~ ^[0-9]{1,5}$ ]]; then
        printf '%s\n' 'Error: --port requires an integer from 1 to 65535.' >&2
        exit 2
      fi
      echooo_port=$((10#$2))
      if (( echooo_port < 1 || echooo_port > 65535 )); then
        printf '%s\n' 'Error: --port requires an integer from 1 to 65535.' >&2
        exit 2
      fi
      export APP_HOST=127.0.0.1 APP_PORT="$echooo_port"
      export PUBLIC_ORIGIN="http://127.0.0.1:$echooo_port" COOKIE_SECURE=false
      shift 2
      ;;
    --install) echooo_install=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Error: unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

echooo_python="$echooo_root/.venv/bin/python"
if [[ ! -x "$echooo_python" ]]; then
  if [[ -e "$echooo_root/.venv" ]]; then
    printf '%s\n' 'Error: .venv exists but has no working Python. Move or repair it, then retry.' >&2
    exit 1
  fi
  echooo_bootstrap=""
  if [[ -n "${PYTHON:-}" ]]; then
    echooo_candidates=("$PYTHON")
  else
    echooo_candidates=(python3 python3.14 python3.13 python3.12 python3.11)
  fi
  for echooo_candidate in "${echooo_candidates[@]}"; do
    if command -v "$echooo_candidate" >/dev/null 2>&1 &&
       "$echooo_candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
      echooo_bootstrap="$echooo_candidate"
      break
    fi
  done
  if [[ -z "$echooo_bootstrap" ]]; then
    printf '%s\n' 'Error: Python 3.11+ is required. Install it or set PYTHON=/path/to/python3.' >&2
    exit 1
  fi
  printf '%s\n' 'Creating .venv...'
  "$echooo_bootstrap" -m venv "$echooo_root/.venv"
fi

if ! "$echooo_python" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  printf '%s\n' 'Error: .venv requires Python 3.11+. Rebuild it with a supported interpreter.' >&2
  exit 1
fi

echooo_stamp="$echooo_root/.venv/.echooo-dependencies.sha256"
echooo_fingerprint="$("$echooo_python" -c 'import hashlib; from pathlib import Path; print(hashlib.sha256(Path("pyproject.toml").read_bytes()).hexdigest())')"
echooo_previous=""
if [[ -f "$echooo_stamp" ]]; then
  echooo_previous="$(cat "$echooo_stamp")"
fi
if [[ "$echooo_install" == true || "$echooo_fingerprint" != "$echooo_previous" ]]; then
  printf '%s\n' 'Installing project and development dependencies...'
  if ! "$echooo_python" -m pip --disable-pip-version-check install -e '.[dev]'; then
    printf '%s\n' 'Dependency installation failed. Fix the pip configuration and run ./start.sh --install again.' >&2
    exit 1
  fi
  printf '%s\n' "$echooo_fingerprint" > "$echooo_stamp"
fi

if [[ ! -e "$echooo_root/.env" ]]; then
  (umask 077; cp -n "$echooo_root/.env.mock.example" "$echooo_root/.env")
  printf '%s\n' 'Created .env with local demo settings. Edit it to connect live providers.'
fi

printf '%s\n' 'Starting Echooo. Press Ctrl+C to stop.'
exec "$echooo_python" -m echooo
