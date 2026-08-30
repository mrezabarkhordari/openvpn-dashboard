# Local OpenVPN options (not upstream angristan)

Pinned upstream: [angristan/openvpn-install](https://github.com/angristan/openvpn-install)
`ad22fd9eb0c8569a885f836ef6e37576d8702e9f` (fetched by `vpn/fetch-angristan.sh`).

We do **not** keep a private fork of the installer. Behavior that the old
`openvpn-manager.sh` / `start.sh` added on top of angristan lives in
`vpn/manager.sh` and `vpn/entrypoint.sh`.

## Diff vs pinned angristan (this repo)

The historical `openvpn-manager.sh` is angristan plus these extras:

| Local addition | Upstream menu | Where we keep it |
|----------------|---------------|------------------|
| `listClient` | not present | `manager.sh list` |
| `disableClient` (CCD file) | not present | `manager.sh enable` / `disable` |
| `revokeClientCN` (revoke by name) | interactive number only | `manager.sh revoke <name>` |
| Django `MENU_OPTION=1` + `CLIENT` + `PASS=1` | interactive `newClient` | `manager.sh add <name>` |
| Django `MENU_OPTION=4` + `CLIENTCN` | n/a | `manager.sh revoke <name>` |
| Inline `.ovpn` left in `/root` | same | write `clients/<name>.ovpn` |
| `remote` rewrite to a public host:port | uses `ENDPOINT` | `OPENVPN_ENDPOINT` + `OPENVPN_CLIENT_PORT` |
| `start.sh` first-boot + `exec`/daemon openvpn | `systemctl start` | entrypoint skips systemd, `exec openvpn` |
| Always-on status log | `status` in server.conf only | CLI `--status` + `--status-version 2` |
| Management interface | not in local script | CLI `--management 127.0.0.1:$PORT` |

CCD disable: local files used the line `--disable`. OpenVPN’s CCD directive is
`disable`. `manager.sh` writes `disable` and treats either line as disabled so
existing CCD files still work.

## Container (no systemd)

Angristan enables `openvpn-server@server` and `iptables-openvpn` via systemd. The VPN
image has no systemd.

- First boot (no `server.conf` / `server/server.conf` / `openvpn.conf`):
  pinned angristan CLI `openvpn-install.sh install [flags]` (AUTO_INSTALL is
  gone on `ad22fd9`). A `systemctl` stub plus a dummy unit file keep the
  installer from fataling. Older AUTO_INSTALL snapshots still work if present.
- Every boot: enable `ip_forward`, apply MASQUERADE, `exec openvpn`.
- Always inject `--client-config-dir $OPENVPN_DIR/ccd` (and rewrite the
  matching server.conf line) so `manager.sh enable|disable` works.
- Do not rely on unit files written by the installer.

## Always-on status and management

CLI flags override `server.conf`:

| Flag | Default | Purpose |
|------|---------|---------|
| `--status` | `$OPENVPN_STATUS_FILE` every `$OPENVPN_STATUS_INTERVAL` s | UI / metrics |
| `--status-version` | `2` | parseable `CLIENT_LIST` rows |
| `--management` | `127.0.0.1:$OPENVPN_MGMT_PORT` | loopback only; do not publish |

## Data layout (`OPENVPN_DATA_DIR`)

Host path (default `./data/openvpn`) is mounted at `/etc/openvpn`.

| Path | Role |
|------|------|
| `server.conf` | Written by angristan |
| `easy-rsa/` | PKI (`pki/issued`, `pki/index.txt`, CRL) |
| `ccd/` | Per-client config; `disable` = disabled |
| `clients/<name>.ovpn` | Unified profiles for Django download |
| `status.log` | `--status` output |
| `client-template.txt` | Base client config |
| `.installed` | Marker after a successful first-boot install |

## `manager.sh` contract

```text
manager.sh add|revoke|list|get-config|enable|disable <name>
```

Easy-RSA and CCD only. The UI must not re-implement PKI.

## New angristan CLI flags (passed from `.env` on first boot)

`entrypoint.sh` runs `openvpn-install.sh --no-color --no-log install …`
(global flags must come before `install`). Optional knobs:

`--endpoint`, `--ip`, `--port`, `--protocol`, `--dns` / `--dns-primary`,
`--subnet-ipv4`, `--client-ipv6` / `--no-client-ipv6`, `--client-to-client`,
`--route-internet`, `--tls-sig`, `--cipher`, `--auth-mode`, `--multi-client`,
`--local-network`.

## Networking

`NET_ADMIN`, `/dev/net/tun`, published `$OPENVPN_PORT/$OPENVPN_PROTO`, and
iptables MASQUERADE for `$OPENVPN_SUBNET`. `IP_FORWARD` is set in the entrypoint.
