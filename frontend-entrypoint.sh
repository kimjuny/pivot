#!/bin/sh
set -eu

# Derive the container runtime's DNS server from our own /etc/resolv.conf.
# nginx requires an explicit `resolver` to look up the backend hostname at
# request time (lazy resolution via the `set $upstream` + `proxy_pass $upstream`
# pattern), but the DNS address differs by runtime: Docker embeds 127.0.0.11,
# Podman uses the podman bridge gateway (e.g. 10.89.0.1). Reading it from
# resolv.conf makes the same image portable across both. Falls back to a public
# resolver only if resolv.conf has no nameserver entry.
dns="$(awk '/^nameserver[[:space:]]/ {print $2; exit}' /etc/resolv.conf)"
dns="${dns:-1.1.1.1}"
sed "s|__RESOLVER__|${dns}|" /etc/nginx/default.conf.tmpl > /etc/nginx/conf.d/default.conf

exec "$@"
