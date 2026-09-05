from __future__ import annotations

import asyncio
import ipaddress
import socket

# Cloudflare's published IPv4 ranges (cloudflare.com/ips-v4) — hardcoded
# snapshot since fetching it live isn't worth a network call for something
# that changes maybe once a year; update from the published list if a real
# domain's resolved IP stops matching any of these unexpectedly.
CLOUDFLARE_IPV4_RANGES = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
]
_CF_NETWORKS = [ipaddress.ip_network(cidr) for cidr in CLOUDFLARE_IPV4_RANGES]


def is_cloudflare_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _CF_NETWORKS)


async def resolve_domain(domain: str) -> list[str]:
    """Blocking getaddrinfo off the event loop — returns unique IPv4/IPv6
    addresses the domain currently resolves to, or [] if it doesn't resolve
    at all (NXDOMAIN, DNS not propagated yet, typo, etc.)."""
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, domain, None)
    except socket.gaierror:
        return []
    seen: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in seen:
            seen.append(ip)
    return seen


async def check_cdn_readiness(domain: str) -> str:
    """Human-readable readiness summary for the /test lab — resolves the
    domain and reports whether it's actually proxied through Cloudflare
    (resolved IP falls in a published Cloudflare range) rather than
    pointing straight at the origin VPS (which would defeat the whole
    point — DPI would just see the VPS's own IP again)."""
    ips = await resolve_domain(domain)
    if not ips:
        return f"❌ {domain} не резолвится — DNS ещё не применился или домен не привязан к Cloudflare."

    cf_ips = [ip for ip in ips if is_cloudflare_ip(ip)]
    lines = [f"IP: {', '.join(ips)}"]
    if cf_ips:
        lines.append("✅ Проксируется через Cloudflare (оранжевое облако) — готово к настройке Xray-инбаунда.")
    else:
        lines.append(
            "⚠️ Резолвится напрямую, не через Cloudflare — проверь, что запись в DNS-панели CF "
            "помечена как Proxied (оранжевое облако), а не DNS only (серое)."
        )
    return "\n".join(lines)
