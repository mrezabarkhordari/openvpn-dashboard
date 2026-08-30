#!/usr/bin/env bash
set -euo pipefail

PINNED_COMMIT="ad22fd9eb0c8569a885f836ef6e37576d8702e9f"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${SCRIPT_DIR}/openvpn-install.sh"
URL="https://raw.githubusercontent.com/angristan/openvpn-install/${PINNED_COMMIT}/openvpn-install.sh"

echo "Fetching angristan/openvpn-install @ ${PINNED_COMMIT}"
curl -fsSL "${URL}" -o "${DEST}"
chmod +x "${DEST}"
echo "Wrote ${DEST}"
