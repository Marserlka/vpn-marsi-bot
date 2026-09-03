"""Minimal HTTP agent that lets the Telegram bot manage AmneziaWG peers on
this VPS. AmneziaWG has no REST API of its own, so this is the sidecar the
bot talks to instead — Marzban's equivalent would be its own admin API, but
Marzban has no native WireGuard support (see TZ 3.2 for why AmneziaWG became
the primary protocol).

Deploy: copy to /opt/awg_agent.py on the VPS and run under systemd (see
`awg-agent.service` example in README.md). Runs on 0.0.0.0:9443 with TLS
(reuse the same cert as the panel) and a bearer-token auth check.

Endpoints:
  GET    /health             liveness check
  POST   /peers               {"label": "<subscription id>"} -> creates a peer,
                               returns {"public_key", "ip", "client_config"}
  DELETE /peers/<pubkey>       removes a peer

Required environment variables:
  AWG_AGENT_TOKEN     bearer token clients must send in Authorization header
  AWG_SERVER_ENDPOINT host:port clients connect to, e.g. "1.2.3.4:443"
  AWG_SERVER_PUBLIC_KEY server's AmneziaWG public key (from `awg show awg0`)
  AWG_TLS_CERTFILE    path to the fullchain.pem used for this agent's HTTPS
  AWG_TLS_KEYFILE     path to the matching private key
Optional:
  AWG_CONF_DIR (default /etc/amnezia/amneziawg)
  AWG_INTERFACE (default awg0)
  AWG_SUBNET (default 10.29.29.0/24)
  AWG_BIN (default /usr/local/bin/awg)
"""
from __future__ import annotations

import http.server
import ipaddress
import json
import os
import ssl
import subprocess
import threading

AWG_DIR = os.environ.get("AWG_CONF_DIR", "/etc/amnezia/amneziawg")
CONF_FILE = os.path.join(AWG_DIR, "awg0.conf")
STATE_FILE = os.path.join(AWG_DIR, "peers.json")
INTERFACE = os.environ.get("AWG_INTERFACE", "awg0")
SUBNET = ipaddress.ip_network(os.environ.get("AWG_SUBNET", "10.29.29.0/24"))
SERVER_ADDR = str(next(SUBNET.hosts()))
SERVER_ENDPOINT = os.environ["AWG_SERVER_ENDPOINT"]
SERVER_PUBLIC_KEY = os.environ["AWG_SERVER_PUBLIC_KEY"]
AWG_BIN = os.environ.get("AWG_BIN", "/usr/local/bin/awg")
TOKEN = os.environ["AWG_AGENT_TOKEN"]
CERT_FILE = os.environ["AWG_TLS_CERTFILE"]
KEY_FILE = os.environ["AWG_TLS_KEYFILE"]

_lock = threading.Lock()


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"peers": {}}
    with open(STATE_FILE) as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _next_free_ip(state: dict) -> str:
    used = {v["ip"] for v in state["peers"].values()} | {SERVER_ADDR}
    for host in SUBNET.hosts():
        if str(host) not in used:
            return str(host)
    raise RuntimeError("address pool exhausted")


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def create_peer(label: str) -> dict:
    with _lock:
        state = _load_state()
        priv = _run([AWG_BIN, "genkey"])
        pub = subprocess.run(
            [AWG_BIN, "pubkey"], input=priv, capture_output=True, text=True, check=True
        ).stdout.strip()
        ip = _next_free_ip(state)

        _run([AWG_BIN, "set", INTERFACE, "peer", pub, "allowed-ips", f"{ip}/32"])

        state["peers"][pub] = {"label": label, "ip": ip}
        _save_state(state)
        _persist_conf(state)

        client_config = (
            "[Interface]\n"
            f"Address = {ip}/24\n"
            "DNS = 1.1.1.1, 8.8.8.8\n"
            f"PrivateKey = {priv}\n"
            "Jc = 4\nJmin = 40\nJmax = 70\nS1 = 68\nS2 = 88\n"
            "H1 = 1234567\nH2 = 2345678\nH3 = 3456789\nH4 = 4567890\n\n"
            "[Peer]\n"
            f"PublicKey = {SERVER_PUBLIC_KEY}\n"
            f"Endpoint = {SERVER_ENDPOINT}\n"
            "AllowedIPs = 0.0.0.0/0, ::/0\n"
            "PersistentKeepalive = 25\n"
        )
        return {"public_key": pub, "ip": ip, "client_config": client_config}


def delete_peer(pubkey: str) -> bool:
    with _lock:
        state = _load_state()
        if pubkey not in state["peers"]:
            return False
        subprocess.run([AWG_BIN, "set", INTERFACE, "peer", pubkey, "remove"], check=False)
        del state["peers"][pubkey]
        _save_state(state)
        _persist_conf(state)
        return True


def _persist_conf(state: dict) -> None:
    """Rewrite awg0.conf's [Peer] blocks so peers survive a server reboot."""
    with open(CONF_FILE) as f:
        content = f.read()
    header = content.split("[Peer]")[0].rstrip() + "\n"
    blocks = [header]
    for pub, info in state["peers"].items():
        blocks.append(f"\n[Peer]\nPublicKey = {pub}\nAllowedIPs = {info['ip']}/32\n")
    with open(CONF_FILE, "w") as f:
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
            result = create_peer(data.get("label", ""))
            self._json(201, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def do_DELETE(self) -> None:
        if not self._auth_ok():
            self._json(401, {"error": "unauthorized"})
            return
        prefix = "/peers/"
        if not self.path.startswith(prefix):
            self._json(404, {"error": "not found"})
            return
        pubkey = self.path[len(prefix):]
        try:
            ok = delete_peer(pubkey)
            self._json(200 if ok else 404, {"deleted": ok})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def log_message(self, format, *args):
        pass


def main() -> None:
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 9443), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
