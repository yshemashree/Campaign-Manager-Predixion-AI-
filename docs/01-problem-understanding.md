# 1. Understanding the Problem

> Read this first. It restates the assignment in our own words, names the parts that are actually hard, and lists every assumption we made where the brief is silent. The architecture (`02-architecture.md`) is built to answer this document.

---

## 1.1 The problem in one paragraph

A business (say, a lender) wants an AI voice agent to phone thousands of its customers: *"Hi Priya, your EMI of ₹4,500 is due on the 5th..."*. Sarvam already provides the voice agent and **one** HTTP API that places **one** outbound call. We build everything around that single call:

- **who** may run campaigns (organisations, workspaces, roles),
- **whom** to call and with what personalised data (cohort CSVs validated against the agent's variables),
- **when** calls may happen (start/end time, calling window with timezone, hours, days),
- **how fast and how many at once** (per-campaign attempts/second, plus two hard per-organisation limits set by a superadmin: calls running at the same time and calls per second),
- **what happens when nobody picks up** (retry rules),
- **what is happening right now** (live status per campaign and per contact).

All of it must work from a UI **and** from a REST API.

---

## 1.2 Actors

| Actor | What they need from the system |
| --- | --- |
| **Superadmin** (platform operator) | Onboard organisations, set each org's two limits (concurrent calls and calls per second), see everything |
| **Org admin** *(assumed role, see A14)* | Manage workspaces, users, Sarvam credentials, agents and caller numbers |
| **Org member** | Create campaigns, upload cohorts, start / pause / resume / stop, watch progress |
| **Sarvam platform** (external) | Receives one HTTP request per call; later POSTs the call outcome to our webhook |
| **Customer** (the person being called) | Called only inside allowed hours, never twice by accident, not hammered with retries |

---

## 1.3 Domain vocabulary

| Term | Meaning in this system |
| --- | --- |
| **Organisation (org)** | A tenant (a company). Owns workspaces and users. Has **two outbound limits** (concurrent calls and calls per second) shared by everything inside it. Maps to a Sarvam org id. |
| **Workspace** | A team/project space inside an org. Maps to a Sarvam workspace id (the outbound URL contains both ids). Agents, connections and campaigns live here. |
| **Agent** | A Sarvam voice agent: `app_id` + `app_version` + the list of **agent variables** it expects (e.g. `customer_name`, `emi_amount`). |
| **Connection** | A Sarvam telephony connection (`connection_id`) plus the **caller numbers** ("from" numbers) available on it. |
| **Campaign** | "Call this cohort with this agent, from these numbers, at this pace, inside this window, retrying like this." |
| **Cohort** | One uploaded CSV of customers for a campaign. A campaign can have several cohorts. |
| **Contact** | One row of a cohort: a phone number + values for the agent variables. The unit of work. |
| **Attempt** | One actual dial of a contact (one hit on Sarvam's API). A contact has 1..N attempts. |
| **Outcome** | What happened on an attempt: completed, busy, no answer, short call, failed, lost. |
| **Calling window** | Timezone + allowed weekdays + allowed daily hours. Calls are only placed inside it. |
| **APS** | Attempts per second: a campaign's own pace cap. |
| **Org concurrency limit** | `max_concurrent_calls`: *at most N calls running at the same time for the whole org* (reserved or live, until the outcome arrives). |
| **Org rate limit** | `max_calls_per_second`: *at most N hits on Sarvam's outbound API in any rolling second for the whole org*. |

---

## 1.4 Requirements, translated

### Functional

| # | The brief says | What it means for us | How we will prove it |
| --- | --- | --- | --- |
| F1 | Campaign creation: agent, connection + caller numbers, APS, retry rules (busy, no answer, short-duration threshold), start/end time, calling window | A validated campaign model and a create/edit wizard; config is frozen once running except for safe fields | API + UI create a campaign; invalid configs get field-level errors |
| F2 | Cohort upload; per-agent sample CSV; validate before accepting | Agents declare their variables, the sample CSV is generated from that declaration, and uploads are validated row by row before anything is stored | Download sample → fill → upload; bad rows produce a row-level error report |
| F3 | Start, pause, resume, stop; live status of campaign and every contact (pending, in progress, completed, failed, retrying, attempts made) | An explicit state machine for campaigns and contacts, plus a push channel to the UI | Buttons and `PUT /status` both work; the UI updates within about a second |
| F4 | Queueing, workers, Redis, windows, retries; outcomes via webhook | Our own execution engine. Sarvam tells us the result later, asynchronously | End-to-end campaign run against the mock Sarvam |
| F5 | Org limit N ⇒ outbound API hit **at most N times per second** for that org, whatever the number of campaigns, agents or workers | Two **global**, distributed limits checked in one atomic step: calls running at the same time (the company confirmed this is what concurrency means, see A1) and calls per second (the brief's example). Per-process limiting is wrong by construction | An independent referee (the mock Sarvam) records every request and reports, per org, the max calls in any rolling 1-second window and the max calls live at once, under load. `make prove` prints both against the limits |
| F6 | Organisations, workspaces, superadmin vs org users | Tenant isolation on every query, plus role checks | Org A's users can't see or touch Org B's data (tests) |
| F7 | Everything usable from the frontend **and** REST | API-first: the UI is just another client of the public API | OpenAPI spec + Postman collection cover every UI action |

### Non-functional targets (our own, so we can measure ourselves)

| Quality | Target |
| --- | --- |
| **Limit correctness** | 0 windows where an org exceeds its calls-per-second limit in **any** rolling 1-second interval, and 0 moments where it has more calls live than its concurrent-call limit, both measured at the receiver |
| **No accidental double calls** | 0 attempts sent twice. A crash never causes an immediate blind re-dial |
| **Completeness** | Every contact ends in a terminal state (completed / failed / cancelled). Nothing gets stuck forever |
| **Control latency** | Once the pause/stop API responds, **no new call** is sent for that campaign |
| **Dispatch overhead** | Under 5 ms p99 from "slot granted" to "request on the wire" |
| **UI freshness** | Under 1 s from a state change to the browser |
| **Webhook ack** | Under 50 ms p99 (store first, then process) |
| **Throughput headroom** | Designed for about 1,000 dials/s total on one Postgres + one Redis; scale by adding workers |
| **Fault tolerance** | Any API/worker process can die at any instant without losing or duplicating work. Losing Redis makes dispatch **stop** (fail closed), then recover by itself |

---

## 1.5 What actually makes this hard

The CRUD (campaigns, uploads, users) is routine. These eight problems are where the design effort goes:

1. **One budget, many spenders.** Several worker processes, on several machines, all dialing for the same org. A limiter inside each process can't work: 3 workers × "5/s each" = 15/s, and the same goes for a count of live calls. The limits have to be decided in **one shared place**, atomically, using **one clock**.
2. **Exactly-once delivery doesn't exist over a network.** If a worker sends the HTTP request and crashes before saving the response, we can't know whether the customer is being called. Sending again risks calling them twice; not sending risks never calling them. We need a deliberate policy (we choose **at most once per attempt**, then reconcile).
3. **Time is tricky.** Timezones, DST, weekdays, windows that close mid-batch, retries that would land at 2 a.m., campaign end times.
4. **Control must beat the data plane.** "Pause" has to take effect *now*, even though work is spread across many processes. Anything already sitting in a queue would keep calling people after the pause.
5. **Outcomes are asynchronous and come from someone else's system.** A webhook arrives seconds to minutes later. It may be duplicated, arrive before we've even saved the API response, or never arrive. We aren't allowed to call any other Sarvam API to check.
6. **Multi-tenancy is about fairness as well as isolation.** One org's 1-million-row campaign must not starve another org's 50-row campaign, and one campaign must not starve its siblings inside the same org.
7. **Bulk data with a dynamic schema.** Every agent has different variables, so CSV validation is driven by data, not hard-coded. It also needs to be fast (100k rows in seconds) and give helpful errors.
8. **Live visibility at volume.** Thousands of state changes per second must reach browsers without hammering the database.

---

## 1.6 Assumptions and interpretations

Wherever the brief is silent or ambiguous, we decided as follows. Each decision is also listed in the README's "Known limitations / assumptions" section.

| # | Assumption | Why |
| --- | --- | --- |
| **A1** | "Concurrency" means **how many calls run at the same time**. The company confirmed this by email: *"Concurrency means how many calls will run at the same time."* So each org has **two limits**, both set by the superadmin and both checked in the same atomic Redis step: **`max_concurrent_calls`**, the number of calls reserved or live at once (a call holds its place until its outcome is processed), and **`max_calls_per_second`**, at most N calls to Sarvam's outbound API in **any rolling 1-second interval**. The rolling reading is stricter than "per calendar second", which would allow 2N calls across a second boundary. | The email settles what concurrency means. The brief's own example ("hit at most 5 times per second") is a rate, so we enforce that too. Holding both is safe under either reading. |
| **A2** | Campaign APS (0.1 to 500, like Sarvam's own range) is a per-campaign cap. **Every** dial, first attempt or retry, counts against the campaign cap and both org limits. | Retries are real API hits. Sarvam's campaign docs also count retries toward the rate. |
| **A3** | We may not call any other Sarvam API, so **agents are registered manually** in our system (app id, version, variables with type/required/example). The sample CSV is generated from that registration. | There is no allowed way to fetch agent metadata from Sarvam. |
| **A4** | Sarvam org id lives on our organisation; Sarvam workspace id + API key live on our workspace. API keys are encrypted at rest and write-only through the API. | The outbound URL needs both ids; keys are secrets. |
| **A5** | The webhook follows Sarvam's documented instant-outbound payload (`attempt_id`, `status` ∈ connected/busy/no_answer/failed, `duration`, `failure_reason`, echoed `webhook_config.metadata`). We put our own `attempt_ref` + an HMAC signature into `metadata`. Parsing is tolerant and isolated in one adapter. | Sarvam doesn't document webhook signing, so we authenticate webhooks ourselves. The adapter localises any payload differences. |
| **A6** | Outcome mapping: connected and duration ≥ threshold → **completed**; connected and duration < threshold → **short_call**; busy; no_answer; failed. **No webhook within 15 min** (configurable with `WEBHOOK_TIMEOUT_S`; the compose file uses 5 min because the mock runs calls 10 times faster) → **lost**, handled like *failed* for retries. | Turns the brief's "short-duration threshold" into a concrete rule, and covers lost webhooks. |
| **A7** | Retry rules: per outcome (busy / no_answer / short_call / failed): enabled + delay (optional exponential backoff), plus a global **max attempts** (including the first). A retry is shifted into the next allowed window. A retry that would land after the campaign's end time isn't scheduled (contact → failed, reason `campaign_ended`). | Retries must respect the schedule and the limit (one of the brief's questions). |
| **A8** | Calling window = one IANA timezone + allowed weekdays + one daily `[start, end)` local interval per campaign. Windows that cross midnight aren't supported in v1. DST comes from the tz database. | Covers the brief's "timezone, hours, days" without over-building. |
| **A9** | A call already accepted by Sarvam **can't be cancelled** (we have no API for that). Pause, stop and window-close stop **new** dials immediately. Live calls finish and their outcomes are still recorded. | Physical reality plus the API constraint. |
| **A10** | A campaign **auto-completes** when every contact is terminal, or when its end time passes. Contacts not yet reached then fail with reason `campaign_ended`. | A clear, observable end state. |
| **A11** | Uploads are **all-or-nothing by default**: any invalid row rejects the file, with a row-level error report. `skip_invalid=true` accepts only the valid rows; `dry_run=true` validates without saving. Phones are normalised to E.164 (default region IN). A phone number appears at most once per campaign. | "Validate uploads before accepting them": the safe default, with escape hatches. |
| **A12** | Cohorts can be added while a campaign is draft, scheduled, running or paused, but not after it has stopped or completed. | Matches Sarvam's own cohort rules. |
| **A13** | Caller numbers are used **round-robin** across the campaign's selected numbers. | Spreads load across numbers, which helps answer rates and spam scores. |
| **A14** | Roles: **superadmin** (global), **org_admin** (whole org), **member** (only the workspaces they belong to). | The brief names superadmin vs org users. An admin tier inside the org is the minimum practical split. |
| **A15** | The same phone number is never dialed **concurrently** by two campaigns of the same org (short-lived phone lock). Cross-org de-duplication is out of scope. | The broader reading of "can a customer be called twice?" |
| **A16** | Every call goes to a **mock Sarvam** with the same request and webhook contract. The assignment allows only mock calls, so the system never calls the real Sarvam API. `SARVAM_BASE_URL` exists, but it points at the mock. | Lets us generate load and failures without phoning real people, and the mock doubles as an independent referee for the limits. |

### Out of scope for v1 (possible extensions)

- Transcripts, recordings, analytics (these need other Sarvam APIs, which aren't allowed).
- National DND registry checks, consent management, billing.
- Per-contact timezones, multiple windows per day, holiday calendars.
- SSO / OAuth identity providers.

---

## 1.7 The four questions the brief asks

Short answers here. The full reasoning is in `02-architecture.md` §B.18.

| Question | Our answer in one line |
| --- | --- |
| How do you guarantee the per-org limit with many workers/instances? | Every dial must win a **slot from one atomic Redis script** that checks both org limits at once: a free place under the concurrent-call cap (an in-flight set per org) and an evenly spaced send time (GCRA pacing, Redis server clock, safety margin for jitter). Workers hold no limit state of their own, so adding workers can't add budget. |
| Worker crashes mid-dispatch: can a customer be called twice? | The contact is **claimed in Postgres with a lease**. A **send-intent marker** is written just before the HTTP call. After a crash: no marker ⇒ the reaper takes the marker itself (atomic set-if-absent) ⇒ never sent, and now it never can be ⇒ safely re-queued; marker ⇒ *maybe* sent ⇒ we wait for the webhook (matched by our `attempt_ref`) or a timeout, and **never blindly re-send**. |
| Window closes / campaign paused mid-batch? | **There is no batch.** Nothing is pre-queued. Each dial is decided at the last moment by a gate that checks campaign state and window end atomically. Claimed-but-unsent contacts go back to the queue untouched; live calls finish. |
| How do retries interact with the schedule and the limit? | A retry is just the same contact row with a new `next_attempt_at`, shifted into the next allowed window. It goes back through the **same queue and the same gate**, so it counts against the same org limits and obeys the same window. Due retries get priority over fresh contacts so retry delays stay honest. |

---

## 1.8 What "done" looks like (demo checklist)

1. `docker compose up` brings up the whole system with seed data.
2. Superadmin creates **Org A (20 calls at once, 5/s, like the seeded demo org)** and **Org B (40 calls at once, 10/s)**.
3. An org user registers an agent, downloads the sample CSV, uploads a 2,000-row cohort, and sees validation errors for a deliberately broken file.
4. Three campaigns run at once across both orgs with three worker replicas.
5. The live dashboard shows per-contact states and attempts. The org rate chart sits flat at the limit, and the **mock Sarvam's own counters report the max calls in any 1-second window ≤ the rate limit and the max calls live at once ≤ the concurrent limit** (`make prove` prints both).
6. Pause → calls stop immediately. Resume → they continue. Stop → remaining contacts are cancelled.
7. Kill a worker mid-run → no customer is called twice, and every contact still finishes.
8. Retries show up after their delay and only inside the calling window.
