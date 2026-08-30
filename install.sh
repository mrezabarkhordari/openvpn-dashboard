#!/usr/bin/env bash
# Compatibility wrapper — implementation lives in scripts/install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/scripts/install.sh" "$@"
