from typing import Any

import httpx

from tests.integration.conftest import ALWAYS_OPEN, csv_rows, make_org


async def _campaign(client: httpx.AsyncClient, org: dict[str, Any], **extra: Any) -> dict[str, Any]:
    body = {
        "name": "November EMI",
        "agent_id": org["agent"]["id"],
        "connection_id": org["conn"]["id"],
        "attempts_per_second": 2,
        "calling_window": ALWAYS_OPEN,
        **extra,
    }
    resp = await client.post(
        f"/api/v1/workspaces/{org['ws']['id']}/campaigns", headers=org["admin"], json=body
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def _upload(
    client: httpx.AsyncClient, org: dict[str, Any], campaign_id: str, content: str, **form: str
) -> httpx.Response:
    return await client.post(
        f"/api/v1/campaigns/{campaign_id}/cohorts",
        headers=org["admin"],
        files={"file": ("cohort.csv", content.encode(), "text/csv")},
        data=form,
    )


async def test_sample_csv_matches_agent_variables(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    resp = await client.get(
        f"/api/v1/agents/{org['agent']['id']}/sample-cohort.csv", headers=org["admin"]
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.text.splitlines()[0] == "phone_number,lead_id,customer_name,emi_amount"


async def test_invalid_rows_reject_the_whole_file_by_default(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    campaign = await _campaign(client, org)
    bad = csv_rows(3) + "12345,lead-x,Bad Phone,100\n+919876000999,lead-y,,abc\n"
    resp = await _upload(client, org, campaign["id"], bad)
    body = resp.json()
    assert body["accepted"] is False
    assert body["rows_total"] == 5 and body["rows_valid"] == 3 and body["rows_rejected"] == 2
    messages = {(e["row"], e["column"]) for e in body["errors"]}
    assert (4, "phone_number") in messages
    assert (5, "customer_name") in messages and (5, "emi_amount") in messages
    assert "=" not in (body["error_report_csv"] or "")[:1]

    # Nothing imported...
    page = (
        await client.get(f"/api/v1/campaigns/{campaign['id']}/contacts", headers=org["admin"])
    ).json()
    assert page["items"] == []
    # ...unless the caller asks to skip invalid rows.
    resp = await _upload(client, org, campaign["id"], bad, skip_invalid="true")
    assert resp.json()["accepted"] is True
    assert resp.json()["cohort"]["rows_accepted"] == 3


async def test_header_problems_are_reported(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    campaign = await _campaign(client, org)
    resp = await _upload(client, org, campaign["id"], "phone_number,surprise\n+919876543210,x\n")
    errors = resp.json()["header_errors"]
    assert any("customer_name" in e for e in errors)
    assert any("surprise" in e for e in errors)


async def test_dry_run_and_duplicates(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    campaign = await _campaign(client, org)
    dry = (await _upload(client, org, campaign["id"], csv_rows(4), dry_run="true")).json()
    assert dry["dry_run"] is True and dry["accepted"] is False and dry["rows_valid"] == 4

    first = (await _upload(client, org, campaign["id"], csv_rows(4))).json()
    assert first["cohort"]["rows_accepted"] == 4
    # Same 4 numbers + 2 new ones: only the new ones are imported.
    second = (await _upload(client, org, campaign["id"], csv_rows(6))).json()
    assert second["duplicates_existing"] == 4
    assert second["cohort"]["rows_accepted"] == 2

    page = (
        await client.get(
            f"/api/v1/campaigns/{campaign['id']}/contacts?limit=4", headers=org["admin"]
        )
    ).json()
    assert len(page["items"]) == 4 and page["next_cursor"]
    rest = (
        await client.get(
            f"/api/v1/campaigns/{campaign['id']}/contacts?cursor={page['next_cursor']}",
            headers=org["admin"],
        )
    ).json()
    assert len(rest["items"]) == 2 and rest["next_cursor"] is None
    assert all(c["status"] == "pending" for c in page["items"] + rest["items"])


async def test_lifecycle_rules(client: httpx.AsyncClient, superadmin: dict[str, str]) -> None:
    org = await make_org(client, superadmin, "Org A")
    campaign = await _campaign(client, org)
    url = f"/api/v1/campaigns/{campaign['id']}/status"

    # Can't start without contacts.
    resp = await client.put(url, headers=org["admin"], json={"action": "start"})
    assert resp.status_code == 422
    await _upload(client, org, campaign["id"], csv_rows(2))

    assert (await client.put(url, headers=org["admin"], json={"action": "start"})).json()[
        "status"
    ] == "running"
    paused = (await client.put(url, headers=org["admin"], json={"action": "pause"})).json()
    assert paused["status"] == "paused"
    # Repeating an action is a harmless no-op, not an error.
    again = await client.put(url, headers=org["admin"], json={"action": "pause"})
    assert again.status_code == 200 and again.json()["state_version"] == paused["state_version"]

    # Settings can be edited while paused.
    edit = await client.patch(
        f"/api/v1/campaigns/{campaign['id']}", headers=org["admin"], json={"attempts_per_second": 4}
    )
    assert edit.status_code == 200 and edit.json()["attempts_per_second"] == 4

    assert (await client.put(url, headers=org["admin"], json={"action": "resume"})).json()[
        "status"
    ] == "running"
    edit = await client.patch(
        f"/api/v1/campaigns/{campaign['id']}", headers=org["admin"], json={"attempts_per_second": 3}
    )
    assert edit.status_code == 409  # not while running

    assert (await client.put(url, headers=org["admin"], json={"action": "stop"})).json()[
        "status"
    ] == "stopped"
    resp = await client.put(url, headers=org["admin"], json={"action": "resume"})
    assert resp.status_code == 409
    resp = await _upload(client, org, campaign["id"], csv_rows(1, start=50))
    assert resp.status_code == 409  # no uploads into a stopped campaign


async def test_future_start_goes_to_scheduled(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    campaign = await _campaign(client, org, start_at="2099-01-01T09:00:00+05:30")
    await _upload(client, org, campaign["id"], csv_rows(1))
    resp = await client.put(
        f"/api/v1/campaigns/{campaign['id']}/status", headers=org["admin"], json={"action": "start"}
    )
    assert resp.json()["status"] == "scheduled"


async def test_validation_errors_name_the_field(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    org = await make_org(client, superadmin, "Org A")
    resp = await client.post(
        f"/api/v1/workspaces/{org['ws']['id']}/campaigns",
        headers=org["admin"],
        json={
            "name": "Bad",
            "agent_id": org["agent"]["id"],
            "connection_id": org["conn"]["id"],
            "attempts_per_second": 0,
            "calling_window": {
                "timezone": "Mars/Base",
                "days": [9],
                "start": "18:00",
                "end": "09:00",
            },
        },
    )
    assert resp.status_code == 422
    fields = {e["field"] for e in resp.json()["errors"]}
    assert "attempts_per_second" in fields
    assert any(f.startswith("calling_window") for f in fields)
