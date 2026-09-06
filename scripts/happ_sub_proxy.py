"""Tiny HTTPS reverse-proxy in front of Marzban's own subscription endpoint
that adds an HTTP `routing` header carrying a Happ routing-profile deeplink
(happ://routing/onadd/<base64 JSON>) — see the Happ dev docs
(happ.su/main/dev-docs/routing): a subscription can bundle a routing
profile either via this header or in the body text, and Happ applies it
automatically the moment the subscription is added, same as a competitor's
bot does (see TZ 2026-09-06).

Marzban itself has no way to add custom response headers to its
subscription responses, hence this — deploy one instance per Marzban VPS
(Germany and Netherlands both need their own, each proxying its own local
Marzban on 127.0.0.1:8000).

Deploy: copy to /opt/happ_sub_proxy.py, run under systemd (mirrors
awg-agent.service — see README.md), reusing the same TLS cert Marzban's
panel already has for this box's sslip.io domain.

Required environment variables:
  HAPP_PROXY_TLS_CERTFILE   path to fullchain.pem
  HAPP_PROXY_TLS_KEYFILE    path to matching private key
Optional:
  HAPP_PROXY_PORT (default 8449)
  MARZBAN_LOCAL_BASE_URL (default https://127.0.0.1:8000 — Marzban's own
                          panel, reached over loopback so its self-signed/
                          real cert doesn't matter, verification is skipped)
"""
from __future__ import annotations

import http.server
import os
import ssl
import urllib.error
import urllib.request

PORT = int(os.environ.get("HAPP_PROXY_PORT", "8449"))
CERT_FILE = os.environ["HAPP_PROXY_TLS_CERTFILE"]
KEY_FILE = os.environ["HAPP_PROXY_TLS_KEYFILE"]
MARZBAN_LOCAL_BASE_URL = os.environ.get("MARZBAN_LOCAL_BASE_URL", "https://127.0.0.1:8000")

# Precomputed happ://routing/onadd/<base64> for the MarsiVPN routing profile
# (DNS over HTTPS instead of the default DNS-over-TLS-on-853, which is what
# was actually breaking browsing in NekoBox/Happ — see TZ 2026-09-06).
# Regenerate by re-running the one-off script that built this if the
# profile ever needs to change; there's no need to keep the JSON source in
# this file, the deeplink is the only thing that matters at request time.
ROUTING_DEEPLINK = (
    "happ://routing/onadd/eyJOYW1lIjoiTWFyc2lWUE4iLCJHbG9iYWxQcm94eSI6dHJ1ZSwiUmVtb3RlRE5TVHlwZSI6IkRvSCIsIl"
    "JlbW90ZUROU0RvbWFpbiI6Imh0dHBzOi8vY2xvdWRmbGFyZS1kbnMuY29tL2Rucy1xdWVyeSIsIlJlbW90ZUROU0lQIjoiMS4xLjEu"
    "MSIsIkRvbWVzdGljRE5TVHlwZSI6IkRvSCIsIkRvbWVzdGljRE5TRG9tYWluIjoiaHR0cHM6Ly9kbnMuZ29vZ2xlL2Rucy1xdWVyeS"
    "IsIkRvbWVzdGljRE5TSVAiOiI4LjguOC44IiwiRG9tYWluU3RyYXRlZ3kiOiJJUElmTm9uTWF0Y2giLCJGYWtlRE5TIjpmYWxzZSwi"
    "R2VvaXB1cmwiOiJodHRwczovL2dpdGh1Yi5jb20vTG95YWxzb2xkaWVyL3YycmF5LXJ1bGVzLWRhdC9yZWxlYXNlcy9sYXRlc3QvZG"
    "93bmxvYWQvZ2VvaXAuZGF0IiwiR2Vvc2l0ZXVybCI6Imh0dHBzOi8vZ2l0aHViLmNvbS9Mb3lhbHNvbGRpZXIvdjJyYXktcnVsZXMt"
    "ZGF0L3JlbGVhc2VzL2xhdGVzdC9kb3dubG9hZC9nZW9zaXRlLmRhdCJ9"
)

_UNSAFE_CTX = ssl.create_default_context()
_UNSAFE_CTX.check_hostname = False
_UNSAFE_CTX.verify_mode = ssl.CERT_NONE


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, b'{"status":"ok"}', {"Content-Type": "application/json"})
            return
        upstream = f"{MARZBAN_LOCAL_BASE_URL}{self.path}"
        try:
            req = urllib.request.Request(upstream, headers={"User-Agent": self.headers.get("User-Agent", "")})
            with urllib.request.urlopen(req, timeout=10, context=_UNSAFE_CTX) as resp:
                body = resp.read()
                headers = {
                    k: v for k, v in resp.getheaders()
                    if k.lower() not in ("connection", "transfer-encoding", "content-length")
                }
                headers["routing"] = ROUTING_DEEPLINK
                self._send(resp.status, body, headers)
        except urllib.error.HTTPError as exc:
            self._send(exc.code, exc.read())
        except Exception as exc:
            self._send(502, str(exc).encode())

    def _send(self, code: int, body: bytes, headers: dict | None = None) -> None:
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class TLSServer(http.server.ThreadingHTTPServer):
    """Wraps each *accepted connection* in TLS, not the listening socket —
    see awg_agent.py's TLSServer docstring for why (a single stalled
    handshake on the listening socket wedges the entire accept loop)."""

    def __init__(self, *args, ssl_context: ssl.SSLContext, **kwargs):
        self._ssl_context = ssl_context
        super().__init__(*args, **kwargs)

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(10.0)
        wrapped = self._ssl_context.wrap_socket(sock, server_side=True)
        wrapped.settimeout(None)
        return wrapped, addr


def main() -> None:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    server = TLSServer(("0.0.0.0", PORT), Handler, ssl_context=ctx)
    print(f"happ_sub_proxy listening on :{PORT}, upstream {MARZBAN_LOCAL_BASE_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
