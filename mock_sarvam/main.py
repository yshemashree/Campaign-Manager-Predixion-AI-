"""Mock Sarvam outbound API.

A stand-in for `POST /api/outbounds/v1/orgs/{org_id}/workspaces/{workspace_id}/outbounds`,
so the Campaign Manager can be developed, tested and load-tested without placing real calls.

Day 1: health endpoint only. The outbound endpoint, simulated call outcomes, webhooks and the
per-org request measurements arrive with the engine work.
"""

from fastapi import FastAPI

app = FastAPI(title="Mock Sarvam", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
