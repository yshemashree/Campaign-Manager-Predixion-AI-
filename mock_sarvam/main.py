"""Mock Sarvam outbound API.

Stands in for POST /api/outbounds/v1/orgs/{org_id}/workspaces/{workspace_id}/outbounds so the
Campaign Manager can be developed, tested and load-tested without placing real calls.

What it does:
  * accepts the same request body as Sarvam and returns an attempt_id
  * simulates the call (ringing, talking) and its outcome, then POSTs a Sarvam-style webhook
  * can inject faults: 5xx responses, dropped or duplicated webhooks
  * acts as an independent referee: for each org it records every request it receives and
    reports the most calls seen in any rolling second and the most calls live at once

Endpoints besides the outbound one:
  GET  /stats        per-org measurements
  POST /stats/reset  clear measurements
  GET  /config       current simulation settings
  PATCH /config      change settings at runtime (e.g. outcome mix, fault rates, speed)
"""

import asyncio
import os
import random
import time
import uuid
from collections import Counter, deque
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


class SimConfig(BaseModel):
    # Divides all simulated durations: 10 means calls take a tenth of the time.
    speed: float = Field(default=_env_float("MOCK_SPEED", 1.0), gt=0)
    ring_min_s: float = 1.0
    ring_max_s: float = 4.0
    talk_min_s: float = 15.0
    talk_max_s: float = 90.0
    # Relative weights of each outcome.
    outcomes: dict[str, float] = {
        "connected": 0.6,
        "short": 0.05,
        "no_answer": 0.2,
        "busy": 0.1,
        "failed": 0.05,
    }
    fail_5xx_rate: float = Field(default=_env_float("MOCK_FAIL_5XX_RATE", 0.0), ge=0, le=1)
    webhook_drop_rate: float = Field(default=_env_float("MOCK_WEBHOOK_DROP_RATE", 0.0), ge=0, le=1)
    webhook_dup_rate: float = Field(default=_env_float("MOCK_WEBHOOK_DUP_RATE", 0.0), ge=0, le=1)
    accept_latency_ms: float = 40.0


class OrgStats:
    def __init__(self) -> None:
        self.total_requests = 0
        self.window: deque[float] = deque()  # arrival times within the last second
        self.max_in_any_rolling_second = 0
        self.active = 0
        self.max_concurrent = 0
        self.outcomes: Counter[str] = Counter()
        self.webhooks_sent = 0
        self.webhooks_failed = 0
        self.rejected_5xx = 0

    def arrive(self, now: float) -> None:
        self.total_requests += 1
        self.window.append(now)
        while self.window and now - self.window[0] >= 1.0:
            self.window.popleft()
        self.max_in_any_rolling_second = max(self.max_in_any_rolling_second, len(self.window))

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "max_calls_in_any_rolling_second": self.max_in_any_rolling_second,
            "max_concurrent_calls": self.max_concurrent,
            "active_calls": self.active,
            "outcomes": dict(self.outcomes),
            "webhooks_sent": self.webhooks_sent,
            "webhooks_failed": self.webhooks_failed,
            "rejected_5xx": self.rejected_5xx,
        }


config = SimConfig()
stats: dict[str, OrgStats] = {}
_client: httpx.AsyncClient | None = None
_tasks: set[asyncio.Task[None]] = set()

app = FastAPI(title="Mock Sarvam", version="0.2.0")


class ConnectionConfig(BaseModel):
    connection_id: str
    agent_phone_number: str


class AppConfig(BaseModel):
    app_id: str
    app_version: int
    app_type: str = "agent"
    connection_config: ConnectionConfig
    agent_variables: dict[str, Any] = {}
    app_overrides: dict[str, Any] | None = None


class UserConfig(BaseModel):
    user_phone_number: str


class WebhookConfig(BaseModel):
    url: str
    metadata: dict[str, Any] = {}


class OutboundRequest(BaseModel):
    app_config: AppConfig
    user_config: UserConfig
    webhook_config: WebhookConfig


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10)
    return _client


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/outbounds/v1/orgs/{org_id}/workspaces/{workspace_id}/outbounds")
async def outbound(
    org_id: str,
    workspace_id: str,
    body: OutboundRequest,
    x_api_key: str | None = Header(default=None),
) -> dict[str, str]:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    org = stats.setdefault(org_id, OrgStats())
    org.arrive(time.monotonic())
    if config.accept_latency_ms:
        await asyncio.sleep(config.accept_latency_ms / 1000)
    if random.random() < config.fail_5xx_rate:
        org.rejected_5xx += 1
        raise HTTPException(status_code=503, detail="Simulated upstream failure")

    attempt_id = str(uuid.uuid4())
    org.active += 1
    org.max_concurrent = max(org.max_concurrent, org.active)
    task = asyncio.create_task(_simulate(org, attempt_id, body))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"attempt_id": attempt_id, "status": "initiated"}


def _pick_outcome() -> str:
    names = list(config.outcomes)
    return random.choices(names, weights=[config.outcomes[n] for n in names])[0]


async def _simulate(org: OrgStats, attempt_id: str, body: OutboundRequest) -> None:
    outcome = _pick_outcome()
    ring = random.uniform(config.ring_min_s, config.ring_max_s)
    duration: int | None = None
    status = outcome
    reason = None
    if outcome == "connected":
        duration = int(random.uniform(config.talk_min_s, config.talk_max_s))
    elif outcome == "short":
        status, duration = "connected", random.randint(1, 5)
    elif outcome == "failed":
        reason = "mock-telephony: number unreachable"
    try:
        await asyncio.sleep((ring + (duration or 0)) / config.speed)
    finally:
        org.active -= 1  # the call is over
    org.outcomes[outcome] += 1

    payload = {
        "attempt_id": attempt_id,
        "status": status,
        "duration": duration,
        "interaction_id": str(uuid.uuid4()) if status == "connected" else None,
        "failure_reason": reason,
        "final_agent_variables": body.app_config.agent_variables if status == "connected" else None,
        "interaction_transcript": None,
        "webhook_config": body.webhook_config.model_dump(),
    }
    if random.random() < config.webhook_drop_rate:
        return
    copies = 2 if random.random() < config.webhook_dup_rate else 1
    for _ in range(copies):
        await _deliver(org, body.webhook_config.url, payload)


async def _deliver(org: OrgStats, url: str, payload: dict[str, Any]) -> None:
    for attempt in range(4):  # retry like a real webhook sender would
        try:
            resp = await client().post(url, json=payload)
            if resp.status_code < 500:
                org.webhooks_sent += 1
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.5 * 2**attempt)
    org.webhooks_failed += 1


@app.get("/stats")
async def get_stats() -> dict[str, Any]:
    return {org_id: s.as_dict() for org_id, s in stats.items()}


@app.post("/stats/reset")
async def reset_stats() -> dict[str, str]:
    for s in stats.values():
        active = s.active
        s.__init__()  # type: ignore[misc]
        s.active = active
    return {"status": "reset"}


@app.get("/config", response_model=SimConfig)
async def get_config() -> SimConfig:
    return config


@app.patch("/config", response_model=SimConfig)
async def update_config(changes: dict[str, Any]) -> SimConfig:
    global config
    config = SimConfig(**{**config.model_dump(), **changes})
    return config
