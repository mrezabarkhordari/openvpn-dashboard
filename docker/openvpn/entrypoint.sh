#!/usr/bin/env bash
# Runtime: tun, first-boot PKI via generate-config.sh, NAT, exec openvpn.
# Packages and angristan are baked into the image. Never apt-get here.
set -euo pipefail

OPENVPN_DIR="${OPENVPN_DIR:-/etc/openvpn}"
STATUS_FILE="${OPENVPN_STATUS_FILE:-${OPENVPN_DIR}/status.log}"
STATUS_INTERVAL="${OPENVPN_STATUS_INTERVAL:-10}"
MGMT_PORT="${OPENVPN_MGMT_PORT:-${OPENVPN_MANAGEMENT_PORT:-7505}}"
MGMT_ADDR="${OPENVPN_MGMT_ADDR:-127.0.0.1}"
SUBNET="${OPENVPN_SUBNET:-10.8.0.0/24}"
CCD_DIR="${OPENVPN_CCD_DIR:-${OPENVPN_DIR}/ccd}"
GENERATOR="${OPENVPN_GENERATE_CONFIG:-/opt/vpn/generate-config.sh}"

log() { printf 'entrypoint: %s\n' "$*"; }
die() { printf 'entrypoint: %s\n' "$*" >&2; exit 1; }

find_server_conf() {
	local f
	for f in \
		"${OPENVPN_DIR}/server.conf" \
		"${OPENVPN_DIR}/server/server.conf" \
		"${OPENVPN_DIR}/server/openvpn.conf"; do
		if [[ -f "$f" ]]; then
			printf '%s' "$f"
			return 0
		fi
	done
	return 1
}

ensure_tun() {
	if [[ ! -c /dev/net/tun ]]; then
		mkdir -p /dev/net
		mknod /dev/net/tun c 10 200
		chmod 600 /dev/net/tun
	fi
}

enable_forwarding() {
	if [[ -w /proc/sys/net/ipv4/ip_forward ]]; then
		echo 1 >/proc/sys/net/ipv4/ip_forward || true
	fi
	sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
	if [[ "${OPENVPN_IPV6:-n}" == "y" ]]; then
		sysctl -w net.ipv6.conf.all.forwarding=1 >/dev/null 2>&1 || true
	fi
}

apply_nat() {
	local nic
	nic="$(ip -4 route show default 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')"
	if [[ -z "$nic" ]]; then
		log "No default route; skipping MASQUERADE"
		return 0
	fi
	if ! iptables -t nat -C POSTROUTING -s "$SUBNET" -o "$nic" -j MASQUERADE 2>/dev/null; then
		iptables -t nat -A POSTROUTING -s "$SUBNET" -o "$nic" -j MASQUERADE
	fi
	iptables -C FORWARD -s "$SUBNET" -j ACCEPT 2>/dev/null || iptables -A FORWARD -s "$SUBNET" -j ACCEPT
	iptables -C FORWARD -d "$SUBNET" -j ACCEPT 2>/dev/null || iptables -A FORWARD -d "$SUBNET" -j ACCEPT
	log "NAT on ${nic} for ${SUBNET}"
}

ensure_dirs() {
	mkdir -p "$CCD_DIR" "${OPENVPN_DIR}/clients" "$(dirname "$STATUS_FILE")"
	touch "$STATUS_FILE"
}

ensure_ccd_in_conf() {
	local conf="$1"
	if grep -Eqs '^[[:space:]]*client-config-dir[[:space:]]' "$conf"; then
		sed -i "s|^[[:space:]]*client-config-dir[[:space:]].*|client-config-dir ${CCD_DIR}|" "$conf"
	else
		printf '\nclient-config-dir %s\n' "$CCD_DIR" >>"$conf"
	fi
}

main() {
	ensure_tun
	mkdir -p "$OPENVPN_DIR"
	cd "$OPENVPN_DIR"

	if find_server_conf >/dev/null; then
		log "Existing OpenVPN config found; skipping generate-config"
	else
		[[ -f "$GENERATOR" ]] || die "missing ${GENERATOR}"
		log "No server.conf; generating PKI and config with easy-rsa"
		bash "$GENERATOR"
	fi

	local server_conf conf_dir
	server_conf="$(find_server_conf)" || die "no OpenVPN server config under ${OPENVPN_DIR}"
	conf_dir="$(dirname "$server_conf")"

	ensure_dirs
	ensure_ccd_in_conf "$server_conf"
	enable_forwarding
	apply_nat

	log "exec openvpn --config ${server_conf} --client-config-dir ${CCD_DIR} --status ${STATUS_FILE} ${STATUS_INTERVAL} --management ${MGMT_ADDR} ${MGMT_PORT}"
	exec openvpn \
		--cd "$conf_dir" \
		--config "$server_conf" \
		--client-config-dir "$CCD_DIR" \
		--status "$STATUS_FILE" "$STATUS_INTERVAL" \
		--status-version 2 \
		--management "$MGMT_ADDR" "$MGMT_PORT"
}

main "$@"
