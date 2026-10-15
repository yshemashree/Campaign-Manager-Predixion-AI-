"""The only external call: Sarvam's outbound API (the mock server, in this project).

The key question for every failure is "could the call have been placed?":
    not_sent      not placed: the request never left (connection refused, DNS, timeout) or 503
    rate_limited  429: not placed
    auth_error    401/403: not placed
    rejected      other 4xx: not placed, and retrying the same request won't help
    unknown       5xx, read timeout, dropped connection: it MAY have been placed
    dispatched    2xx: placed
"""

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.core.security import sign_attempt


@dataclass(frozen=True)
class CallTarget:
    """Everything needed to place calls for one campaign (cached by the dispatcher)."""

    campaign_id: uuid.UUID
    org_id: uuid.UUID
    workspace_id: uuid.UUID
    sarvam_org_id: str
    sarvam_workspace_id: str
    api_key: str
    app_id: str
    app_version: int
    connection_id: str
    caller_numbers: tuple[str, ...]
    app_overrides: dict[str, Any]


@dataclass(frozen=True)
class CallResult:
    kind: str  # dispatched | unknown | rejected | not_sent | rate_limited | auth_error
    http_status: int | None = None
    provider_attempt_id: str | None = None
    error: str | None = None
    retry_after_ms: int | None = None


def build_payload(
    settings: Settings,
    target: CallTarget,
    *,
    attempt_ref: uuid.UUID,
    phone: str,
    lead_id: str,
    variables: dict[str, Any],
    from_number: str,
) -> dict[str, Any]:
    app_config: dict[str, Any] = {
        "app_id": target.app_id,
        "app_version": target.app_version,
        "app_type": "agent",
        "connection_config": {
            "connection_id": target.connection_id,
            "agent_phone_number": from_number,
        },
        "agent_variables": {k: str(v) for k, v in variables.items()},
    }
    if target.app_overrides:
        app_config["app_overrides"] = target.app_overrides
    return {
        "app_config": app_config,
        "user_config": {"user_phone_number": phone},
        "webhook_config": {
            "url": f"{settings.public_base_url.rstrip('/')}/api/v1/webhooks/sarvam",
            # Echoed back in the webhook: lets us match the result to this exact attempt,
            # even if this worker dies before saving Sarvam's response.
            "metadata": {
                "lead_id": lead_id,
                "attempt_ref": str(attempt_ref),
                "sig": sign_attempt(settings, str(attempt_ref)),
            },
        },
    }


class SarvamClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.sarvam_base_url,
            timeout=httpx.Timeout(
                connect=settings.sarvam_connect_timeout_s,
                read=settings.sarvam_read_timeout_s,
                write=settings.sarvam_read_timeout_s,
                pool=settings.sarvam_connect_timeout_s,
            ),
            limits=httpx.Limits(max_connections=settings.dispatch_slots * 2),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def place_call(self, target: CallTarget, payload: dict[str, Any]) -> CallResult:
        path = (
            f"/api/outbounds/v1/orgs/{target.sarvam_org_id}"
            f"/workspaces/{target.sarvam_workspace_id}/outbounds"
        )
        try:
            resp = await self.client.post(path, json=payload, headers={"X-API-Key": target.api_key})
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            return CallResult("not_sent", error=f"{type(exc).__name__}: {exc}")
        except httpx.HTTPError as exc:  # read/write timeout, dropped connection, ...
            return CallResult("unknown", error=f"{type(exc).__name__}: {exc}")

        code = resp.status_code
        if 200 <= code < 300:
            try:
                provider_id = resp.json().get("attempt_id")
            except ValueError:
                provider_id = None
            return CallResult("dispatched", http_status=code, provider_attempt_id=provider_id)
        error = resp.text[:500]
        if code == 429:
            retry_after = resp.headers.get("retry-after")
            ms = int(float(retry_after) * 1000) if retry_after and retry_after.isdigit() else 1000
            return CallResult("rate_limited", http_status=code, error=error, retry_after_ms=ms)
        if code in (401, 403):
            return CallResult("auth_error", http_status=code, error=error)
        if 400 <= code < 500:
            return CallResult("rejected", http_status=code, error=error)
        if code == 503:
            # "Unavailable" means the request was turned away, so no call was placed.
            return CallResult("not_sent", http_status=code, error=error)
        # Other 5xx: the call may or may not have been placed. Never resend; wait for a webhook.
        return CallResult("unknown", http_status=code, error=error)
