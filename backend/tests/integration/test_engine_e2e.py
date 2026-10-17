"""The whole engine running for real: scheduler + dispatcher + API + webhooks.

Sarvam is replaced by an in-process fake that, like the mock server, accepts the call, waits a
bit, then posts the result back to our webhook. The fake also acts as referee: it measures the
most calls live at once and the most calls started in any rolling second, per org.
"""

import asyncio
import json
import random
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.engine.dispatcher import Dispatcher
from app.engine.gate import Gate
from app.engine.sarvam_client import SarvamClient
from app.engine.scheduler import Scheduler
from tests.integration.conftest import ALWAYS_OPEN, csv_rows, make_org


class FakeSarvam:
    def __init__(self, api: httpx.AsyncClient) -> None:
        self.api = api
        self.arrivals: dict[str, list[float]] = defaultdict(list)
        self.active: Counter[str] = Counter()
        self.max_active: Counter[str] = Counter()
        self.calls_per_phone: Counter[str] = Counter()
        self.busy_first: set[str] = set()  # these numbers are busy on the first call
        self.duplicate_webhooks = False
        self.call_seconds = (0.2, 0.5)
        self._tasks: set[asyncio.Task[None]] = set()

    async def handler(self, request: httpx.Request) -> httpx.Response:
        org = request.url.path.split("/")[5]
        body = json.loads(request.content)
        phone = body["user_config"]["user_phone_number"]
        self.arrivals[org].append(time.monotonic())
        self.calls_per_phone[phone] += 1
        self.active[org] += 1
        self.max_active[org] = max(self.max_active[org], self.active[org])
        attempt_id = str(uuid.uuid4())
        task = asyncio.create_task(self._finish(org, phone, attempt_id, body))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return httpx.Response(200, json={"attempt_id": attempt_id, "status": "initiated"})

    async def _finish(self, org: str, phone: str, attempt_id: str, body: dict[str, Any]) -> None:
        await asyncio.sleep(random.uniform(*self.call_seconds))
        self.active[org] -= 1
        busy = phone in self.busy_first and self.calls_per_phone[phone] == 1
        payload = {
            "attempt_id": attempt_id,
            "status": "busy" if busy else "connected",
            "duration": None if busy else 42,
            "webhook_config": body["webhook_config"],
        }
        for _ in range(2 if self.duplicate_webhooks else 1):
            resp = await self.api.post("/api/v1/webhooks/sarvam", json=payload)
            assert resp.status_code == 200, resp.text

    async def wait_for_calls(self, org: str, n: int) -> None:
        for _ in range(200):
            if len(self.arrivals[org]) >= n:
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"fewer than {n} calls arrived")

    def max_in_rolling_second(self, org: str) -> int:
        times = sorted(self.arrivals[org])
        best, start = 0, 0
        for end, t in enumerate(times):
            while t - times[start] >= 1.0:
                start += 1
            best = max(best, end - start + 1)
        return best


@pytest.fixture
async def engine(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    client: httpx.AsyncClient,
) -> AsyncIterator[FakeSarvam]:
    fake = FakeSarvam(client)
    sarvam = SarvamClient(settings)
    await sarvam.client.aclose()
    sarvam.client = httpx.AsyncClient(
        transport=httpx.MockTransport(fake.handler), base_url=settings.sarvam_base_url
    )
    gate = Gate(redis, settings)
    stop = asyncio.Event()
    # Two dispatchers, as if two worker processes were running.
    loops = [
        asyncio.create_task(Scheduler(settings, factory, redis, gate, "w1").run(stop)),
        asyncio.create_task(Dispatcher(settings, factory, redis, gate, sarvam, "w1").run(stop)),
        asyncio.create_task(Dispatcher(settings, factory, redis, gate, sarvam, "w2").run(stop)),
    ]
    yield fake
    stop.set()
    await asyncio.gather(*loops, return_exceptions=True)
    await asyncio.gather(*fake._tasks, return_exceptions=True)
    await sarvam.aclose()


async def _create(client: httpx.AsyncClient, org: dict[str, Any], n: int, **extra: Any) -> str:
    resp = await client.post(
        f"/api/v1/workspaces/{org['ws']['id']}/campaigns",
        headers=org["admin"],
        json={
            "name": "Engine test",
            "agent_id": org["agent"]["id"],
            "connection_id": org["conn"]["id"],
            "attempts_per_second": 10,
            "calling_window": ALWAYS_OPEN,
            **extra,
        },
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    up = await client.post(
        f"/api/v1/campaigns/{cid}/cohorts",
        headers=org["admin"],
        files={"file": ("c.csv", csv_rows(n).encode(), "text/csv")},
    )
    assert up.json()["accepted"], up.text
    return str(cid)


async def _action(
    client: httpx.AsyncClient, org: dict[str, Any], cid: str, action: str
) -> dict[str, Any]:
    resp = await client.put(
        f"/api/v1/campaigns/{cid}/status", headers=org["admin"], json={"action": action}
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


async def _wait_status(
    client: httpx.AsyncClient, org: dict[str, Any], cid: str, status: str, within: float = 30
) -> dict[str, Any]:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        stats = (await client.get(f"/api/v1/campaigns/{cid}/stats", headers=org["admin"])).json()
        if stats["status"] == status:
            return dict(stats)
        await asyncio.sleep(0.2)
    raise AssertionError(f"campaign never reached {status}: {stats}")


async def test_campaign_runs_to_completion_within_org_limits(
    client: httpx.AsyncClient,
    superadmin: dict[str, str],
    engine: FakeSarvam,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    org = await make_org(client, superadmin, "Org A", concurrent=3, cps=4)
    sv_org = org["org"]["sarvam_org_id"]
    cid = await _create(
        client,
        org,
        24,
        retry_policy={"max_attempts": 2, "rules": {"busy": {"enabled": True, "delay_s": 1}}},
    )
    # Every fourth number is busy the first time and answers on the retry.
    engine.busy_first = {f"+9198{76000000 + i}" for i in range(0, 24, 4)}
    engine.duplicate_webhooks = True  # duplicates must not double-count anything

    await _action(client, org, cid, "start")
    stats = await _wait_status(client, org, cid, "completed", within=40)

    assert stats["by_status"] == {"completed": 24}
    assert stats["attempts_total"] == 24 + 6
    # The referee's view: limits held the whole time.
    assert engine.max_active[sv_org] <= 3
    assert engine.max_in_rolling_second(sv_org) <= 4
    # Exactly one call per attempt: busy numbers twice, everyone else once.
    assert sum(engine.calls_per_phone.values()) == 30
    assert all(engine.calls_per_phone[p] == 2 for p in engine.busy_first)

    async with factory() as s:
        statuses: dict[str, int] = dict(
            (await s.execute(text("SELECT status, count(*) FROM call_attempts GROUP BY 1"))).all()
        )
    assert statuses == {"completed": 24, "busy": 6}


async def test_two_orgs_have_separate_limits(
    client: httpx.AsyncClient, superadmin: dict[str, str], engine: FakeSarvam
) -> None:
    a = await make_org(client, superadmin, "Org A", concurrent=2, cps=3)
    b = await make_org(client, superadmin, "Org B", concurrent=4, cps=6)
    engine.call_seconds = (0.3, 0.6)
    ca = await _create(client, a, 12)
    cb = await _create(client, b, 20)
    await _action(client, a, ca, "start")
    await _action(client, b, cb, "start")
    await _wait_status(client, a, ca, "completed", within=40)
    await _wait_status(client, b, cb, "completed", within=40)

    sa, sb = a["org"]["sarvam_org_id"], b["org"]["sarvam_org_id"]
    assert engine.max_active[sa] <= 2 and engine.max_in_rolling_second(sa) <= 3
    assert engine.max_active[sb] <= 4 and engine.max_in_rolling_second(sb) <= 6
    # B wasn't slowed down to A's limits.
    assert engine.max_active[sb] > 2


async def test_pause_stops_new_calls_and_resume_finishes(
    client: httpx.AsyncClient, superadmin: dict[str, str], engine: FakeSarvam
) -> None:
    org = await make_org(client, superadmin, "Org A", concurrent=3, cps=3)
    sv_org = org["org"]["sarvam_org_id"]
    cid = await _create(client, org, 30)
    await _action(client, org, cid, "start")

    await engine.wait_for_calls(sv_org, 4)
    await _action(client, org, cid, "pause")
    paused_at = time.monotonic()
    sent_before = len(engine.arrivals[sv_org])
    await asyncio.sleep(2.0)
    late = [t for t in engine.arrivals[sv_org] if t > paused_at]
    assert late == [], "a call went out after the pause was acknowledged"

    stats = (await client.get(f"/api/v1/campaigns/{cid}/stats", headers=org["admin"])).json()
    assert stats["by_status"].get("pending", 0) == 30 - sent_before

    await _action(client, org, cid, "resume")
    stats = await _wait_status(client, org, cid, "completed", within=40)
    assert stats["by_status"] == {"completed": 30}
    assert sum(engine.calls_per_phone.values()) == 30


async def test_stop_cancels_the_rest(
    client: httpx.AsyncClient, superadmin: dict[str, str], engine: FakeSarvam
) -> None:
    org = await make_org(client, superadmin, "Org A", concurrent=2, cps=2)
    cid = await _create(client, org, 20)
    await _action(client, org, cid, "start")
    await engine.wait_for_calls(org["org"]["sarvam_org_id"], 2)
    await _action(client, org, cid, "stop")

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        stats = (await client.get(f"/api/v1/campaigns/{cid}/stats", headers=org["admin"])).json()
        open_ = sum(stats["by_status"].get(s, 0) for s in ("pending", "dialing", "in_progress"))
        if open_ == 0:
            break
        await asyncio.sleep(0.2)
    called = sum(engine.calls_per_phone.values())
    assert stats["by_status"].get("cancelled") == 20 - called
    assert stats["by_status"].get("completed") == called
