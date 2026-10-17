# 4. Build Plan (day by day)

> Each day ends with something that **runs**, **has tests**, and that you can **explain**. The order is chosen to retire the biggest risks first and to keep the UI from being rebuilt as the APIs change.

---

## 4.1 Milestones and why they come in this order

| Milestone | Days | Outcome |
| --- | --- | --- |
| **M0 Design** | Day 0 (today) | Problem understood, architecture fixed, decisions recorded, plan agreed |
| **M1 Foundations** | Days 1–2 | One-command stack, CI, auth, multi-tenancy, roles |
| **M2 Campaign domain** | Days 3–4 | Agents, connections, campaigns, state machine, calling-window maths, cohort upload |
| **M3 Execution engine** | Days 5–7 | mock-sarvam, Sarvam client, rate gate, scheduler, dispatcher, webhooks, retries, crash recovery |
| **M4 Visibility and UI** | Days 8–10 | Live status (SSE), stats, full frontend |
| **M5 Proof and delivery** | Days 11–12 | Load and failure drills, docs, OpenAPI/Postman, demo video |
| Buffer and stretch | Day 13 | Slack for surprises; stretch goals by priority |

**Why this order?**

1. **API first, UI later.** The brief requires every feature through REST, so the UI is just another client. Building it after the APIs settle avoids rework.
2. **Engine before UI.** The engine (M3) is the riskiest part and the most heavily graded (the four questions). Doing it in the middle leaves time to harden it.
3. **Mock before engine.** We can't build or test a dispatcher without something to dispatch *to*. mock-sarvam also becomes the independent referee for the rate limit.
4. **Pure logic before I/O.** Calling windows and transitions (Day 3) are pure functions with property tests, so the engine (Days 6–7) builds on proven pieces.

---

## 4.2 Day by day

### Day 0: Understand and design ✅ (today)
- **Built:** `docs/01` problem understanding and assumptions, `docs/02` architecture (HLD + LLD), `docs/03` tech decisions, `docs/04` this plan.
- **Done when:** you can explain the four questions and the main design choices in your own words.

### Day 1: Foundations and one-command setup
- **Build:** monorepo layout (`backend/`, `frontend/`, `mock_sarvam/`, `docs/`); `docker-compose.yml` with Postgres, Redis, API, worker, web and mock-sarvam, all with healthchecks; FastAPI app factory, settings (`pydantic-settings`), structured logging, DB and Redis clients, `/healthz` and `/readyz`; Alembic setup; `Makefile` (`up`, `down`, `test`, `lint`, `migrate`, `seed`); uv + ruff + mypy + pytest; GitHub Actions CI (lint + tests against service containers); `.env.example`.
- **How:** containers start in dependency order using healthchecks (not sleeps); migrations run as a one-shot service before the API starts.
- **Done when:** `docker compose up --build` gives a healthy API, a worker logging heartbeats and a placeholder web page, and CI is green.
- **You'll learn:** compose service graph, config flow (env → settings), liveness vs readiness.

### Day 2: Multi-tenancy, auth and roles
- **Build:** tables for organisations, workspaces, users and memberships (+ migration); argon2id hashing; JWT login and `/auth/me`; `TenantContext` dependency; role guards (superadmin / org_admin / member); superadmin seeded from env; org, workspace and user CRUD; encrypted Sarvam credentials (AES-256-GCM, write-only); RFC 9457 error format.
- **Tests:** isolation (Org A can't read Org B: 404), the role matrix, password and token edge cases.
- **Done when:** superadmin creates an org and its admin → the admin creates a workspace and a member → the member sees only their workspace.
- **You'll learn:** why tenant scoping is enforced in one place, and why 404 beats 403 for foreign ids.

### Day 3: Agents, connections, campaigns and the state machine
- **Build:** agents with a variable schema; connections and caller numbers; campaign CRUD with strict validation (APS 0.1–500, `start_at < end_at`, window shape, retry policy shape, caller numbers ⊆ connection); `domain/states.py` transition tables + the conditional-update helper; `PUT /campaigns/{id}/status` (the gate is wired in on Day 6); `domain/windows.py` (`window_end`, `next_allowed`).
- **Tests:** every legal and illegal transition (200 / idempotent 200 / 409); Hypothesis property tests for windows, plus fixed DST cases.
- **Done when:** create → start → pause → resume → stop works through the API, and the window tests pass across time zones.
- **You'll learn:** compare-and-set state machines; why time maths must be pure and property-tested.

### Day 4: Cohort upload
- **Build:** `GET /agents/{id}/sample-cohort.csv`; streaming validator (file → header → row); E.164 normalisation; de-dupe in the file and against the campaign; `dry_run` and `skip_invalid` modes; `COPY` into a temp table + `INSERT ... ON CONFLICT DO NOTHING`; downloadable error report (formula-injection safe); cohort listing; contacts list with filters + keyset pagination; contact detail.
- **Tests:** good file, each kind of bad row, duplicates, BOM, huge file, wrong headers.
- **Done when:** a 100k-row file validates and imports in seconds, and a broken file returns precise row-level errors.
- **You'll learn:** streaming vs loading, why `COPY` is so much faster, keyset vs offset pagination.

### Day 5: mock-sarvam and the Sarvam client
- **Build:** mock-sarvam (same endpoint and payload contract, API-key check, simulated calls with a configurable outcome mix and durations, webhook delivery with optional delay / duplicate / drop, 5xx and timeout injection); **the referee**: a per-org arrival log, max calls in any rolling second, and a violation counter at `GET /stats`. Our client: payload builder, HMAC metadata, `httpx` with timeouts, error classification (`02` §B.16).
- **Optional:** one real call to Sarvam with your credentials (needs a public webhook URL, e.g. a cloudflared/ngrok tunnel).
- **Done when:** every error class has a test, and one mock call, plus one real call if ready, ends with a webhook we can read.
- **You'll learn:** "was the call placed?" as the central question of error handling; why we test against a fake with fault injection.

### Day 6: Engine I, the rate gate and the scheduler
- **Build:** `reserve.lua`, `refund.lua`, `fire.lua`, `sync_gate.lua` + a Python wrapper; the scheduler with leader election and reconcile steps 1–3 (activate, sync campaign gates + the runnable map, sync org gates with the cold-start guard); lifecycle actions now write the versioned gate.
- **Tests:** **3 processes × 200 concurrent requesters → every grant ≥ T apart**; fencing race (a stale scheduler write is rejected); window cutoff at millisecond precision; limit change invalidates old reservations.
- **Done when:** the gate tests prove the limit, and pausing flips the gate even when it races the scheduler.
- **You'll learn:** atomicity in Redis, GCRA, reservations vs polling, fencing tokens.

### Day 7: Engine II, dispatcher, webhooks, retries and recovery
- **Build:** the slot loop; claim / release / record SQL; `POST /webhooks/sarvam` (HMAC, dedupe, transactional apply); `retry_policy.decide` + window alignment; scheduler steps 4–8 (finish, finalise in batches, reap leases with send markers, reap lost attempts, sweep webhooks); cross-campaign phone lock; auto-pause rules; an **invariant-checker** script.
- **Tests:** webhook replayed 3× is applied once; webhook before `record_dispatch`; a retry landing outside the window moves to the next window; a stopped campaign cancels the rest.
- **Done when:** a 1,000-contact campaign runs end to end against the mock with 3 workers; the referee shows ≤ limit; `docker kill` on a worker mid-run → no `attempt_ref` received twice, every contact terminal.
- **You'll learn:** `SKIP LOCKED`, leases, at-most-once per attempt, idempotent consumers.

### Day 8: Live status and stats
- **Build:** publish-after-commit events; SSE endpoint with 250 ms coalescing; `GET /campaigns/{id}/stats` (1 s cache); org rate series endpoint; audit log for lifecycle and limit changes; `/metrics`.
- **Done when:** `curl -N` on the SSE endpoint streams live events during a run, and the stats match the database.
- **You'll learn:** push vs pull, why pub/sub needs a snapshot fallback, coalescing.

### Day 9: Frontend I, shell and setup screens
- **Build:** Vite + TS + Tailwind + shadcn/ui scaffold; a typed API client generated from OpenAPI; login, token handling and role-based routes; layout and navigation; **superadmin**: organisations list, create, edit rate limit; **org admin**: workspaces (+ Sarvam credentials), users, agents (variable editor), connections and caller numbers.
- **Done when:** every setup flow works in the browser, with server validation errors shown on the right fields.
- **You'll learn:** server-state caching (TanStack Query), typed contracts from OpenAPI.

### Day 10: Frontend II, campaigns and the live dashboard
- **Build:** campaigns list (status chips, progress bars); create wizard (agent → numbers → pace and retries → schedule and window → review, with a hint like "effective pace: 5/s, capped by org limit"); campaign detail: live counters and progress over SSE, start/pause/resume/stop with confirmations, contacts table (filter, search, infinite scroll, live row updates), attempt-history drawer; cohort upload (sample download, dry-run report, error CSV); **org rate chart** (the flat line at the limit).
- **Done when:** the whole demo script can be run from the UI alone.
- **You'll learn:** live UIs without hammering the backend.

### Day 11: Proof and hardening
- **Build:** a load scenario (2 orgs with limits 5 and 10, 3 campaigns, 5k contacts, 3 workers); failure drills (kill a worker, restart Redis, restart Postgres) each followed by the invariant checker; performance pass (`EXPLAIN ANALYZE` on hot queries, autovacuum settings for `contacts`); security pass (tenant tests, secrets never logged, CSV injection, login throttling).
- **Done when:** all drills pass, the referee shows **zero violations**, and dispatch overhead p99 is measured and documented.

### Day 12: Docs, API collection and demo
- **Build:** final README (one-command quickstart, architecture diagram, decisions and trade-offs, assumptions, known limitations); exported `openapi.json` + Postman collection; demo script; record the video.
- **Done when:** a fresh clone + one command reproduces the demo.

### Day 13: Buffer and stretch goals (in priority order)
1. Postgres Row-Level Security as a second tenant-isolation layer.
2. `Idempotency-Key` support on create endpoints.
3. Per-org cap on simultaneous live calls.
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

- [ ] Create a Sarvam account; note **org id**, **workspace id**, **API key**.
- [ ] Create or choose an **agent**: note `app_id`, `app_version` and the **variables** it uses.
- [ ] Note a **connection id** and at least one **caller number**.
- [ ] (Optional, for real webhooks) install **cloudflared** or **ngrok** to expose your local webhook URL.

Everything works against mock-sarvam without these. They are only needed for the real-call smoke test.

## 4.5 Risk register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Real webhook payload differs from the docs | Outcomes not parsed | Tolerant adapter in one file; raw events always stored; early real smoke test (Day 5) |
| Real webhooks need a public URL | No outcomes in local dev | Tunnel + `PUBLIC_BASE_URL` setting; the mock needs none |
| Time-zone / DST bugs | Calls outside allowed hours | Pure functions + property tests (Day 3); the gate enforces the window end in ms |
| Engine races | Double calls or stuck contacts | Compare-and-set everywhere, unique constraints, invariant checker, chaos drills (Days 7, 11) |
| UI scope creep | Late delivery | UI scoped to the demo script; stretch list kept separate |
| Sarvam credentials or credits not ready | No real call in the demo | The entire system and demo run against mock-sarvam |
