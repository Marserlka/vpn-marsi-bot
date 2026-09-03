from __future__ import annotations

import httpx

from bot.config import settings


class AwgAgentError(Exception):
    pass


class AwgAgentClient:
    """Talks to the awg_agent service running on the VPS (see scripts/awg_agent.py
    on the server) which owns both VPN interfaces we offer — AmneziaWG
    (obfuscated) and plain WireGuard (native kernel module, faster, no
    obfuscation) — and their peer lists.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.AWG_AGENT_BASE_URL,
            headers={"Authorization": f"Bearer {settings.AWG_AGENT_TOKEN}"},
            timeout=15.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def create_peer(self, label: str, protocol: str = "amnezia") -> dict:
        resp = await self._client.post("/peers", json={"label": label, "protocol": protocol})
        if resp.status_code != 201:
            raise AwgAgentError(f"create_peer failed: {resp.status_code} {resp.text}")
        return resp.json()

    async def delete_peer(self, public_key: str, protocol: str = "amnezia") -> None:
        resp = await self._client.delete(f"/peers/{public_key}", params={"protocol": protocol})
        if resp.status_code not in (200, 404):
            raise AwgAgentError(f"delete_peer failed: {resp.status_code} {resp.text}")


awg_agent = AwgAgentClient()
