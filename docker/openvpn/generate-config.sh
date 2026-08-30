#!/usr/bin/env bash
# First-boot PKI + server.conf using easy-rsa already in the image.
# Never apt-get. Never systemctl. Never run the angristan OS installer.
set -euo pipefail

OPENVPN_DIR="${OPENVPN_DIR:-/etc/openvpn}"
EASYRSA_DIR="${EASYRSA_DIR:-${OPENVPN_DIR}/easy-rsa}"
CCD_DIR="${OPENVPN_CCD_DIR:-${OPENVPN_DIR}/ccd}"
CLIENTS_DIR="${OPENVPN_CLIENTS_DIR:-${OPENVPN_DIR}/clients}"
TEMPLATE="${OPENVPN_CLIENT_TEMPLATE:-${OPENVPN_DIR}/client-template.txt}"
SERVER_CN="${OPENVPN_SERVER_CN:-server}"
PORT="${OPENVPN_PORT:-${PORT:-1194}}"
PROTO="$(printf '%s' "${OPENVPN_PROTO:-udp}" | tr '[:upper:]' '[:lower:]')"
[[ "$PROTO" == tcp ]] || PROTO=udp
SUBNET="${OPENVPN_SUBNET:-10.8.0.0/24}"
CIPHER="${OPENVPN_CIPHER:-AES-256-GCM}"
AUTH="${OPENVPN_AUTH:-SHA256}"
# End-entity cert lifetime (server + client). Easy-RSA default is 825 (~2 years).
EASYRSA_CERT_EXPIRE="${OPENVPN_CERT_EXPIRE:-${EASYRSA_CERT_EXPIRE:-825}}"
export EASYRSA_CERT_EXPIRE

log() { printf 'generate-config: %s\n' "$*"; }
die() { printf 'generate-config: %s\n' "$*" >&2; exit 1; }

find_easyrsa_src() {
	if [[ -x /usr/share/easy-rsa/easyrsa ]]; then
		printf '%s' /usr/share/easy-rsa
		return 0
	fi
	if command -v easyrsa >/dev/null 2>&1; then
		local bin
		bin="$(command -v easyrsa)"
		printf '%s' "$(dirname "$(readlink -f "$bin")")"
		return 0
	fi
	return 1
}

cidr_netmask() {
	local bits="${1#*/}"
	[[ "$bits" =~ ^[0-9]+$ ]] || bits=24
	local mask=$((0xffffffff ^ ((1 << (32 - bits)) - 1)))
	printf '%d.%d.%d.%d' \
		$(((mask >> 24) & 255)) \
		$(((mask >> 16) & 255)) \
		$(((mask >> 8) & 255)) \
		$((mask & 255))
}

dns_pair() {
	local raw="${OPENVPN_DNS_CHOICE:-${DNS:-11}}"
	if [[ -n "${OPENVPN_DNS1:-${DNS1:-}}" ]]; then
		printf '%s %s' "${OPENVPN_DNS1:-${DNS1}}" "${OPENVPN_DNS2:-${DNS2:-}}"
		return 0
	fi
	case "$raw" in
	1 | system) printf '' ;;
	3 | cloudflare) printf '1.1.1.1 1.0.0.1' ;;
	4 | quad9) printf '9.9.9.9 149.112.112.112' ;;
	5 | quad9-uncensored) printf '9.9.9.10 149.112.112.10' ;;
	6 | fdn) printf '80.67.169.40 80.67.169.12' ;;
	7 | dnswatch) printf '84.200.69.80 84.200.70.40' ;;
	8 | opendns) printf '208.67.222.222 208.67.220.220' ;;
	9 | google) printf '8.8.8.8 8.8.4.4' ;;
	10 | yandex) printf '77.88.8.8 77.88.8.1' ;;
	11 | adguard) printf '94.140.14.14 94.140.15.15' ;;
	12 | nextdns) printf '45.90.28.167 45.90.30.167' ;;
	13 | custom) printf '%s %s' "${OPENVPN_DNS1:-}" "${OPENVPN_DNS2:-}" ;;
	*) printf '94.140.14.14 94.140.15.15' ;;
	esac
}

ensure_easyrsa_tree() {
	local src
	src="$(find_easyrsa_src)" || die "easyrsa not found (tried /usr/share/easy-rsa and PATH)"
	mkdir -p "$EASYRSA_DIR"
	if [[ ! -x "${EASYRSA_DIR}/easyrsa" ]]; then
		cp -a "${src}/." "$EASYRSA_DIR/"
	fi
	[[ -x "${EASYRSA_DIR}/easyrsa" ]] || die "easyrsa missing after copy from ${src}"
}

run_easyrsa() {
	(
		cd "$EASYRSA_DIR"
		export EASYRSA_BATCH=1
		export EASYRSA_PKI="${EASYRSA_DIR}/pki"
		export EASYRSA_CERT_EXPIRE
		# Easy-RSA 3.1: build-*-full takes CN from the filename, not EASYRSA_REQ_CN.
		unset EASYRSA_REQ_CN
		exec ./easyrsa --batch "$@"
	)
}

run_easyrsa_ca() {
	(
		cd "$EASYRSA_DIR"
		export EASYRSA_BATCH=1
		export EASYRSA_PKI="${EASYRSA_DIR}/pki"
		export EASYRSA_REQ_CN="${EASYRSA_REQ_CN:-OpenVPN-CA}"
		exec ./easyrsa --batch build-ca nopass
	)
}

init_pki() {
	local pki="${EASYRSA_DIR}/pki"
	if [[ -f "${pki}/ca.crt" && -f "${pki}/issued/${SERVER_CN}.crt" ]]; then
		log "Reusing existing PKI in ${pki}"
		[[ -f "${EASYRSA_DIR}/SERVER_NAME_GENERATED" ]] || printf '%s\n' "$SERVER_CN" >"${EASYRSA_DIR}/SERVER_NAME_GENERATED"
		return 0
	fi

	if [[ ! -f "${pki}/ca.crt" ]]; then
		log "Initializing PKI (easy-rsa) in ${EASYRSA_DIR}"
		if [[ -d "$pki" ]]; then
			run_easyrsa init-pki <<<'yes' || run_easyrsa init-pki
		else
			run_easyrsa init-pki
		fi
		run_easyrsa_ca
	else
		log "Reusing existing CA; issuing server certificate"
	fi

	if [[ ! -f "${pki}/issued/${SERVER_CN}.crt" ]]; then
		run_easyrsa build-server-full "$SERVER_CN" nopass
	fi
	if [[ ! -f "${pki}/dh.pem" ]]; then
		log "Generating Diffie-Hellman parameters (this can take a minute)"
		run_easyrsa gen-dh
	fi
	if [[ ! -f "${pki}/crl.pem" ]]; then
		run_easyrsa gen-crl
	fi
	printf '%s\n' "$SERVER_CN" >"${EASYRSA_DIR}/SERVER_NAME_GENERATED"
}

copy_server_material() {
	local pki="${EASYRSA_DIR}/pki"
	[[ -f "${pki}/ca.crt" ]] || die "missing ${pki}/ca.crt"
	[[ -f "${pki}/issued/${SERVER_CN}.crt" ]] || die "missing server cert"
	[[ -f "${pki}/private/${SERVER_CN}.key" ]] || die "missing server key"
	[[ -f "${pki}/dh.pem" ]] || die "missing ${pki}/dh.pem"

	cp -f "${pki}/ca.crt" "${OPENVPN_DIR}/ca.crt"
	cp -f "${pki}/issued/${SERVER_CN}.crt" "${OPENVPN_DIR}/server.crt"
	cp -f "${pki}/private/${SERVER_CN}.key" "${OPENVPN_DIR}/server.key"
	cp -f "${pki}/dh.pem" "${OPENVPN_DIR}/dh.pem"
	if [[ -f "${pki}/crl.pem" ]]; then
		cp -f "${pki}/crl.pem" "${OPENVPN_DIR}/crl.pem"
		chmod 644 "${OPENVPN_DIR}/crl.pem"
	fi
	chmod 644 "${OPENVPN_DIR}/ca.crt" "${OPENVPN_DIR}/server.crt" "${OPENVPN_DIR}/dh.pem"
	chmod 600 "${OPENVPN_DIR}/server.key"
}

ensure_tls_crypt() {
	local key="${OPENVPN_DIR}/tls-crypt.key"
	if [[ -f "$key" ]]; then
		return 0
	fi
	log "Generating tls-crypt.key"
	openvpn --genkey secret "$key"
	chmod 600 "$key"
}

write_client_template() {
	local endpoint="${OPENVPN_ENDPOINT:-CHANGE_ME}"
	local cport="${OPENVPN_CLIENT_PORT:-${PORT}}"
	{
		echo "client"
		if [[ "$PROTO" == tcp ]]; then
			echo "proto tcp-client"
		else
			echo "proto udp"
			echo "explicit-exit-notify"
		fi
		echo "remote ${endpoint} ${cport}"
		echo "dev tun"
		echo "resolv-retry infinite"
		echo "nobind"
		echo "persist-key"
		echo "persist-tun"
		echo "remote-cert-tls server"
		echo "auth ${AUTH}"
		echo "cipher ${CIPHER}"
		echo "verb 3"
	} >"$TEMPLATE"
	log "Wrote ${TEMPLATE}"
}

write_server_conf() {
	local conf="${OPENVPN_DIR}/server.conf"
	local net="${SUBNET%%/*}"
	local mask
	mask="$(cidr_netmask "$SUBNET")"
	local dns1 dns2
	read -r dns1 dns2 <<<"$(dns_pair)"

	{
		echo "port ${PORT}"
		if [[ -n "${OPENVPN_LISTEN_IP:-}" ]]; then
			echo "local ${OPENVPN_LISTEN_IP}"
		fi
		echo "proto ${PROTO}"
		echo "dev tun"
		echo "user nobody"
		echo "group nogroup"
		echo "persist-key"
		echo "persist-tun"
		echo "keepalive 10 120"
		echo "topology subnet"
		echo "server ${net} ${mask}"
		echo "ifconfig-pool-persist ipp.txt"
		if [[ "${OPENVPN_CLIENT_TO_CLIENT:-n}" == "y" ]]; then
			echo "client-to-client"
		fi
		if [[ "${OPENVPN_MULTI_CLIENT:-n}" == "y" ]]; then
			echo "duplicate-cn"
		fi
		if [[ "${OPENVPN_ROUTE_INTERNET:-y}" != "n" ]]; then
			echo 'push "redirect-gateway def1 bypass-dhcp"'
		fi
		if [[ -n "${OPENVPN_LOCAL_NETWORKS:-}" ]]; then
			local net_item
			IFS=',' read -ra nets <<<"${OPENVPN_LOCAL_NETWORKS}"
			for net_item in "${nets[@]}"; do
				net_item="$(echo "$net_item" | awk '{$1=$1; print}')"
				[[ -n "$net_item" ]] || continue
				echo "push \"route ${net_item%%/*} $(cidr_netmask "$net_item")\""
			done
		fi
		if [[ -n "${dns1:-}" ]]; then
			echo "push \"dhcp-option DNS ${dns1}\""
		fi
		if [[ -n "${dns2:-}" ]]; then
			echo "push \"dhcp-option DNS ${dns2}\""
		fi
		echo "client-config-dir ${CCD_DIR}"
		echo "ca ca.crt"
		echo "cert server.crt"
		echo "key server.key"
		echo "dh dh.pem"
		echo "tls-crypt tls-crypt.key"
		if [[ -f "${OPENVPN_DIR}/crl.pem" ]]; then
			echo "crl-verify crl.pem"
		fi
		echo "auth ${AUTH}"
		echo "cipher ${CIPHER}"
		echo "data-ciphers ${CIPHER}:AES-128-GCM"
		echo "status ${OPENVPN_STATUS_FILE:-${OPENVPN_DIR}/status.log}"
		echo "status-version 2"
		echo "verb 3"
		if [[ "$PROTO" == udp ]]; then
			echo "explicit-exit-notify 1"
		fi
	} >"$conf"
	log "Wrote ${conf}"
}

main() {
	mkdir -p "$OPENVPN_DIR" "$CCD_DIR" "$CLIENTS_DIR"
	ensure_easyrsa_tree
	init_pki
	copy_server_material
	ensure_tls_crypt
	write_client_template
	write_server_conf
	log "OpenVPN config ready under ${OPENVPN_DIR}"
}

main "$@"
