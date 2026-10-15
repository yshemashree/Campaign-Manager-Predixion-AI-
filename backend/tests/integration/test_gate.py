"""The Redis gate on its own: the limits, the fencing and the races it exists to win."""

import asyncio
import itertools
import time
import uuid

import pytest
from redis.asyncio import Redis

from app.core.config import Settings
from app.engine.gate import Gate, Grant, org_gate_key

ORG = uuid.uuid4()
CAMP = uuid.uuid4()
FAR = 4_102_444_800_000  # window open until 2100


@pytest.fixture
def gate(redis: Redis, settings: Settings) -> Gate:
    # A wider late tolerance than production so slow CI runners don't miss their slot.
    return Gate(redis, settings.model_copy(update={"late_tolerance_ms": 200}))


async def setup(
    gate: Gate,
    *,
    cps: int = 100,
    concurrent: int = 100,
    aps: float = 100,
    campaign: uuid.UUID = CAMP,
    window_until: int = FAR,
) -> None:
    await gate.sync_org(ORG, limit_version=1, max_cps=cps, max_concurrent=concurrent)
    # Skip the cold-start guard (first slot 1 s out) so tests don't wait for it.
    await gate.redis.hset(org_gate_key(ORG), "tat", 0)
    await gate.sync_campaign(
        ORG,
        campaign,
        version=1,
        state="running",
        attempts_per_second=aps,
        window_until_ms=window_until,
    )


async def fire_when_due(
    gate: Gate, ref: uuid.UUID, grant: Grant, phone: str = "+919876500000"
) -> str:
    while True:
        verdict = await gate.fire(ORG, CAMP, ref, phone, grant)
        if verdict.reason != "early":
            return verdict.reason
        await asyncio.sleep(verdict.wait_ms / 1000)


async def test_concurrency_cap_holds_under_parallel_reservers(gate: Gate) -> None:
    await setup(gate, concurrent=3)
    grants = await asyncio.gather(*(gate.reserve(ORG, CAMP, uuid.uuid4()) for _ in range(25)))
    assert sum(g.ok for g in grants) == 3
    assert {g.reason for g in grants if not g.ok} == {"org_busy"}
    assert await gate.inflight_count(ORG) == 3


async def test_release_frees_a_place(gate: Gate) -> None:
    await setup(gate, concurrent=1)
    ref = uuid.uuid4()
    grant = await gate.reserve(ORG, CAMP, ref)
    assert grant.ok
    assert (await gate.reserve(ORG, CAMP, uuid.uuid4())).reason == "org_busy"
    assert await fire_when_due(gate, ref, grant) == "ok"
    # A live call still counts until it is over.
    assert (await gate.reserve(ORG, CAMP, uuid.uuid4())).reason == "org_busy"
    await gate.release(ORG, ref, "+919876500000")
    assert (await gate.reserve(ORG, CAMP, uuid.uuid4())).ok


async def test_org_pacing_spaces_slots(gate: Gate, settings: Settings) -> None:
    await setup(gate, cps=5)
    spacing = -(-(1000 + settings.rate_margin_ms) // 5)  # ceil
    slots: list[int] = []
    for _ in range(10):
        grant = await gate.reserve(ORG, CAMP, uuid.uuid4())
        if not grant.ok:
            assert grant.reason == "org_pace" and grant.retry_after_ms > 0
            break
        slots.append(grant.slot_ms)
    # Only about one second's worth is booked ahead; each slot is a full spacing apart.
    assert 4 <= len(slots) <= 6
    assert all(b - a == spacing for a, b in itertools.pairwise(slots))
    # So no rolling second can hold more than 5 slots.
    assert all(slots[i + 5] - slots[i] > 1000 for i in range(len(slots) - 5))


async def test_campaign_pace_leaves_slots_for_other_campaigns(gate: Gate) -> None:
    other = uuid.uuid4()
    await setup(gate, cps=10, aps=1)
    await gate.sync_campaign(
        ORG, other, version=1, state="running", attempts_per_second=10, window_until_ms=FAR
    )
    assert (await gate.reserve(ORG, CAMP, uuid.uuid4())).ok
    slow = await gate.reserve(ORG, CAMP, uuid.uuid4())
    assert slow.reason == "campaign_pace" and slow.retry_after_ms > 500
    # The org still has capacity, and the other campaign gets it.
    assert (await gate.reserve(ORG, other, uuid.uuid4())).ok


async def test_older_sync_cannot_undo_a_pause(gate: Gate) -> None:
    await setup(gate)
    assert await gate.sync_campaign(
        ORG, CAMP, version=2, state="paused", attempts_per_second=100, window_until_ms=FAR
    )
    # A slow scheduler arrives late with the old "running" state: ignored.
    assert not await gate.sync_campaign(
        ORG, CAMP, version=1, state="running", attempts_per_second=100, window_until_ms=FAR
    )
    assert (await gate.reserve(ORG, CAMP, uuid.uuid4())).reason == "not_running"


async def test_pause_between_reserve_and_fire_stops_the_call(gate: Gate) -> None:
    await setup(gate)
    ref = uuid.uuid4()
    grant = await gate.reserve(ORG, CAMP, ref)
    assert grant.ok
    await gate.sync_campaign(
        ORG, CAMP, version=2, state="paused", attempts_per_second=100, window_until_ms=FAR
    )
    assert await fire_when_due(gate, ref, grant) == "not_running"
    # Pause then resume is a new version too: the old booking stays dead.
    await gate.sync_campaign(
        ORG, CAMP, version=3, state="running", attempts_per_second=100, window_until_ms=FAR
    )
    assert await fire_when_due(gate, ref, grant) == "not_running"


async def test_limit_change_invalidates_bookings(gate: Gate) -> None:
    await setup(gate)
    ref = uuid.uuid4()
    grant = await gate.reserve(ORG, CAMP, ref)
    await gate.sync_org(ORG, limit_version=2, max_cps=1, max_concurrent=1)
    assert await fire_when_due(gate, ref, grant) == "limit_changed"


async def test_a_call_is_never_sent_late(settings: Settings, redis: Redis) -> None:
    strict = Gate(redis, settings.model_copy(update={"late_tolerance_ms": 20}))
    await setup(strict)
    ref = uuid.uuid4()
    grant = await strict.reserve(ORG, CAMP, ref)
    await asyncio.sleep((grant.delay_ms + 100) / 1000)
    assert (await strict.fire(ORG, CAMP, ref, "+919876500000", grant)).reason == "late"


async def test_reaper_and_worker_race_has_one_winner(gate: Gate) -> None:
    await setup(gate)
    # The reaper gets there first: the worker must not send.
    ref = uuid.uuid4()
    grant = await gate.reserve(ORG, CAMP, ref)
    assert await gate.revoke(ORG, ref) is True
    assert await fire_when_due(gate, ref, grant) == "revoked"

    # The worker gets there first: the reaper learns the call went out.
    ref = uuid.uuid4()
    grant = await gate.reserve(ORG, CAMP, ref)
    assert await fire_when_due(gate, ref, grant, phone="+919876500001") == "ok"
    assert await gate.revoke(ORG, ref) is False


async def test_one_phone_is_never_called_twice_at_once(gate: Gate) -> None:
    await setup(gate)
    first, second = uuid.uuid4(), uuid.uuid4()
    g1 = await gate.reserve(ORG, CAMP, first)
    g2 = await gate.reserve(ORG, CAMP, second)
    assert await fire_when_due(gate, first, g1) == "ok"
    assert await fire_when_due(gate, second, g2) == "phone_busy"


async def test_closed_window_and_missing_limits_fail_closed(gate: Gate) -> None:
    now_ms = int(time.time() * 1000)
    await setup(gate, window_until=now_ms - 1)
    assert (await gate.reserve(ORG, CAMP, uuid.uuid4())).reason == "window_closed"

    stranger = uuid.uuid4()  # an org the scheduler hasn't synced yet
    await gate.sync_campaign(
        stranger, CAMP, version=1, state="running", attempts_per_second=1, window_until_ms=FAR
    )
    assert (await gate.reserve(stranger, CAMP, uuid.uuid4())).reason == "org_disabled"


async def test_refund_returns_the_last_slot(gate: Gate) -> None:
    await setup(gate, cps=2, aps=2)
    ref = uuid.uuid4()
    grant = await gate.reserve(ORG, CAMP, ref)
    await gate.refund(ORG, CAMP, ref, grant)
    again = await gate.reserve(ORG, CAMP, uuid.uuid4())
    assert again.ok and again.slot_ms <= grant.slot_ms + 5
    assert await gate.inflight_count(ORG) == 1
