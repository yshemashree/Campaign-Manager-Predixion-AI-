"""Campaign and contact endpoints the dashboard leans on: counts, edits, copies, exports."""

import csv
import io
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.engine.events import campaign_channel
from tests.integration.conftest import (
    ALWAYS_OPEN,
    csv_rows,
    drain_events,
    make_member,
    make_org,
    phone,
)


async def _campaign(client: httpx.AsyncClient, org: dict[str, Any], **extra: Any) -> dict[str, Any]:
    body = {
        "name": "November EMI",
        "agent_id": org["agent"]["id"],
        "connection_id": org["conn"]["id"],
        "calling_window": ALWAYS_OPEN,
        **extra,
    }
    resp = await client.post(
        f"/api/v1/workspaces/{org['ws']['id']}/campaigns", headers=org["admin"], json=body
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def _upload(
    client: httpx.AsyncClient, org: dict[str, Any], campaign_id: str, content: str
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/campaigns/{campaign_id}/cohorts",
        headers=org["admin"],
        files={"file": ("cohort.csv", content.encode(), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


async def _set_status(
    factory: async_sessionmaker[AsyncSession], campaign_id: str, phones: list[str], status: str
) -> None:
    async with factory() as s:
        await s.execute(
            text(
                "UPDATE contacts SET status = :status"
                " WHERE campaign_id = :cid AND phone_e164 = ANY(:phones)"
            ),
            {"status": status, "cid": campaign_id, "phones": phones},
        )
        await s.commit()


async def test_campaigns_carry_org_and_contact_counts(
    client: httpx.AsyncClient,
    superadmin: dict[str, str],
    factory: async_sessionmaker[AsyncSession],
) -> None:
    org = await make_org(client, superadmin, "Org A")
    first = await _campaign(client, org, name="First")
    second = await _campaign(client, org, name="Second")
    assert first["org_id"] == org["org"]["id"] and first["contact_counts"] == {}
    await _upload(client, org, first["id"], csv_rows(5))
    await _upload(client, org, second["id"], csv_rows(2))
    await _set_status(factory, first["id"], [phone(0), phone(1)], "completed")

    listed = (
        await client.get(f"/api/v1/workspaces/{org['ws']['id']}/campaigns", headers=org["admin"])
    ).json()
    counts = {c["name"]: c["contact_counts"] for c in listed}
    assert counts == {"First": {"pending": 3, "completed": 2}, "Second": {"pending": 2}}
    one = (await client.get(f"/api/v1/campaigns/{first['id']}", headers=org["admin"])).json()
    assert one["contact_counts"] == {"pending": 3, "completed": 2}


async def test_contact_list_total_follows_filters(
    client: httpx.AsyncClient,
    superadmin: dict[str, str],
    factory: async_sessionmaker[AsyncSession],
) -> None:
    org = await make_org(client, superadmin, "Org A")
    campaign = await _campaign(client, org)
    await _upload(client, org, campaign["id"], csv_rows(12))
    await _set_status(factory, campaign["id"], [phone(i) for i in range(4)], "completed")
    url = f"/api/v1/campaigns/{campaign['id']}/contacts"

    page = (await client.get(f"{url}?limit=5", headers=org["admin"])).json()
    assert page["total"] == 12 and len(page["items"]) == 5
    nxt = (
        await client.get(f"{url}?limit=5&cursor={page['next_cursor']}", headers=org["admin"])
    ).json()
    assert nxt["total"] == 12  # the cursor doesn't change the total

    done = (await client.get(f"{url}?status=completed", headers=org["admin"])).json()
    assert done["total"] == 4
    assert all(c["next_attempt_at"] is None for c in done["items"])
    waiting = (await client.get(f"{url}?status=pending&limit=1", headers=org["admin"])).json()
    assert waiting["total"] == 8 and waiting["items"][0]["next_attempt_at"] is not None
    found = (await client.get(f"{url}?q=lead-1", headers=org["admin"])).json()
    assert found["total"] == 3  # lead-1, lead-10, lead-11


async def test_patch_agent_connection_and_numbers_only_in_draft(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    other = await make_org(client, superadmin, "Org B")
    campaign = await _campaign(client, org)
    url = f"/api/v1/campaigns/{campaign['id']}"
    ws = org["ws"]["id"]
    agent2 = (
        await client.post(
            f"/api/v1/workspaces/{ws}/agents",
            headers=org["admin"],
            json={"name": "Second agent", "app_id": "app-2", "app_version": 1},
        )
    ).json()
    conn2 = (
        await client.post(
            f"/api/v1/workspaces/{ws}/connections",
            headers=org["admin"],
            json={"name": "Line 2", "connection_id": "conn-2", "caller_numbers": ["+918069000009"]},
        )
    ).json()

    resp = await client.patch(
        url,
        headers=org["admin"],
        json={"agent_id": agent2["id"], "connection_id": conn2["id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent_id"] == agent2["id"] and body["connection_id"] == conn2["id"]
    # A new connection without explicit numbers takes all of its numbers.
    assert body["caller_numbers"] == ["+918069000009"]

    resp = await client.patch(
        url,
        headers=org["admin"],
        json={
            "agent_id": org["agent"]["id"],
            "connection_id": org["conn"]["id"],
            "caller_numbers": ["+918069000002"],
        },
    )
    assert resp.json()["caller_numbers"] == ["+918069000002"]
    # Numbers must be on the connection.
    resp = await client.patch(url, headers=org["admin"], json={"caller_numbers": ["+918069000009"]})
    assert resp.status_code == 422
    # Another org's agent or connection is invisible.
    resp = await client.patch(url, headers=org["admin"], json={"agent_id": other["agent"]["id"]})
    assert resp.status_code == 404
    resp = await client.patch(url, headers=org["admin"], json={"connection_id": None})
    assert resp.status_code == 422

    # Same org, other workspace: refused.
    ws2 = (
        await client.post("/api/v1/workspaces", headers=org["admin"], json={"name": "Other"})
    ).json()
    agent3 = (
        await client.post(
            f"/api/v1/workspaces/{ws2['id']}/agents",
            headers=org["admin"],
            json={"name": "Elsewhere", "app_id": "app-3", "app_version": 1},
        )
    ).json()
    resp = await client.patch(url, headers=org["admin"], json={"agent_id": agent3["id"]})
    assert resp.status_code == 422

    # Once started (then paused), only the other settings can change.
    await _upload(client, org, campaign["id"], csv_rows(2))
    for action in ("start", "pause"):
        await client.put(f"{url}/status", headers=org["admin"], json={"action": action})
    resp = await client.patch(url, headers=org["admin"], json={"agent_id": org["agent"]["id"]})
    assert resp.status_code == 409
    assert "draft" in resp.json()["detail"]
    resp = await client.patch(url, headers=org["admin"], json={"caller_numbers": ["+918069000001"]})
    assert resp.status_code == 409
    resp = await client.patch(url, headers=org["admin"], json={"attempts_per_second": 3})
    assert resp.status_code == 200


async def test_duplicate_makes_a_clean_draft(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    member = await make_member(client, org)
    source = await _campaign(
        client,
        org,
        caller_numbers=["+918069000002"],
        attempts_per_second=3,
        retry_policy={"max_attempts": 5},
        start_at="2099-01-01T09:00:00+05:30",
        end_at="2099-02-01T09:00:00+05:30",
        app_overrides={"initial_bot_message": "Hello"},
    )
    await _upload(client, org, source["id"], csv_rows(3))
    await client.put(
        f"/api/v1/campaigns/{source['id']}/status", headers=org["admin"], json={"action": "start"}
    )

    resp = await client.post(f"/api/v1/campaigns/{source['id']}/duplicate", headers=member)
    assert resp.status_code == 201, resp.text
    copy = resp.json()
    assert copy["id"] != source["id"]
    assert copy["name"] == "November EMI (copy)"
    assert copy["status"] == "draft" and copy["contact_counts"] == {}
    assert copy["start_at"] is None and copy["end_at"] is None
    for key in (
        "agent_id",
        "connection_id",
        "caller_numbers",
        "attempts_per_second",
        "retry_policy",
        "calling_window",
        "app_overrides",
    ):
        assert copy[key] == source[key], key
    page = (await client.get(f"/api/v1/campaigns/{copy['id']}/contacts", headers=member)).json()
    assert page["total"] == 0

    other = await make_org(client, superadmin, "Org B")
    resp = await client.post(f"/api/v1/campaigns/{source['id']}/duplicate", headers=other["admin"])
    assert resp.status_code == 404


async def test_cancel_contact(
    client: httpx.AsyncClient,
    superadmin: dict[str, str],
    factory: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> None:
    org = await make_org(client, superadmin, "Org A")
    campaign = await _campaign(client, org)
    await _upload(client, org, campaign["id"], csv_rows(3))
    await _set_status(factory, campaign["id"], [phone(1)], "retry_scheduled")
    await _set_status(factory, campaign["id"], [phone(2)], "in_progress")
    items = (
        await client.get(f"/api/v1/campaigns/{campaign['id']}/contacts", headers=org["admin"])
    ).json()["items"]
    by_phone = {c["phone_e164"]: c["id"] for c in items}

    pubsub = redis.pubsub()
    await pubsub.subscribe(campaign_channel(campaign["id"]))
    member = await make_member(client, org)
    for p in (phone(0), phone(1)):
        resp = await client.post(f"/api/v1/contacts/{by_phone[p]}/cancel", headers=member)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "cancelled" and body["final_reason"] == "cancelled_by_user"
        assert body["next_attempt_at"] is None

    published = await drain_events(pubsub)
    assert len(published) == 2
    event = published[0]
    assert event["type"] == "contact.updated" and event["status"] == "cancelled"
    assert {"next_attempt_at", "last_outcome", "updated_at"} <= event.keys()
    assert event["next_attempt_at"] is None

    # Calls under way, and contacts already cancelled, can't be cancelled.
    for p in (phone(2), phone(0)):
        resp = await client.post(f"/api/v1/contacts/{by_phone[p]}/cancel", headers=org["admin"])
        assert resp.status_code == 409
    other = await make_org(client, superadmin, "Org B")
    resp = await client.post(
        f"/api/v1/contacts/{by_phone[phone(2)]}/cancel", headers=other["admin"]
    )
    assert resp.status_code == 404


async def test_export_contacts_csv(
    client: httpx.AsyncClient,
    superadmin: dict[str, str],
    factory: async_sessionmaker[AsyncSession],
) -> None:
    org = await make_org(client, superadmin, "Org A")
    campaign = await _campaign(client, org, name="Nov / EMI")
    rows = csv_rows(2) + "+919876000099,=HYPERLINK(1),@evil,250\n"
    await _upload(client, org, campaign["id"], rows)
    async with factory() as s:
        await s.execute(
            text(
                "WITH c AS (SELECT id, org_id FROM contacts WHERE phone_e164 = :p)"
                " INSERT INTO call_attempts (id, org_id, campaign_id, contact_id, attempt_no,"
                " status, created_at, dispatched_at, ended_at, duration_s)"
                " SELECT gen_random_uuid(), c.org_id, :cid, c.id, n, 'completed', now(),"
                " now() + make_interval(mins => n), now(), 30 + n"
                " FROM c, generate_series(1, 2) AS n"
            ),
            {"p": phone(0), "cid": campaign["id"]},
        )
        await s.execute(
            text(
                "UPDATE contacts SET status = 'completed', attempts_made = 2,"
                " last_outcome = 'completed' WHERE phone_e164 = :p"
            ),
            {"p": phone(0)},
        )
        await s.commit()

    resp = await client.get(
        f"/api/v1/campaigns/{campaign['id']}/contacts.csv", headers=org["admin"]
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="contacts-nov---emi.csv"' in resp.headers["content-disposition"]
    table = list(csv.DictReader(io.StringIO(resp.text)))
    assert list(table[0].keys()) == [
        "phone_number",
        "lead_id",
        "customer_name",
        "emi_amount",
        "status",
        "attempts_made",
        "last_outcome",
        "final_reason",
        "last_attempt_at",
        "last_duration_s",
        "updated_at",
    ]
    by_phone = {r["phone_number"]: r for r in table}
    assert len(by_phone) == 3
    done = by_phone[phone(0)]
    assert done["status"] == "completed" and done["attempts_made"] == "2"
    assert done["last_duration_s"] == "32"  # from the latest attempt
    assert done["last_attempt_at"] and done["customer_name"] == "Customer 0"
    waiting = by_phone[phone(1)]
    assert waiting["status"] == "pending" and waiting["last_attempt_at"] == ""
    # Formulas are defused, as in the error report.
    evil = by_phone["+919876000099"]
    assert evil["lead_id"] == "'=HYPERLINK(1)" and evil["customer_name"] == "'@evil"

    other = await make_org(client, superadmin, "Org B")
    resp = await client.get(
        f"/api/v1/campaigns/{campaign['id']}/contacts.csv", headers=other["admin"]
    )
    assert resp.status_code == 404


async def test_validate_cohort_without_a_campaign(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    member = await make_member(client, org)
    url = f"/api/v1/agents/{org['agent']['id']}/validate-cohort"
    content = csv_rows(3) + "12345,lead-x,Bad,100\n"
    resp = await client.post(
        url, headers=member, files={"file": ("c.csv", content.encode(), "text/csv")}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is True and body["accepted"] is False and body["cohort"] is None
    assert body["rows_total"] == 4 and body["rows_valid"] == 3 and body["rows_rejected"] == 1
    assert body["duplicates_existing"] == 0 and body["dnd_skipped"] == 0
    assert body["error_report_csv"]

    resp = await client.post(
        url,
        headers=member,
        files={"file": ("c.csv", b"phone_number\n+919876543210\n", "text/csv")},
    )
    assert any("customer_name" in e for e in resp.json()["header_errors"])
    other = await make_org(client, superadmin, "Org B")
    resp = await client.post(
        url, headers=other["admin"], files={"file": ("c.csv", content.encode(), "text/csv")}
    )
    assert resp.status_code == 404


async def test_rate_reports_live_calls_per_second(
    client: httpx.AsyncClient,
    superadmin: dict[str, str],
    factory: async_sessionmaker[AsyncSession],
) -> None:
    org = await make_org(client, superadmin, "Org A")
    campaign = await _campaign(client, org)
    await _upload(client, org, campaign["id"], csv_rows(3))
    async with factory() as s:
        # One call still open since 20 s ago, one that ran from -20 s to -10 s, one long gone.
        await s.execute(
            text(
                """
                INSERT INTO call_attempts (id, org_id, campaign_id, contact_id, attempt_no,
                                           status, created_at, dispatched_at, ended_at)
                SELECT gen_random_uuid(), c.org_id, c.campaign_id, c.id, 1, v.status,
                       now() - make_interval(secs => v.began), NULL,
                       CASE WHEN v.ended IS NULL THEN NULL
                            ELSE now() - make_interval(secs => v.ended) END
                FROM contacts c
                JOIN (VALUES (:p0, 'dispatched', 20, NULL::int),
                             (:p1, 'completed', 20, 10),
                             (:p2, 'completed', 500, 400)) AS v(phone, status, began, ended)
                  ON v.phone = c.phone_e164
                """
            ),
            {"p0": phone(0), "p1": phone(1), "p2": phone(2)},
        )
        await s.commit()

    resp = await client.get(
        f"/api/v1/organizations/{org['org']['id']}/rate?seconds=30", headers=org["admin"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    live = body["live_per_second"]
    assert [p["t"] for p in live] == [p["t"] for p in body["per_second"]]
    calls = [p["calls"] for p in live]
    assert calls[:5] == [0] * 5  # before either call started
    assert calls[14] == 2  # both running about 15 s ago
    assert calls[-3:] == [1, 1, 1]  # only the open one now
