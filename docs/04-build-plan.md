# 4. Build Plan (day by day)

> Each day ends with something that **runs**, **has tests**, and that you can **explain**. The order is chosen to retire the biggest risks first and to keep the UI from being rebuilt as the APIs change.

---

## Status

- **Done:** Days 1 to 4 are built, tested and pushed to `main`: the backend, the execution engine, mock Sarvam, live updates (SSE), the tests (69 backend, 5 mock), the API docs (`docs/api/`), the `prove_limits` tool (`make prove`) and CI. That covers the backend work this plan spread over Days 1 to 8, plus the load proof and the OpenAPI/Postman export from Days 11 and 12.
- **Finishing now:** the React web UI (Days 9 and 10).
- **Remaining:** the demo video.
- **Not built from the plan:** the audit log and `/metrics` (Day 8).
- **Changed from the plan:** "concurrency" turned out to mean calls running at the same time (confirmed by the company by email), so each org now has two limits enforced together; only mock calls are allowed, so there is no real Sarvam call; the rate margin is 100 ms after a real-stack load test (`02` §B.5).

The rest of this document is the original plan, kept as the record, with ✅ on the parts that are done.

## 4.1 Milestones and why they come in this order

| Milestone | Days | Outcome | Status |
| --- | --- | --- | --- |
| **M0 Design** | Day 0 | Problem understood, architecture fixed, decisions recorded, plan agreed | ✅ |
| **M1 Foundations** | Days 1 to 2 | One-command stack, CI, auth, multi-tenancy, roles | ✅ |
| **M2 Campaign domain** | Days 3 to 4 | Agents, connections, campaigns, state machine, calling-window maths, cohort upload | ✅ |
| **M3 Execution engine** | Days 5 to 7 | mock-sarvam, Sarvam client, rate gate, scheduler, dispatcher, webhooks, retries, crash recovery | ✅ (plus the concurrent-call limit) |
| **M4 Visibility and UI** | Days 8 to 10 | Live status (SSE), stats, full frontend | ✅ live status and stats; UI finishing now |
| **M5 Proof and delivery** | Days 11 to 12 | Load and failure drills, docs, OpenAPI/Postman, demo video | ✅ load proof, docs, OpenAPI/Postman; demo video remains |
| Buffer and stretch | Day 13 | Slack for surprises; stretch goals by priority | |

**Why this order?**

1. **API first, UI later.** The brief requires every feature through REST, so the UI is just another client. Building it after the APIs settle avoids rework.
2. **Engine before UI.** The engine (M3) is the riskiest part and the most heavily graded (the four questions). Doing it in the middle leaves time to harden it.
3. **Mock before engine.** We can't build or test a dispatcher without something to dispatch *to*. mock-sarvam also becomes the independent referee for the rate limit.
4. **Pure logic before I/O.** Calling windows and transitions (Day 3) are pure functions with property tests, so the engine (Days 6 to 7) builds on proven pieces.

---

## 4.2 Day by day

### Day 0: Understand and design ✅
- **Built:** `docs/01` problem understanding and assumptions, `docs/02` architecture (HLD + LLD), `docs/03` tech decisions, `docs/04` this plan.
- **Done when:** you can explain the four questions and the main design choices in your own words.

### Day 1: Foundations and one-command setup ✅
- **Build:** monorepo layout (`backend/`, `frontend/`, `mock_sarvam/`, `docs/`); `docker-compose.yml` with Postgres, Redis, API, worker, web and mock-sarvam, all with healthchecks; FastAPI app factory, settings (`pydantic-settings`), structured logging, DB and Redis clients, `/healthz` and `/readyz`; Alembic setup; `Makefile` (`up`, `down`, `test`, `lint`, `migrate`, `seed`); uv + ruff + mypy + pytest; GitHub Actions CI (lint + tests against service containers); `.env.example`.
- **How:** containers start in dependency order using healthchecks (not sleeps); migrations run as a one-shot service before the API starts.
- **Done when:** `docker compose up --build` gives a healthy API, a worker logging heartbeats and a placeholder web page, and CI is green.
- **You'll learn:** compose service graph, config flow (env → settings), liveness vs readiness.

### Day 2: Multi-tenancy, auth and roles ✅
- **Build:** tables for organisations, workspaces, users and memberships (+ migration); argon2id hashing; JWT login and `/auth/me`; `TenantContext` dependency; role guards (superadmin / org_admin / member); superadmin seeded from env; org, workspace and user CRUD; encrypted Sarvam credentials (AES-256-GCM, write-only); RFC 9457 error format.
- **Tests:** isolation (Org A can't read Org B: 404), members limited to their workspaces, write-only API keys, password hashing and token tampering.
- **Done when:** superadmin creates an org and its admin → the admin creates a workspace and a member → the member sees only their workspace.
- **You'll learn:** why tenant scoping is enforced in one place, and why 404 beats 403 for foreign ids.

### Day 3: Agents, connections, campaigns and the state machine ✅
- **Build:** agents with a variable schema; connections and caller numbers; campaign CRUD with strict validation (APS 0.1 to 500, `start_at < end_at`, window shape, retry policy shape, caller numbers ⊆ connection); `domain/states.py` transition tables + the conditional-update helper; `PUT /campaigns/{id}/status` (the gate is wired in on Day 6); `domain/windows.py` (`window_end`, `next_allowed`).
- **Tests:** lifecycle rules through the API (a repeated action is an idempotent 200, illegal moves are 409, start needs contacts, edits only while paused), a future start goes to `scheduled`, field-level validation errors; Hypothesis property tests for windows, plus fixed DST cases.
- **Done when:** create → start → pause → resume → stop works through the API, and the window tests pass across time zones.
- **You'll learn:** compare-and-set state machines; why time maths must be pure and property-tested.

### Day 4: Cohort upload ✅
- **Build:** `GET /agents/{id}/sample-cohort.csv`; streaming validator (file → header → row); E.164 normalisation; de-dupe in the file and against the campaign; `dry_run` and `skip_invalid` modes; `COPY` into a temp table + `INSERT ... ON CONFLICT DO NOTHING`; downloadable error report (formula-injection safe); cohort listing; contacts list with filters + keyset pagination; contact detail.
- **Tests:** good file, each kind of bad row, duplicates, BOM, the row limit, wrong headers, dry run, keyset paging.
- **Done when:** a 100k-row file validates and imports in seconds, and a broken file returns precise row-level errors.
- **You'll learn:** streaming vs loading, why `COPY` is so much faster, keyset vs offset pagination.

### Day 5: mock-sarvam and the Sarvam client ✅
- **Build:** mock-sarvam (same endpoint and payload contract, API-key check, simulated calls with a configurable outcome mix and durations, `MOCK_SPEED` to shorten calls (10 in the compose file), webhook delivery with retries, fault injection by env vars: `MOCK_FAIL_5XX_RATE` (503s), `MOCK_WEBHOOK_DROP_RATE`, `MOCK_WEBHOOK_DUP_RATE`, all changeable at runtime with `PATCH /config`); **the referee** at `GET /stats`: per org, `max_calls_in_any_rolling_second` and `max_concurrent_calls`. Our client: payload builder, HMAC metadata, `httpx` with timeouts, error classification (`02` §B.16).
- **Done when:** one mock call ends with a webhook we can read, and every error class is handled as in `02` §B.16 (the 503 path is exercised by `make prove` with injected faults).
- **You'll learn:** "was the call placed?" as the central question of error handling; why we test against a fake with fault injection.

### Day 6: Engine I, the rate gate and the scheduler ✅
- **Build:** `reserve.lua`, `refund.lua`, `fire.lua`, `release.lua`, `cooldown.lua`, `sync_campaign.lua`, `sync_org.lua` + a Python wrapper (`engine/gate.py`); the scheduler with leader election and the first reconcile steps (sync org gates with the cold-start guard, activate scheduled campaigns, sync campaign gates + the runnable map); lifecycle actions now write the versioned gate. The gate also enforces the concurrent-call limit with an in-flight set per org.
- **Tests (real Redis):** 25 parallel reservers never get past a concurrency cap of 3; releasing frees a place; consecutive slots are exactly T apart, so no rolling second holds more than N; a slow campaign leaves org slots to others; versioned sync race (a stale scheduler write can't undo a pause); pause between reserve and fire stops the call; a limit change invalidates old bookings; a late fire is refused; reaper vs fire race has one winner; one phone is never called twice at once; a closed window or missing limits fail closed.
- **Done when:** the gate tests prove the limit, and pausing flips the gate even when it races the scheduler.
- **You'll learn:** atomicity in Redis, GCRA, reservations vs polling, fencing tokens.

### Day 7: Engine II, dispatcher, webhooks, retries and recovery ✅
- **Build:** the slot loop; claim / release / record SQL; `POST /webhooks/sarvam` (HMAC, dedupe, transactional apply); `retry_policy.decide` + window alignment; the remaining scheduler steps (finish, finalise in batches, reap leases with send markers, reap lost attempts, sweep webhooks); cross-campaign phone lock; auto-pause rules; an **invariant check** (built as `make prove`, which checks one placed call per contact against the mock's own count).
- **Tests:** engine end-to-end with two dispatchers and a fake Sarvam referee: every webhook sent twice is applied once, busy numbers are retried, both org limits hold, two orgs keep separate limits, pause stops new calls and resume finishes, a stopped campaign cancels the rest. A retry landing outside the window moves to the next window (unit test).
- **Done when:** a 1,000-contact campaign runs end to end against the mock with 3 workers; the referee shows ≤ limit; `docker kill` on a worker mid-run → no `attempt_ref` received twice, every contact terminal.
- **Result:** built and tested as above. The real-stack load runs are recorded under Day 11.
- **You'll learn:** `SKIP LOCKED`, leases, at-most-once per attempt, idempotent consumers.

### Day 8: Live status and stats ✅ (except the audit log and `/metrics`)
- **Build:** publish-after-commit events; SSE endpoint with 250 ms coalescing; `GET /campaigns/{id}/stats` (1 s cache); org rate series endpoint; audit log for lifecycle and limit changes; `/metrics`.
- **Result:** events, SSE (with a `stats` snapshot every 5 s), stats and `GET /organizations/{id}/rate` are built. Stats needed no cache: a `GROUP BY` on an index is fast enough. The audit log and `/metrics` are not built.
- **Done when:** `curl -N` on the SSE endpoint streams live events during a run, and the stats match the database.
- **You'll learn:** push vs pull, why pub/sub needs a snapshot fallback, coalescing.

### Day 9: Frontend I, shell and setup screens (finishing now)
- **Build:** Vite + TS + Tailwind + shadcn/ui scaffold; a typed API client generated from OpenAPI; login, token handling and role-based routes; layout and navigation; **superadmin**: organisations list, create, edit both org limits; **org admin**: workspaces (+ Sarvam credentials), users, agents (variable editor), connections and caller numbers.
- **Done when:** every setup flow works in the browser, with server validation errors shown on the right fields.
- **You'll learn:** server-state caching (TanStack Query), typed contracts from OpenAPI.

### Day 10: Frontend II, campaigns and the live dashboard (finishing now)
- **Build:** campaigns list (status chips, progress bars); create wizard (agent → numbers → pace and retries → schedule and window → review, with a hint like "effective pace: 5/s, capped by org limit"); campaign detail: live counters and progress over SSE, start/pause/resume/stop with confirmations, contacts table (filter, search, infinite scroll, live row updates), attempt-history drawer; cohort upload (sample download, dry-run report, error CSV); **org rate chart** (the flat line at the limit).
- **Done when:** the whole demo script can be run from the UI alone.
- **You'll learn:** live UIs without hammering the backend.

### Day 11: Proof and hardening (load proof ✅)
- **Build:** a load scenario (2 orgs with limits 5 and 10, 3 campaigns, 5k contacts, 3 workers); failure drills (kill a worker, restart Redis, restart Postgres) each followed by the invariant checker; performance pass (`EXPLAIN ANALYZE` on hot queries, autovacuum settings for `contacts`); security pass (tenant tests, secrets never logged, CSV injection, login throttling).
- **Done when:** all drills pass, the referee shows **zero violations**, and dispatch overhead p99 is measured and documented.
- **Result so far:** `make prove` runs a campaign on the real stack and prints the mock's referee numbers against both limits. All runs pass: 200 contacts at 15 concurrent / 5 per second observed 15 / 5; 300 at 40 / 10 observed 40 / 10; 150 at 20 / 6 with 10% injected 503s and 30% duplicate webhooks observed 17 / 6 with exactly 150 calls placed. CI runs a smaller proof on every push. An early run found 6 calls in one second at a limit of 5 with a 50 ms margin, which led to the 100 ms margin (`02` §B.5).

### Day 12: Docs, API collection and demo (docs and API collection ✅, video remains)
- **Build:** final README (one-command quickstart, architecture diagram, decisions and trade-offs, assumptions, known limitations); exported `openapi.json` + Postman collection (`make api-docs` writes `docs/api/`); demo script; record the video.
- **Done when:** a fresh clone + one command reproduces the demo.

### Day 13: Buffer and stretch goals (in priority order)
1. Postgres Row-Level Security as a second tenant-isolation layer.
2. `Idempotency-Key` support on create endpoints.
3. Per-org cap on simultaneous live calls. ✅ Moved into the core engine once the company confirmed this is what concurrency means.
4. Upload column mapping (the "transformation file" in Sarvam's API).
5. Holiday calendars / multiple windows per day.
6. Playwright smoke tests; Grafana dashboard.

---

## 4.3 How each day works

1. I build that day's slice **with tests**.
2. I explain **what** was built, **why** it is built that way, and **how to verify it yourself** (exact commands).
3. You review and run it, then commit and push it yourself, using the short, plain commit messages I suggest.
4. If a decision changes, the docs change in the same commit, so docs and code never disagree.

## 4.4 Your action items before Day 5 (Sarvam account)

None. The assignment allows only mock calls, so the system never calls the real Sarvam API and needs no real org id, workspace id, API key, agent, connection or caller number. The seed data and `make prove` use made-up values that the mock accepts.

## 4.5 Risk register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Sarvam's real webhook payload differs from its docs | Outcomes not parsed | Tolerant adapter in one file; raw events always stored; the mock follows Sarvam's documented payload |
| The mock can't reach our webhook | No outcomes | `PUBLIC_BASE_URL` setting (`http://api:8000` inside compose) |
| Time-zone / DST bugs | Calls outside allowed hours | Pure functions + property tests (Day 3); the gate enforces the window end in ms |
| Engine races | Double calls or stuck contacts | Compare-and-set everywhere, unique constraints, gate race tests, the `make prove` check of one call per contact, chaos drills (Days 7, 11) |
| Network jitter between our send and Sarvam's count | One call too many in a second | Safety margin in the pacing, raised from 50 ms to 100 ms after a real-stack load test caught exactly this |
| UI scope creep | Late delivery | UI scoped to the demo script; stretch list kept separate |
