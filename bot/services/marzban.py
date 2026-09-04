from __future__ import annotations

import datetime as dt
import logging
import time

import httpx

from bot.config import settings

logger = logging.getLogger("bot.marzban")


class MarzbanError(Exception):
    pass


class MarzbanClient:
    """Thin async wrapper around the Marzban REST API.

    KNOWN GAP: checked the deployed panel's UserCreate schema (03.09.2026,
    Marzban `gozargah/marzban:latest`) — it has no per-user IP/device-count
    field at all (no `ips_limit`, no `limit_ip`). Unlike AmneziaWG/WireGuard,
    where the 1-device rule falls out of the protocol itself (see TZ 3.1),
    VLESS/Shadowsocks users created here are NOT limited to one device by
    Marzban. If this needs enforcing, it'll have to be a separate mechanism
    (e.g. parsing Xray's access log for concurrent client IPs) — out of
    scope for the initial VLESS/SS rollout.
    """

    def __init__(self) -> None:
        self._base_url = settings.MARZBAN_BASE_URL.rstrip("/")
        self._username = settings.MARZBAN_ADMIN_USERNAME
        self._password = settings.MARZBAN_ADMIN_PASSWORD
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=15.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def _authenticate(self) -> str:
        if not self._base_url:
            raise MarzbanError("MARZBAN_BASE_URL is not configured")
        resp = await self._client.post(
            "/api/admin/token",
            data={"username": self._username, "password": self._password},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Marzban tokens are typically long-lived; refresh conservatively every hour.
        self._token_expires_at = time.monotonic() + 3600
        return self._token

    async def _headers(self) -> dict:
        if not self._token or time.monotonic() >= self._token_expires_at:
            await self._authenticate()
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = await self._headers()
        resp = await self._client.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 401:
            # token expired mid-flight, retry once
            await self._authenticate()
            headers = await self._headers()
            resp = await self._client.request(method, path, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp

    async def create_user(self, username: str, expire_at: dt.datetime, protocol: str = "vless") -> dict:
        """protocol is "vless" (Reality over plain tcp) or "ss" (Shadowsocks).

        VLESS-Reality briefly used the xhttp transport (see TZ 3.4) but that
        was reverted (TZ 3.6) — several real client apps/cores (sing-box,
        and even a build labelled "Xray TUN") failed to route traffic over
        it correctly despite our own server-side Xray handling it fine in
        every test. Plain tcp is what every VLESS client supports without
        exception, so that's what we use, paired with the standard
        xtls-rprx-vision flow (a tcp-transport-only optimization — do not
        set this if xhttp ever comes back).

        Shadowsocks cipher is aes-256-gcm, not the more commonly-default
        chacha20-ietf-poly1305 — this VPS's CPU has AES-NI (confirmed via
        the aesni_intel kernel module), and ChaCha20 exists specifically to
        be fast in software *without* hardware AES acceleration, so it's
        the wrong choice here. WireGuard/AmneziaWG aren't affected by this —
        their cipher is fixed to ChaCha20-Poly1305 by the protocol itself.
        """
        if protocol == "ss":
            proxies = {"shadowsocks": {"method": "aes-256-gcm"}}
            inbounds = {"shadowsocks": [settings.MARZBAN_SS_INBOUND_TAG]}
        else:
            proxies = {"vless": {"flow": "xtls-rprx-vision"}}
            inbounds = {"vless": [settings.MARZBAN_INBOUND_TAG]}
        payload = {
            "username": username,
            "proxies": proxies,
            "inbounds": inbounds,
            "expire": int(expire_at.timestamp()),
            "data_limit": 0,  # unlimited traffic — see class docstring re: no per-device limit here
            "status": "active",
        }
        resp = await self._request("POST", "/api/user", json=payload)
        data = resp.json()
        if protocol == "vless" and data.get("links"):
            # Marzban hardcodes fp=chrome in its link template; there's no
            # API field to override it, so patch the already-built link.
            # "random" varies the TLS ClientHello fingerprint per
            # connection instead of always presenting the same one, which
            # is the generally-recommended Reality setting (a competitor's
            # working config used it too — see TZ 3.6).
            data["links"] = [link.replace("fp=chrome", "fp=random") for link in data["links"]]
        return data

    async def get_user(self, username: str) -> dict | None:
        try:
            resp = await self._request("GET", f"/api/user/{username}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return resp.json()

    async def modify_expire(self, username: str, expire_at: dt.datetime, status: str = "active") -> dict:
        payload = {"expire": int(expire_at.timestamp()), "status": status}
        resp = await self._request("PUT", f"/api/user/{username}", json=payload)
        return resp.json()

    async def disable_user(self, username: str) -> dict:
        resp = await self._request("PUT", f"/api/user/{username}", json={"status": "disabled"})
        return resp.json()

    async def remove_user(self, username: str) -> None:
        await self._request("DELETE", f"/api/user/{username}")

    @staticmethod
    def subscription_url_from(user_data: dict, base_url: str) -> str:
        sub_path = user_data.get("subscription_url", "")
        if sub_path.startswith("http"):
            return sub_path
        return f"{base_url.rstrip('/')}{sub_path}"


marzban_client = MarzbanClient()
