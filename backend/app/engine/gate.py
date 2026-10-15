"""The rate and concurrency gate: a thin Python wrapper over the Lua scripts in ./lua.

Every outbound call goes through two atomic steps inside Redis:
    reserve()  book a send slot (checks campaign state, window, pacing and org concurrency)
    fire()     the last check right before sending (still running? on time? phone free?)

All keys of one org share the hash tag {o:<org>} so they live in one Redis Cluster slot.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redis.asyncio import Redis

from app.core.config import Settings

_LUA_DIR = Path(__file__).parent / "lua"
RUNNABLE_KEY = "runnable"  # campaign_id -> org_id of campaigns the workers should serve


def org_gate_key(org_id: uuid.UUID | str) -> str:
    return f"{{o:{org_id}}}:gate"


def campaign_gate_key(org_id: uuid.UUID | str, campaign_id: uuid.UUID | str) -> str:
    return f"{{o:{org_id}}}:c:{campaign_id}"


def inflight_key(org_id: uuid.UUID | str) -> str:
    return f"{{o:{org_id}}}:inflight"


def fires_key(org_id: uuid.UUID | str) -> str:
    return f"{{o:{org_id}}}:fires"


def phone_lock_key(org_id: uuid.UUID | str, phone: str) -> str:
    return f"{{o:{org_id}}}:ph:{phone}"


def marker_key(org_id: uuid.UUID | str, attempt_ref: uuid.UUID | str) -> str:
    return f"{{o:{org_id}}}:sent:{attempt_ref}"


@dataclass(frozen=True)
class Grant:
    ok: bool
    reason: str = ""
    retry_after_ms: int = 0
    slot_ms: int = 0
    delay_ms: int = 0
    campaign_ver: str = ""
    limit_ver: str = ""
    rr: int = 0


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str
    wait_ms: int = 0


def _s(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class Gate:
    def __init__(self, redis: "Redis", settings: Settings) -> None:
        self.redis = redis
        self.settings = settings
        self._reserve = redis.register_script((_LUA_DIR / "reserve.lua").read_text())
        self._fire = redis.register_script((_LUA_DIR / "fire.lua").read_text())
        self._refund = redis.register_script((_LUA_DIR / "refund.lua").read_text())
        self._release = redis.register_script((_LUA_DIR / "release.lua").read_text())
        self._sync_campaign = redis.register_script((_LUA_DIR / "sync_campaign.lua").read_text())
        self._sync_org = redis.register_script((_LUA_DIR / "sync_org.lua").read_text())
        self._cooldown = redis.register_script((_LUA_DIR / "cooldown.lua").read_text())

    # ----- syncing state from Postgres -----

    async def sync_campaign(
        self,
        org_id: uuid.UUID,
        campaign_id: uuid.UUID,
        *,
        version: int,
        state: str,
        attempts_per_second: float,
        window_until_ms: int,
    ) -> bool:
        written = await self._sync_campaign(
            keys=[campaign_gate_key(org_id, campaign_id)],
            args=[version, state, attempts_per_second, window_until_ms],
        )
        return bool(written)

    async def sync_org(
        self, org_id: uuid.UUID, *, limit_version: int, max_cps: int, max_concurrent: int
    ) -> bool:
        written = await self._sync_org(
            keys=[org_gate_key(org_id)], args=[limit_version, max_cps, max_concurrent]
        )
        return bool(written)

    # ----- the dispatch path -----

    async def reserve(
        self, org_id: uuid.UUID, campaign_id: uuid.UUID, attempt_ref: uuid.UUID
    ) -> Grant:
        s = self.settings
        res = await self._reserve(
            keys=[
                org_gate_key(org_id),
                campaign_gate_key(org_id, campaign_id),
                inflight_key(org_id),
            ],
            args=[
                s.reserve_horizon_ms,
                s.rate_margin_ms,
                str(attempt_ref),
                s.reserve_horizon_ms + 10_000,
            ],
        )
        if int(res[0]) != 1:
            return Grant(ok=False, reason=_s(res[1]), retry_after_ms=int(res[2]))
        return Grant(
            ok=True,
            slot_ms=int(res[1]),
            delay_ms=int(res[2]),
            campaign_ver=_s(res[3]),
            limit_ver=_s(res[4]),
            rr=int(res[5]),
        )

    async def refund(
        self, org_id: uuid.UUID, campaign_id: uuid.UUID, attempt_ref: uuid.UUID, grant: Grant
    ) -> None:
        await self._refund(
            keys=[
                org_gate_key(org_id),
                campaign_gate_key(org_id, campaign_id),
                inflight_key(org_id),
            ],
            args=[grant.slot_ms, self.settings.rate_margin_ms, str(attempt_ref)],
        )

    async def fire(
        self,
        org_id: uuid.UUID,
        campaign_id: uuid.UUID,
        attempt_ref: uuid.UUID,
        phone: str,
        grant: Grant,
    ) -> Verdict:
        s = self.settings
        res = await self._fire(
            keys=[
                campaign_gate_key(org_id, campaign_id),
                org_gate_key(org_id),
                inflight_key(org_id),
                phone_lock_key(org_id, phone),
                marker_key(org_id, attempt_ref),
                fires_key(org_id),
            ],
            args=[
                grant.slot_ms,
                s.late_tolerance_ms,
                str(attempt_ref),
                grant.campaign_ver,
                grant.limit_ver,
                s.phone_lock_ttl_s,
                s.webhook_timeout_s * 1000,
            ],
        )
        return Verdict(ok=int(res[0]) == 1, reason=_s(res[1]), wait_ms=int(res[2]))

    async def release(self, org_id: uuid.UUID, attempt_ref: uuid.UUID, phone: str) -> None:
        """The call is over or was never placed: free its concurrency place and phone lock."""
        await self._release(
            keys=[inflight_key(org_id), phone_lock_key(org_id, phone)], args=[str(attempt_ref)]
        )

    async def revoke(self, org_id: uuid.UUID, attempt_ref: uuid.UUID) -> bool:
        """Used by the reaper. True if the attempt was never sent (and now never can be)."""
        return bool(
            await self.redis.set(marker_key(org_id, attempt_ref), "revoked", nx=True, ex=86400)
        )

    async def cooldown(self, org_id: uuid.UUID, ms: int) -> None:
        await self._cooldown(keys=[org_gate_key(org_id)], args=[ms])

    # ----- observability -----

    async def inflight_count(self, org_id: uuid.UUID) -> int:
        now_ms = int((await self.redis.time())[0]) * 1000
        return int(await self.redis.zcount(inflight_key(org_id), now_ms, "+inf"))

    async def fires_between(self, org_id: uuid.UUID, start_ms: int, end_ms: int) -> list[int]:
        """Send timestamps (ms) in a time range; feeds the live rate chart."""
        rows = await self.redis.zrangebyscore(fires_key(org_id), start_ms, end_ms, withscores=True)
        return [int(item[1]) for item in rows]
