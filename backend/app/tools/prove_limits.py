"""Load test that proves the org limits hold, judged by the mock Sarvam server.

Creates a fresh org with the limits you choose, uploads N contacts, runs the campaign through
the real stack (API, worker, Redis, Postgres, mock Sarvam) and then asks the mock, which saw
every request, for the most calls live at once and the most calls in any rolling second.

    docker compose exec api python -m app.tools.prove_limits
    docker compose exec api python -m app.tools.prove_limits --contacts 500 --concurrent 30 --cps 8
"""

import argparse
import asyncio
import sys
import time
from typing import Any

import httpx

from app.core.config import get_settings


def _cohort(n: int, seed: int) -> str:
    lines = ["phone_number,lead_id,customer_name,emi_amount"]
    for i in range(n):
        lines.append(f"+9197{(seed * 7919 + i) % 100_000_000:08d},load-{i},Customer {i},{1000 + i}")
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> bool:
    s = get_settings()
    tag = str(int(time.time()))
    async with (
        httpx.AsyncClient(base_url=args.api, timeout=30) as api,
        httpx.AsyncClient(base_url=args.mock, timeout=10) as mock,
    ):
        login = await api.post(
            "/api/v1/auth/login",
            json={"email": s.seed_superadmin_email, "password": s.seed_superadmin_password},
        )
        login.raise_for_status()
        root = {"Authorization": f"Bearer {login.json()['access_token']}"}

        sarvam_org = f"loadtest-{tag}"
        org = await api.post(
            "/api/v1/organizations",
            headers=root,
            json={
                "name": f"Load test {tag}",
                "sarvam_org_id": sarvam_org,
                "max_concurrent_calls": args.concurrent,
                "max_calls_per_second": args.cps,
                "admin_email": f"loadtest-{tag}@example.com",
                "admin_password": "loadtest123",
            },
        )
        org.raise_for_status()
        login = await api.post(
            "/api/v1/auth/login",
            json={"email": f"loadtest-{tag}@example.com", "password": "loadtest123"},
        )
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        async def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
            resp = await api.post(path, headers=h, json=body)
            resp.raise_for_status()
            return dict(resp.json())

        ws = await post(
            "/api/v1/workspaces",
            {"name": "Load", "sarvam_workspace_id": "load-ws", "sarvam_api_key": "load-key-0000"},
        )
        agent = await post(
            f"/api/v1/workspaces/{ws['id']}/agents",
            {
                "name": "Load agent",
                "app_id": "load-app",
                "app_version": 1,
                "variables": [
                    {"name": "customer_name", "type": "string"},
                    {"name": "emi_amount", "type": "number"},
                ],
            },
        )
        conn = await post(
            f"/api/v1/workspaces/{ws['id']}/connections",
            {
                "name": "Load line",
                "connection_id": "load-conn",
                "caller_numbers": ["+918069000101", "+918069000102", "+918069000103"],
            },
        )
        campaign = await post(
            f"/api/v1/workspaces/{ws['id']}/campaigns",
            {
                "name": f"Load test ({args.contacts} contacts)",
                "agent_id": agent["id"],
                "connection_id": conn["id"],
                "attempts_per_second": args.cps,
                "retry_policy": {"max_attempts": 1},
                "calling_window": {
                    "timezone": "UTC",
                    "days": [1, 2, 3, 4, 5, 6, 7],
                    "start": "00:00",
                    "end": "23:59",
                },
            },
        )
        upload = await api.post(
            f"/api/v1/campaigns/{campaign['id']}/cohorts",
            headers=h,
            files={"file": ("load.csv", _cohort(args.contacts, int(tag)).encode(), "text/csv")},
        )
        upload.raise_for_status()

        print(f"Org limits: {args.concurrent} calls at once, {args.cps} calls per second")
        print(f"Campaign {campaign['id']} with {args.contacts} contacts. Starting...\n")
        started = time.monotonic()
        resp = await api.put(
            f"/api/v1/campaigns/{campaign['id']}/status", headers=h, json={"action": "start"}
        )
        resp.raise_for_status()

        stats: dict[str, Any] = {}
        while time.monotonic() - started < args.timeout:
            await asyncio.sleep(2)
            stats = (await api.get(f"/api/v1/campaigns/{campaign['id']}/stats", headers=h)).json()
            rate = (
                await api.get(f"/api/v1/organizations/{org.json()['id']}/rate", headers=h)
            ).json()
            done = sum(stats["by_status"].get(k, 0) for k in ("completed", "failed", "cancelled"))
            print(
                f"  {time.monotonic() - started:5.0f}s  finished {done:>5}/{stats['total']}"
                f"  live calls {rate['live_calls']:>3}"
            )
            if stats["status"] == "completed":
                break
        elapsed = time.monotonic() - started

        referee = (await mock.get("/stats")).json().get(sarvam_org, {})

    peak_live = referee.get("max_concurrent_calls", 0)
    peak_rate = referee.get("max_calls_in_any_rolling_second", 0)
    # Requests the mock turned away with a 503 placed no call; those contacts were retried.
    sent = referee.get("total_requests", 0) - referee.get("rejected_5xx", 0)
    ok_live = peak_live <= args.concurrent
    ok_rate = peak_rate <= args.cps
    ok_once = sent == args.contacts
    finished = stats.get("status") == "completed"

    print("\nMeasured by the mock Sarvam server (it saw every request):")
    print(f"  {'check':<34}{'limit':>8}{'observed':>10}   result")
    print(
        f"  {'most calls live at once':<34}{args.concurrent:>8}{peak_live:>10}   {_mark(ok_live)}"
    )
    print(f"  {'most calls in any 1 s window':<34}{args.cps:>8}{peak_rate:>10}   {_mark(ok_rate)}")
    print(
        f"  {'calls placed (one per contact)':<34}{args.contacts:>8}{sent:>10}   {_mark(ok_once)}"
    )
    print(f"  {'campaign completed':<34}{'':>8}{stats.get('status', '?'):>10}   {_mark(finished)}")
    print(f"\nOutcomes: {referee.get('outcomes')}  Time: {elapsed:.0f}s")
    if referee.get("rejected_5xx"):
        print(f"Simulated 503s (not placed, sent again later): {referee['rejected_5xx']}")
    return ok_live and ok_rate and ok_once and finished


def _mark(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contacts", type=int, default=200)
    parser.add_argument("--concurrent", type=int, default=20, help="org max_concurrent_calls")
    parser.add_argument("--cps", type=int, default=5, help="org max_calls_per_second")
    parser.add_argument("--timeout", type=int, default=600, help="give up after this many seconds")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--mock", default=get_settings().sarvam_base_url)
    ok = asyncio.run(run(parser.parse_args()))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
