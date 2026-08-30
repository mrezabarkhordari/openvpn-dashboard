#!/usr/bin/env bash
# Dual deploy:
#   ./install.sh              full stack (docker compose --profile vpn up)
#   ./install.sh --ui-only    web + collector + scheduler (no vpn profile)
#   ./install.sh --vpn-only   OpenVPN container only (--profile vpn)
# --ui-only requires OPENVPN_DATA_DIR (typical /etc/openvpn for attach).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="all"

usage() {
	cat <<'EOF'
Usage: ./install.sh [--vpn-only|--ui-only]

  (default)   Full stack: OpenVPN + UI + collector + scheduler
              (docker compose --profile vpn up)
  --vpn-only  Start only the OpenVPN container (--profile vpn)
  --ui-only   Start web + collector + scheduler only (no openvpn profile)

--ui-only requires OPENVPN_DATA_DIR in the environment or .env
(typical: /etc/openvpn to attach to a host OpenVPN install).
status.log must be on that mounted tree, e.g.
  OPENVPN_STATUS_LOG=/etc/openvpn/status.log
Do not use host /var/log/openvpn unless that path is also mounted.
The OpenVPN container / angristan installer is not started in --ui-only.
EOF
	exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--vpn-only) MODE="vpn" ;;
	--ui-only) MODE="ui" ;;
	-h | --help) usage 0 ;;
	*)
		echo "Unknown option: $1" >&2
		usage 1
		;;
	esac
	shift
done

cd "$ROOT"

if [[ ! -f .env ]]; then
	cp .env.example .env
	echo "Wrote .env from .env.example — set SECRET_KEY, ADMIN_PASSWORD, OPENVPN_SERVER_ADDRESS."
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

resolve_dir() {
	local raw="${1:-./data}"
	if [[ "$raw" != /* ]]; then
		raw="${ROOT}/${raw#./}"
	fi
	mkdir -p "$raw"
	(cd "$raw" && pwd)
}

if [[ "$MODE" == "ui" ]]; then
	if [[ -z "${OPENVPN_DATA_DIR:-}" ]]; then
		echo "Error: --ui-only requires OPENVPN_DATA_DIR (typical: /etc/openvpn)." >&2
		echo "Set it in .env or the environment to attach to an existing OpenVPN tree." >&2
		echo "status.log must live on that mounted tree (OPENVPN_STATUS_LOG=/etc/openvpn/status.log)," >&2
		echo "not host /var/log/openvpn unless that path is also mounted." >&2
		exit 1
	fi
	if [[ "$OPENVPN_DATA_DIR" != /* ]]; then
		OPENVPN_DATA_DIR="${ROOT}/${OPENVPN_DATA_DIR#./}"
	fi
	if [[ ! -d "$OPENVPN_DATA_DIR" ]]; then
		echo "Error: OPENVPN_DATA_DIR does not exist: $OPENVPN_DATA_DIR" >&2
		exit 1
	fi
	OPENVPN_DATA_DIR="$(cd "$OPENVPN_DATA_DIR" && pwd)"
else
	OPENVPN_DATA_DIR="$(resolve_dir "${OPENVPN_DATA_DIR:-./stack-data/openvpn}")"
	mkdir -p "${OPENVPN_DATA_DIR}/ccd" "${OPENVPN_DATA_DIR}/clients"
fi

DATABASE_HOST_PATH="$(resolve_dir "${DATABASE_HOST_PATH:-./stack-data/ui}")"
CLIENT_CONFIGS_PATH="$(resolve_dir "${CLIENT_CONFIGS_PATH:-./ovpn-configs}")"
export OPENVPN_DATA_DIR DATABASE_HOST_PATH CLIENT_CONFIGS_PATH

compose() {
	local files=(-f "$ROOT/docker-compose.yml")
	local extra=()
	local services=()
	case "$MODE" in
	all)
		extra=(--profile vpn)
		;;
	vpn)
		extra=(--profile vpn)
		services=(openvpn)
		;;
	ui)
		services=(web collector scheduler)
		;;
	esac
	docker compose \
		--project-directory "$ROOT" \
		--env-file "$ROOT/.env" \
		"${extra[@]}" \
		"${files[@]}" \
		"$@" \
		"${services[@]}"
}

echo "Starting stack (mode=${MODE}) data=${OPENVPN_DATA_DIR}"
compose up -d --build

echo "UI: http://127.0.0.1:${WEB_PORT:-8800}/"
echo "VPN: ${OPENVPN_PROTO:-${OPENVPN_PROTOCOL:-udp}}/${OPENVPN_PORT:-1194}"
