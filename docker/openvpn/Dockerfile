FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        openvpn \
        easy-rsa \
        iptables \
        iproute2 \
        openssl \
        ca-certificates \
        curl \
        wget \
        procps \
        bash \
        dnsutils \
        socat \
        tar \
        iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/vpn

COPY fetch-angristan.sh manager.sh entrypoint.sh generate-config.sh /opt/vpn/

# Vendored, pinned angristan script (reference / optional tooling only).
# PKI is NOT generated here — it is created at first boot on the data volume.
RUN chmod +x /opt/vpn/fetch-angristan.sh /opt/vpn/manager.sh \
        /opt/vpn/entrypoint.sh /opt/vpn/generate-config.sh \
    && /opt/vpn/fetch-angristan.sh

RUN openvpn --version && which easyrsa || ls /usr/share/easy-rsa

ENV OPENVPN_DIR=/etc/openvpn \
    EASYRSA_BATCH=1 \
    PATH="/opt/vpn:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

VOLUME ["/etc/openvpn"]

ENTRYPOINT ["/opt/vpn/entrypoint.sh"]
