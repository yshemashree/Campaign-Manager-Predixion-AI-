import httpx

from tests.integration.conftest import login, make_org


async def test_login_rejects_wrong_password(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "nope"}
    )
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_requests_need_a_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/workspaces")).status_code == 401


async def test_org_admin_sees_only_own_org(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    a = await make_org(client, superadmin, "Org A")
    b = await make_org(client, superadmin, "Org B")

    # B's admin can't see A's workspace, agent or org: 404, so existence isn't revealed.
    assert (
        await client.get(f"/api/v1/workspaces/{a['ws']['id']}", headers=b["admin"])
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/agents/{a['agent']['id']}", headers=b["admin"])
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/organizations/{a['org']['id']}", headers=b["admin"])
    ).status_code == 404
    listed = (await client.get("/api/v1/workspaces", headers=b["admin"])).json()
    assert [w["id"] for w in listed] == [b["ws"]["id"]]

    # Org admins can't change org limits; only superadmins can.
    resp = await client.patch(
        f"/api/v1/organizations/{b['org']['id']}",
        headers=b["admin"],
        json={"max_concurrent_calls": 99},
    )
    assert resp.status_code == 403


async def test_members_see_only_their_workspaces(
    client: httpx.AsyncClient, superadmin: dict[str, str]
) -> None:
    a = await make_org(client, superadmin, "Org A")
    other_ws = (
        await client.post("/api/v1/workspaces", headers=a["admin"], json={"name": "Other"})
    ).json()
    resp = await client.post(
        "/api/v1/users",
        headers=a["admin"],
        json={
            "email": "member@orga.example.com",
            "password": "password123",
            "role": "member",
            "workspace_ids": [a["ws"]["id"]],
        },
    )
    assert resp.status_code == 201, resp.text
    member = await login(client, "member@orga.example.com", "password123")

    me = (await client.get("/api/v1/auth/me", headers=member)).json()
    assert me["workspace_ids"] == [a["ws"]["id"]]
    assert (
        await client.get(f"/api/v1/workspaces/{other_ws['id']}", headers=member)
    ).status_code == 404
    # Members can run campaigns but not register agents.
    resp = await client.post(
        f"/api/v1/workspaces/{a['ws']['id']}/agents",
        headers=member,
        json={"name": "Agent X", "app_id": "x", "app_version": 1},
    )
    assert resp.status_code == 403


async def test_api_key_is_write_only(client: httpx.AsyncClient, superadmin: dict[str, str]) -> None:
    a = await make_org(client, superadmin, "Org A")
    ws = (await client.get(f"/api/v1/workspaces/{a['ws']['id']}", headers=a["admin"])).json()
    assert ws["sarvam_api_key_last4"] == "1234"
    assert "key-1234" not in str(ws)
