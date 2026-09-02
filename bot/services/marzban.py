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

    NOTE (verify against the deployed panel before going live): the exact field
    used to cap simultaneous connections per user differs between Marzban
    versions/forks (seen as `ips_limit` or `limit_ip` in various docs). Check
    the live panel's Swagger UI at ``{MARZBAN_BASE_URL}/docs`` and update
    ``IP_LIMIT_FIELD`` below to match before relying on the 1-device limit.
    """

    IP_LIMIT_FIELD = "ips_limit"
    IP_LIMIT_VALUE = 1

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

    async def create_user(self, username: str, expire_at: dt.datetime) -> dict:
        payload = {
            "username": username,
            "proxies": {"vless": {"flow": "xtls-rprx-vision"}},
            "inbounds": {"vless": [settings.MARZBAN_INBOUND_TAG]},
            "expire": int(expire_at.timestamp()),
            "data_limit": 0,  # unlimited traffic; device limit is enforced via IP field below
            self.IP_LIMIT_FIELD: self.IP_LIMIT_VALUE,
            "status": "active",
        }
        resp = await self._request("POST", "/api/user", json=payload)
        return resp.json()

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
