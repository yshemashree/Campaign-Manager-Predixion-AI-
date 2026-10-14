"""Container healthchecks, used by docker compose. Standard library only.

    python -m app.healthcheck api      # the API answers /healthz
    python -m app.healthcheck worker   # the worker wrote a heartbeat recently

Exit code 0 means healthy, 1 means unhealthy.
"""

import sys
import time
import urllib.request
from pathlib import Path

from app.core.config import get_settings


def check_api() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=3) as resp:
            return bool(resp.status == 200)
    except OSError:
        return False


def check_worker() -> bool:
    settings = get_settings()
    path = Path(settings.worker_heartbeat_file)
    try:
        last_beat = float(path.read_text())
    except (OSError, ValueError):
        return False
    # Healthy if a heartbeat landed within the last three intervals.
    return time.time() - last_beat < settings.worker_heartbeat_interval_s * 3


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "api"
    checks = {"api": check_api, "worker": check_worker}
    if target not in checks:
        sys.exit(f"unknown target {target!r}; use one of {sorted(checks)}")
    sys.exit(0 if checks[target]() else 1)
