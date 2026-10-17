"""The Do Not Disturb list: who can change it, and that listed numbers are never dialled."""

import uuid
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.engine import repo
from app.engine.gate import Gate
from app.engine.scheduler import Scheduler
from tests.integration.conftest import ALWAYS_OPEN, csv_rows, make_member, make_org, phone


def _dnd(org: dict[str, Any]) -> str:
    return f"/api/v1/organizations/{org['org']['id']}/dnd"


async def _campaign(client: httpx.AsyncClient, org: dict[str, Any]) -> str:
    resp = await client.post(
        f"/api/v1/workspaces/{org['ws']['id']}/campaigns",
        headers=org["admin"],
        json={
            "name": "DND test",
            "agent_id": org["agent"]["id"],
            "connection_id": org["conn"]["id"],
            "calling_window": ALWAYS_OPEN,
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _upload(
    client: httpx.AsyncClient, org: dict[str, Any], cid: str, content: str, **form: str
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/campaigns/{cid}/cohorts",
        headers=org["admin"],
        files={"file": ("c.csv", content.encode(), "text/csv")},
        data=form,
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


async def test_add_list_search_and_remove(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    url = _dnd(org)
    resp = await client.post(
        url,
        headers=org["admin"],
        json={
            "phone_numbers": ["9876500001", "+919876500002", "+91 98765 00001", "nope"],
            "reason": "asked not to be called",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"added": 2, "already_listed": 0, "invalid": ["nope"]}
    again = await client.post(url, headers=org["admin"], json={"phone_numbers": ["9876500002"]})
    assert again.json() == {"added": 0, "already_listed": 1, "invalid": []}

    upload = await client.post(
        f"{url}/upload",
        headers=org["admin"],
        files={
            "file": (
                "dnd.csv",
                b"phone_number,reason\n+919876500003,complaint\n+919876500001,\n123,x\n\n",
                "text/csv",
            )
        },
    )
    assert upload.status_code == 200, upload.text
    assert upload.json() == {"added": 1, "already_listed": 1, "invalid": ["123"]}
    bad = await client.post(
        f"{url}/upload",
        headers=org["admin"],
        files={"file": ("dnd.csv", b"number\n+919876500004\n", "text/csv")},
    )
    assert bad.status_code == 422

    page = (await client.get(f"{url}?limit=2", headers=org["admin"])).json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["next_cursor"]
    # Newest first.
    assert page["items"][0]["phone_e164"] == "+919876500003"
    rest = (await client.get(f"{url}?cursor={page['next_cursor']}", headers=org["admin"])).json()
    assert rest["total"] == 3 and len(rest["items"]) == 1 and rest["next_cursor"] is None
    reasons = {d["phone_e164"]: d["reason"] for d in page["items"] + rest["items"]}
    assert reasons == {
        "+919876500001": "asked not to be called",  # listing again keeps the first reason
        "+919876500002": "asked not to be called",
        "+919876500003": "complaint",
    }
    found = (await client.get(f"{url}?search=500002", headers=org["admin"])).json()
    assert found["total"] == 1 and found["items"][0]["phone_e164"] == "+919876500002"

    resp = await client.delete(f"{url}/+919876500002", headers=org["admin"])
    assert resp.status_code == 204
    resp = await client.delete(f"{url}/+919876500002", headers=org["admin"])
    assert resp.status_code == 404
    assert (await client.get(url, headers=org["admin"])).json()["total"] == 2


async def test_permissions(client: httpx.AsyncClient, superadmin: dict[str, str]) -> None:
    a = await make_org(client, superadmin, "Org A")
    b = await make_org(client, superadmin, "Org B")
    member = await make_member(client, a)
    url = _dnd(a)
    body = {"phone_numbers": ["+919876500001"]}

    # Members read, but don't write.
    assert (await client.get(url, headers=member)).status_code == 200
    assert (await client.post(url, headers=member, json=body)).status_code == 403
    assert (await client.delete(f"{url}/+919876500001", headers=member)).status_code == 403
    upload = await client.post(
        f"{url}/upload",
        headers=member,
        files={"file": ("dnd.csv", b"phone_number\n+919876500001\n", "text/csv")},
    )
    assert upload.status_code == 403

    # Superadmins write anywhere.
    resp = await client.post(url, headers=superadmin, json=body)
    assert resp.status_code == 200 and resp.json()["added"] == 1

    # Another org's list doesn't exist, as far as B's users can tell.
    b_member = await make_member(client, b)
    for headers in (b["admin"], b_member):
        assert (await client.get(url, headers=headers)).status_code == 404
        assert (await client.post(url, headers=headers, json=body)).status_code == 404
        resp = await client.delete(f"{url}/+919876500001", headers=headers)
        assert resp.status_code == 404
    assert (await client.get(_dnd(b), headers=b["admin"])).json()["total"] == 0


async def test_cohort_upload_skips_dnd_numbers(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    other = await make_org(client, superadmin, "Org B")
    await client.post(_dnd(org), headers=org["admin"], json={"phone_numbers": [phone(0), phone(3)]})
    # Only the org's own list applies.
    await client.post(_dnd(other), headers=other["admin"], json={"phone_numbers": [phone(1)]})
    cid = await _campaign(client, org)

    dry = await _upload(client, org, cid, csv_rows(5), dry_run="true")
    assert dry["dnd_skipped"] == 2 and dry["rows_valid"] == 5
    checked = await client.post(
        f"/api/v1/agents/{org['agent']['id']}/validate-cohort",
        headers=org["admin"],
        files={"file": ("c.csv", csv_rows(5).encode(), "text/csv")},
    )
    assert checked.json()["dnd_skipped"] == 2

    done = await _upload(client, org, cid, csv_rows(5))
    assert done["accepted"] is True and done["dnd_skipped"] == 2
    assert done["cohort"]["rows_accepted"] == 3
    page = (await client.get(f"/api/v1/campaigns/{cid}/contacts", headers=org["admin"])).json()
    assert {c["phone_e164"] for c in page["items"]} == {phone(1), phone(2), phone(4)}


async def test_engine_never_claims_and_scheduler_cancels_dnd_contacts(
    client: httpx.AsyncClient,
    superadmin: dict[str, str],
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    org = await make_org(client, superadmin, "Org A")
    cid = await _campaign(client, org)
    await _upload(client, org, cid, csv_rows(3))
    resp = await client.put(
        f"/api/v1/campaigns/{cid}/status", headers=org["admin"], json={"action": "start"}
    )
    assert resp.json()["status"] == "running"
    # Listed after upload: now in the queue but must not be claimed.
    await client.post(_dnd(org), headers=org["admin"], json={"phone_numbers": [phone(0), phone(2)]})

    claimed = []
    async with factory() as s:
        version = await s.scalar(
            text("SELECT state_version FROM campaigns WHERE id = :id"), {"id": cid}
        )
    for _ in range(3):
        async with factory() as s:
            claim = await repo.claim_next(
                s,
                campaign_id=uuid.UUID(cid),
                granted_version=version,
                worker_id="t",
                attempt_ref=uuid.uuid4(),
                from_number="+918069000001",
                lease_s=30,
            )
        if claim:
            claimed.append(claim.phone)
    assert claimed == [phone(1)]

    scheduler = Scheduler(settings, factory, redis, Gate(redis, settings), "t")
    await scheduler.cancel_dnd()
    page = (await client.get(f"/api/v1/campaigns/{cid}/contacts", headers=org["admin"])).json()
    by_phone = {c["phone_e164"]: c for c in page["items"]}
    for p in (phone(0), phone(2)):
        assert by_phone[p]["status"] == "cancelled" and by_phone[p]["final_reason"] == "dnd"
    assert by_phone[phone(1)]["status"] == "dialing"  # claimed before; left alone
