#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "Python 3.12 fehlt. Installiere Python 3.12 und python3.12-venv und starte erneut." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  python3.12 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
exec python -m hrv_recorder "$@"
