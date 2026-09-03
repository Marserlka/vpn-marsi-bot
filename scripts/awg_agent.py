"""Minimal HTTP agent that lets the Telegram bot manage VPN peers on this
VPS, for both protocols we offer: AmneziaWG (obfuscated, default) and plain
WireGuard (native kernel module, faster, no obfuscation — see TZ 3.3 for why
we added it: AmneziaWG's junk-packet framing plus running as a userspace
daemon on this VPS's single vCPU made throughput "неприлично низкие" for at
least one user; plain WireGuard runs in-kernel and has none of that
overhead). Neither protocol has a REST API of its own, so this is the
sidecar the bot talks to instead.

Deploy: copy to /opt/awg_agent.py on the VPS and run under systemd (see
`awg-agent.service` example in README.md). Runs on 0.0.0.0:443 by default
(AWG_AGENT_PORT to override) with TLS (reuse the same cert as the panel)
and a bearer-token auth check. Port 443 is deliberate: some bot hosts
(BotHost included) block outbound connections to non-standard ports, and
443 is the one port that's essentially always allowed through — the
symptom is an httpx.ConnectTimeout from the bot with the agent otherwise
healthy (see TZ 3.2 "Урок №3").

The AmneziaWG obfuscation parameters (Jc/Jmin/Jmax/S1/S2/H1-H4, plus MTU
and PresharedKey) must exactly match the server interface's own awg0.conf —
see TZ 3.2's postmortem on the Windows-client connectivity issue this fixed.
If you change the server's [Interface] block, update PROTOCOLS below too
and reissue every peer of that protocol (existing configs will stop
matching otherwise).

Endpoints:
  GET    /health             liveness check
  POST   /peers               {"label": "<subscription id>", "protocol": "amnezia"|"wireguard"}
                               -> creates a peer, returns
                               {"public_key", "ip", "client_config"}
  DELETE /peers/<pubkey>?protocol=amnezia|wireguard   removes a peer

Required environment variables:
  AWG_AGENT_TOKEN          bearer token clients must send in Authorization header
  AWG_SERVER_ENDPOINT      host:port for AmneziaWG clients, e.g. "1.2.3.4:51820"
  AWG_SERVER_PUBLIC_KEY    server's AmneziaWG public key (from `awg show awg0`)
  WG_SERVER_ENDPOINT       host:port for plain WireGuard clients, e.g. "1.2.3.4:51821"
  WG_SERVER_PUBLIC_KEY     server's WireGuard public key (from `wg show wg0`)
  AWG_TLS_CERTFILE         path to the fullchain.pem used for this agent's HTTPS
  AWG_TLS_KEYFILE          path to the matching private key
Optional:
  AWG_CONF_DIR (default /etc/amnezia/amneziawg)
  AWG_INTERFACE (default awg0)
  AWG_SUBNET (default 10.29.29.0/24)
  AWG_BIN (default /usr/local/bin/awg)
  WG_CONF_DIR (default /etc/wireguard)
  WG_INTERFACE (default wg0)
  WG_SUBNET (default 10.29.31.0/24)
  WG_BIN (default /usr/bin/wg)
"""
from __future__ import annotations

import http.server
import ipaddress
import json
import os
import ssl
import subprocess
import threading
from urllib.parse import urlparse, parse_qs

TOKEN = os.environ["AWG_AGENT_TOKEN"]
CERT_FILE = os.environ["AWG_TLS_CERTFILE"]
KEY_FILE = os.environ["AWG_TLS_KEYFILE"]

# Must mirror the [Interface] block in awg0.conf exactly. Note: S3/S4 and
# H1-H4-as-a-range are a newer AmneziaWG protocol addition that some client
# app builds don't understand yet — one such client rejected S3 outright
# ("Неверный ключ для секции [Interface]: s3") even though our server-side
# tools support it. Stick to the widely-supported subset: MTU, PresharedKey
# (set per-peer below), Jc/Jmin/Jmax/S1/S2, and single-value H1-H4.
AMNEZIA_CLIENT_PARAMS = (
    "MTU = 1280\n"
    "Jc = 9\nJmin = 30\nJmax = 90\nS1 = 110\nS2 = 120\n"
    "H1 = 5000000\nH2 = 10000001\nH3 = 20000001\nH4 = 30000001\n"
)

PROTOCOLS = {
    "amnezia": {
        "dir": os.environ.get("AWG_CONF_DIR", "/etc/amnezia/amneziawg"),
        "conf_name": "awg0.conf",
        "state_name": "peers.json",
        "interface": os.environ.get("AWG_INTERFACE", "awg0"),
        "subnet": ipaddress.ip_network(os.environ.get("AWG_SUBNET", "10.29.29.0/24")),
        "bin": os.environ.get("AWG_BIN", "/usr/local/bin/awg"),
        "endpoint": os.environ["AWG_SERVER_ENDPOINT"],
        "server_public_key": os.environ["AWG_SERVER_PUBLIC_KEY"],
        "client_params": AMNEZIA_CLIENT_PARAMS,
    },
    "wireguard": {
        "dir": os.environ.get("WG_CONF_DIR", "/etc/wireguard"),
        "conf_name": "wg0.conf",
        "state_name": "peers.json",
        "interface": os.environ.get("WG_INTERFACE", "wg0"),
        "subnet": ipaddress.ip_network(os.environ.get("WG_SUBNET", "10.29.31.0/24")),
        "bin": os.environ.get("WG_BIN", "/usr/bin/wg"),
        "endpoint": os.environ["WG_SERVER_ENDPOINT"],
        "server_public_key": os.environ["WG_SERVER_PUBLIC_KEY"],
        "client_params": "",
    },
}

_lock = threading.Lock()


def _conf_file(p: dict) -> str:
    return os.path.join(p["dir"], p["conf_name"])


def _state_file(p: dict) -> str:
    return os.path.join(p["dir"], p["state_name"])


def _server_addr(p: dict) -> str:
    return str(next(p["subnet"].hosts()))


def _load_state(p: dict) -> dict:
    path = _state_file(p)
    if not os.path.exists(path):
        return {"peers": {}}
    with open(path) as f:
        return json.load(f)


def _save_state(p: dict, state: dict) -> None:
    with open(_state_file(p), "w") as f:
        json.dump(state, f, indent=2)


def _next_free_ip(p: dict, state: dict) -> str:
    used = {v["ip"] for v in state["peers"].values()} | {_server_addr(p)}
    for host in p["subnet"].hosts():
        if str(host) not in used:
            return str(host)
    raise RuntimeError("address pool exhausted")


def _run(cmd: list[str], input_data: str | None = None) -> str:
    result = subprocess.run(cmd, input=input_data, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def create_peer(label: str, protocol: str) -> dict:
    if protocol not in PROTOCOLS:
        raise ValueError(f"unknown protocol: {protocol}")
    p = PROTOCOLS[protocol]
    with _lock:
        state = _load_state(p)
        priv = _run([p["bin"], "genkey"])
        pub = _run([p["bin"], "pubkey"], input_data=priv)
        psk = _run([p["bin"], "genpsk"])
        ip = _next_free_ip(p, state)

        _run([
            p["bin"], "set", p["interface"], "peer", pub,
            "preshared-key", "/dev/stdin", "allowed-ips", f"{ip}/32",
        ], input_data=psk)

        state["peers"][pub] = {"label": label, "ip": ip, "psk": psk}
        _save_state(p, state)
        _persist_conf(p, state)

        client_config = (
            "[Interface]\n"
            f"Address = {ip}/24\n"
            "DNS = 1.1.1.1, 8.8.8.8\n"
            f"PrivateKey = {priv}\n"
            f"{p['client_params']}\n"
            "[Peer]\n"
            f"PublicKey = {p['server_public_key']}\n"
            f"PresharedKey = {psk}\n"
            f"Endpoint = {p['endpoint']}\n"
            "AllowedIPs = 0.0.0.0/0, ::/0\n"
            "PersistentKeepalive = 25\n"
        )
        return {"public_key": pub, "ip": ip, "client_config": client_config}


def delete_peer(pubkey: str, protocol: str) -> bool:
    if protocol not in PROTOCOLS:
        raise ValueError(f"unknown protocol: {protocol}")
    p = PROTOCOLS[protocol]
    with _lock:
        state = _load_state(p)
        if pubkey not in state["peers"]:
            return False
        subprocess.run([p["bin"], "set", p["interface"], "peer", pubkey, "remove"], check=False)
        del state["peers"][pubkey]
        _save_state(p, state)
        _persist_conf(p, state)
        return True


def _persist_conf(p: dict, state: dict) -> None:
    """Rewrite the interface's conf file's [Peer] blocks so peers survive a reboot."""
    conf_file = _conf_file(p)
    with open(conf_file) as f:
        content = f.read()
    header = content.split("[Peer]")[0].rstrip() + "\n"
    blocks = [header]
    for pub, info in state["peers"].items():
        psk_line = f"PresharedKey = {info['psk']}\n" if info.get("psk") else ""
        blocks.append(f"\n[Peer]\nPublicKey = {pub}\n{psk_line}AllowedIPs = {info['ip']}/32\n")
    with open(conf_file, "w") as f:
        f.write("".join(blocks))


class Handler(http.server.BaseHTTPRequestHandler):
    def _auth_ok(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._auth_ok():
            self._json(401, {"error": "unauthorized"})
            return
        if self.path != "/peers":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        try:
            result = create_peer(data.get("label", ""), data.get("protocol", "amnezia"))
            self._json(201, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def do_DELETE(self) -> None:
        if not self._auth_ok():
            self._json(401, {"error": "unauthorized"})
            return
        parsed = urlparse(self.path)
        prefix = "/peers/"
        if not parsed.path.startswith(prefix):
            self._json(404, {"error": "not found"})
            return
        pubkey = parsed.path[len(prefix):]
        protocol = parse_qs(parsed.query).get("protocol", ["amnezia"])[0]
        try:
            ok = delete_peer(pubkey, protocol)
            self._json(200 if ok else 404, {"deleted": ok})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def log_message(self, format, *args):
        pass


def main() -> None:
    port = int(os.environ.get("AWG_AGENT_PORT", "443"))
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
