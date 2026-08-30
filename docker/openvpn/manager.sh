#!/usr/bin/env bash
# Stable client CLI for the Django UI and install.sh.
# Usage: manager.sh add|revoke|list|get-config|enable|disable <name>
set -euo pipefail

OPENVPN_DIR="${OPENVPN_DIR:-/etc/openvpn}"
EASYRSA_DIR="${EASYRSA_DIR:-${OPENVPN_DIR}/easy-rsa}"
CCD_DIR="${OPENVPN_CCD_DIR:-${OPENVPN_DIR}/ccd}"
CLIENTS_DIR="${OPENVPN_CLIENTS_DIR:-${OPENVPN_DIR}/clients}"
TEMPLATE="${OPENVPN_CLIENT_TEMPLATE:-${OPENVPN_DIR}/client-template.txt}"
EASYRSA_CERT_EXPIRE="${OPENVPN_CERT_EXPIRE:-${EASYRSA_CERT_EXPIRE:-825}}"
export EASYRSA_CERT_EXPIRE
PKI_DIR=""
EASYRSA_BIN=""
SERVER_CONF=""
INDEX_TXT=""

usage() {
	cat >&2 <<'EOF'
Usage: manager.sh <command> [name]

Commands:
  add <name>         Issue a client cert and write clients/<name>.ovpn
  revoke <name>      Revoke the cert, refresh CRL, remove profile
  list               Print "name<TAB>enabled|disabled" for valid clients
  get-config <name>  Write the .ovpn profile to stdout
  enable <name>      Remove CCD disable
  disable <name>     CCD-disable without revoking
EOF
	exit 2
}

log() { printf '%s\n' "$*"; }
die() { printf 'manager.sh: %s\n' "$*" >&2; exit 1; }

require_name() {
	local name="${1:-}"
	[[ -n "$name" ]] || die "client name required"
	# Same charset as openvpn-manager.sh / angristan. Account numbers in
	# models.py are unconstrained CharFields; existing CNs are [A-Za-z0-9_-].
	[[ "$name" =~ ^[a-zA-Z0-9_-]+$ ]] || die "invalid client name: ${name}"
	printf '%s' "$name"
}

first_existing_file() {
	local f
	for f in "$@"; do
		if [[ -f "$f" ]]; then
			printf '%s' "$f"
			return 0
		fi
	done
	return 1
}

first_existing_dir_with() {
	local needle="$1"
	shift
	local d
	for d in "$@"; do
		if [[ -f "${d}/${needle}" ]]; then
			printf '%s' "$d"
			return 0
		fi
	done
	return 1
}

discover_layout() {
	SERVER_CONF=""
	SERVER_CONF=$(first_existing_file \
		"${OPENVPN_DIR}/server.conf" \
		"${OPENVPN_DIR}/server/server.conf" \
		"${OPENVPN_DIR}/server/openvpn.conf" \
		"${OPENVPN_DIR}/openvpn.conf") || SERVER_CONF=""

	EASYRSA_BIN=""
	EASYRSA_BIN=$(first_existing_file \
		"${EASYRSA_DIR}/easyrsa" \
		"${OPENVPN_DIR}/easy-rsa/easyrsa" \
		"${OPENVPN_DIR}/server/easy-rsa/easyrsa" \
		/usr/share/easy-rsa/easyrsa) || EASYRSA_BIN=""

	PKI_DIR=""
	PKI_DIR=$(first_existing_dir_with index.txt \
		"${EASYRSA_DIR}/pki" \
		"${OPENVPN_DIR}/easy-rsa/pki" \
		"${OPENVPN_DIR}/server/easy-rsa/pki" \
		"${OPENVPN_DIR}/pki") || PKI_DIR=""

	if [[ -n "$PKI_DIR" ]]; then
		INDEX_TXT="${PKI_DIR}/index.txt"
	fi

	if [[ -z "${OPENVPN_CCD_DIR:-}" ]]; then
		if [[ -d "${OPENVPN_DIR}/server/ccd" && ! -d "${OPENVPN_DIR}/ccd" ]]; then
			CCD_DIR="${OPENVPN_DIR}/server/ccd"
		fi
	fi
	if [[ -z "${OPENVPN_CLIENTS_DIR:-}" ]]; then
		if [[ -d "${OPENVPN_DIR}/server/clients" && ! -d "${OPENVPN_DIR}/clients" ]]; then
			CLIENTS_DIR="${OPENVPN_DIR}/server/clients"
		fi
	fi

	local t=""
	t=$(first_existing_file \
		"$TEMPLATE" \
		"${OPENVPN_DIR}/client-template.txt" \
		"${OPENVPN_DIR}/server/client-template.txt") || t=""
	if [[ -n "$t" ]]; then
		TEMPLATE="$t"
	fi
}

find_tls_key() {
	first_existing_file \
		"${OPENVPN_DIR}/$1" \
		"${OPENVPN_DIR}/server/$1" \
		"${OPENVPN_DIR}/pki/$1"
}

require_pki() {
	discover_layout
	[[ -n "$PKI_DIR" && -f "$INDEX_TXT" ]] || die "Easy-RSA PKI not found under ${OPENVPN_DIR}"
	[[ -n "$EASYRSA_BIN" ]] || die "easyrsa not found (tried \$EASYRSA_DIR, server/easy-rsa, /usr/share/easy-rsa)"
	mkdir -p "$CCD_DIR" "$CLIENTS_DIR"
}

easyrsa() {
	local workdir
	workdir="$(dirname "$EASYRSA_BIN")"
	(cd "$workdir" && EASYRSA_BATCH=1 EASYRSA_PKI="$PKI_DIR" EASYRSA_CERT_EXPIRE="$EASYRSA_CERT_EXPIRE" "$EASYRSA_BIN" --batch "$@")
}

cn_in_index() {
	local name="$1"
	grep -E "/CN=${name}(/|$)" "$INDEX_TXT" >/dev/null 2>&1
}

client_is_valid() {
	local name="$1"
	grep "^V" "$INDEX_TXT" | grep -q -E "/CN=${name}(/|$)"
}

server_cn() {
	local f
	f="$(first_existing_file \
		"${EASYRSA_DIR}/SERVER_NAME_GENERATED" \
		"${OPENVPN_DIR}/easy-rsa/SERVER_NAME_GENERATED" \
		"${OPENVPN_DIR}/server/easy-rsa/SERVER_NAME_GENERATED")" || return 0
	cat "$f"
}

ccd_is_disabled() {
	local f="${CCD_DIR}/$1"
	[[ -f "$f" ]] || return 1
	grep -Eq '^[[:space:]]*(disable|--disable)([[:space:]]|$)' "$f"
}

# Check tls-crypt-v2 before tls-crypt (the latter is a prefix of the former).
tls_mode() {
	local conf="${SERVER_CONF:-}"
	if [[ -z "$conf" || ! -f "$conf" ]]; then
		if find_tls_key tls-crypt-v2.key >/dev/null; then
			printf 'crypt-v2'
			return 0
		fi
		if find_tls_key tls-crypt.key >/dev/null; then
			printf 'crypt'
			return 0
		fi
		if find_tls_key tls-auth.key >/dev/null || find_tls_key ta.key >/dev/null; then
			printf 'auth'
			return 0
		fi
		printf 'crypt'
		return 0
	fi
	if grep -Eqs '^[[:space:]]*tls-crypt-v2([[:space:]]|$)' "$conf"; then
		printf 'crypt-v2'
	elif grep -Eqs '^[[:space:]]*tls-crypt([[:space:]]|$)' "$conf"; then
		printf 'crypt'
	elif grep -Eqs '^[[:space:]]*tls-auth([[:space:]]|$)' "$conf"; then
		printf 'auth'
	else
		printf 'crypt'
	fi
}

apply_client_remote() {
	local ovpn="$1"
	local endpoint="${OPENVPN_ENDPOINT:-}"
	local port="${OPENVPN_CLIENT_PORT:-${OPENVPN_PORT:-}}"
	[[ -n "$endpoint" ]] || return 0
	[[ -f "$ovpn" ]] || return 0
	local new_remote="remote ${endpoint}"
	if [[ -n "$port" ]]; then
		new_remote="remote ${endpoint} ${port}"
	fi
	local tmp
	tmp="$(mktemp)"
	awk -v repl="$new_remote" '
		BEGIN { done=0 }
		/^remote / && !done { print repl; done=1; next }
		{ print }
	' "$ovpn" >"$tmp"
	mv "$tmp" "$ovpn"
}

generate_template() {
	local dest="$1"
	local proto port cipher auth endpoint conf
	proto="${OPENVPN_PROTO:-udp}"
	port="${OPENVPN_CLIENT_PORT:-${OPENVPN_PORT:-1194}}"
	endpoint="${OPENVPN_ENDPOINT:-}"
	cipher=""
	auth=""
	conf="${SERVER_CONF:-}"
	if [[ -n "$conf" && -f "$conf" ]]; then
		proto="$(awk '/^proto / { print $2; exit }' "$conf" || true)"
		proto="${proto:-udp}"
		local cfg_port
		cfg_port="$(awk '/^port / { print $2; exit }' "$conf" || true)"
		port="${OPENVPN_CLIENT_PORT:-${OPENVPN_PORT:-${cfg_port:-1194}}}"
		cipher="$(awk '/^cipher / { print $2; exit }' "$conf" || true)"
		auth="$(awk '/^auth / { print $2; exit }' "$conf" || true)"
	fi
	[[ -n "$endpoint" ]] || endpoint="CHANGE_ME"
	{
		echo "client"
		if [[ "$proto" == tcp* ]]; then
			echo "proto tcp-client"
		else
			echo "proto udp"
			echo "explicit-exit-notify"
		fi
		echo "remote ${endpoint} ${port}"
		echo "dev tun"
		echo "resolv-retry infinite"
		echo "nobind"
		echo "persist-key"
		echo "persist-tun"
		echo "remote-cert-tls server"
		[[ -n "$auth" ]] && echo "auth ${auth}"
		[[ -n "$cipher" ]] && echo "cipher ${cipher}"
		echo "verb 3"
	} >"$dest"
	log "Generated client template ${dest}"
}

ensure_template() {
	if [[ -f "$TEMPLATE" ]]; then
		return 0
	fi
	TEMPLATE="${OPENVPN_DIR}/client-template.txt"
	mkdir -p "$(dirname "$TEMPLATE")"
	generate_template "$TEMPLATE"
}

append_tls_block() {
	local mode
	mode="$(tls_mode)"
	case "$mode" in
	crypt-v2)
		local server_key client_key
		server_key="$(find_tls_key tls-crypt-v2.key)" || die "missing tls-crypt-v2.key (tried ${OPENVPN_DIR} and ${OPENVPN_DIR}/server)"
		client_key="$(mktemp "${OPENVPN_DIR}/tls-crypt-v2-client.XXXXXX")"
		if ! openvpn --tls-crypt-v2 "$server_key" --genkey tls-crypt-v2-client "$client_key"; then
			rm -f "$client_key"
			die "failed to generate tls-crypt-v2 client key"
		fi
		echo "<tls-crypt-v2>"
		cat "$client_key"
		echo "</tls-crypt-v2>"
		rm -f "$client_key"
		;;
	crypt)
		local crypt_key
		crypt_key="$(find_tls_key tls-crypt.key)" || die "missing tls-crypt.key (tried ${OPENVPN_DIR} and ${OPENVPN_DIR}/server)"
		echo "<tls-crypt>"
		cat "$crypt_key"
		echo "</tls-crypt>"
		;;
	auth)
		local auth_key=""
		auth_key="$(find_tls_key tls-auth.key || true)"
		if [[ -z "$auth_key" ]]; then
			auth_key="$(find_tls_key ta.key || true)"
		fi
		[[ -n "$auth_key" ]] || die "missing tls-auth.key / ta.key (tried ${OPENVPN_DIR}, ${OPENVPN_DIR}/server, ${OPENVPN_DIR}/pki)"
		echo "key-direction 1"
		echo "<tls-auth>"
		cat "$auth_key"
		echo "</tls-auth>"
		;;
	esac
}

write_ovpn() {
	local name="$1"
	local dest="${CLIENTS_DIR}/${name}.ovpn"
	ensure_template
	[[ -f "${PKI_DIR}/issued/${name}.crt" ]] || die "missing cert for ${name}"
	[[ -f "${PKI_DIR}/private/${name}.key" ]] || die "missing key for ${name}"
	[[ -f "${PKI_DIR}/ca.crt" ]] || die "missing CA cert in ${PKI_DIR}"

	cp "$TEMPLATE" "$dest"
	{
		echo "<ca>"
		cat "${PKI_DIR}/ca.crt"
		echo "</ca>"
		echo "<cert>"
		awk '/BEGIN/,/END CERTIFICATE/' "${PKI_DIR}/issued/${name}.crt"
		echo "</cert>"
		echo "<key>"
		cat "${PKI_DIR}/private/${name}.key"
		echo "</key>"
		append_tls_block
	} >>"$dest"
	apply_client_remote "$dest"
	chmod 600 "$dest"
	log "Wrote ${dest}"
}

cmd_add() {
	local name
	name="$(require_name "${1:-}")"
	require_pki
	if cn_in_index "$name"; then
		die "client CN already exists: ${name}"
	fi
	easyrsa build-client-full "$name" nopass
	write_ovpn "$name"
	rm -f "${CCD_DIR}/${name}"
	log "Client ${name} added."
}

cmd_revoke() {
	local name
	name="$(require_name "${1:-}")"
	require_pki
	client_is_valid "$name" || die "no valid client named ${name}"
	# Easy-RSA 3.2+ prefers revoke-issued; classic angristan uses revoke.
	if ! easyrsa revoke "$name" 2>/dev/null; then
		easyrsa revoke-issued "$name"
	fi
	EASYRSA_CRL_DAYS=3650 easyrsa gen-crl
	local crl_src="${PKI_DIR}/crl.pem"
	[[ -f "$crl_src" ]] || die "CRL not generated at ${crl_src}"
	local dest
	for dest in "${OPENVPN_DIR}/crl.pem" "${OPENVPN_DIR}/server/crl.pem"; do
		if [[ -d "$(dirname "$dest")" ]]; then
			rm -f "$dest"
			cp "$crl_src" "$dest"
			chmod 644 "$dest"
		fi
	done
	rm -f "${CLIENTS_DIR}/${name}.ovpn" "/root/${name}.ovpn"
	rm -f "${CCD_DIR}/${name}"
	local ipp
	for ipp in "${OPENVPN_DIR}/ipp.txt" "${OPENVPN_DIR}/server/ipp.txt"; do
		if [[ -f "$ipp" ]]; then
			sed -i "/^${name},/d" "$ipp"
		fi
	done
	log "Certificate for client ${name} revoked."
}

cmd_list() {
	require_pki
	local skip
	skip="$(server_cn || true)"
	local line cn status
	while IFS= read -r line; do
		[[ "$line" == V* ]] || continue
		cn="${line##*/CN=}"
		cn="${cn%%/*}"
		[[ -n "$cn" ]] || continue
		[[ -n "$skip" && "$cn" == "$skip" ]] && continue
		status="enabled"
		if ccd_is_disabled "$cn"; then
			status="disabled"
		fi
		printf '%s\t%s\n' "$cn" "$status"
	done <"$INDEX_TXT"
}

cmd_get_config() {
	local name
	name="$(require_name "${1:-}")"
	require_pki
	client_is_valid "$name" || die "no valid client named ${name}"
	if [[ ! -f "${CLIENTS_DIR}/${name}.ovpn" ]]; then
		write_ovpn "$name" >/dev/null
	else
		apply_client_remote "${CLIENTS_DIR}/${name}.ovpn"
	fi
	cat "${CLIENTS_DIR}/${name}.ovpn"
}

cmd_enable() {
	local name
	name="$(require_name "${1:-}")"
	require_pki
	client_is_valid "$name" || die "no valid client named ${name}"
	rm -f "${CCD_DIR}/${name}"
	log "Client ${name} enabled."
}

cmd_disable() {
	local name
	name="$(require_name "${1:-}")"
	require_pki
	client_is_valid "$name" || die "no valid client named ${name}"
	printf 'disable\n' >"${CCD_DIR}/${name}"
	log "Client ${name} disabled."
}

main() {
	local cmd="${1:-}"
	shift || true
	case "$cmd" in
	add) cmd_add "${1:-}" ;;
	revoke) cmd_revoke "${1:-}" ;;
	list) cmd_list ;;
	get-config) cmd_get_config "${1:-}" ;;
	enable) cmd_enable "${1:-}" ;;
	disable) cmd_disable "${1:-}" ;;
	-h | --help | help | "") usage ;;
	*) die "unknown command: ${cmd}" ;;
	esac
}

main "$@"
