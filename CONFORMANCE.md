# MAX Agent - Conformance to the Build Documentation

This records how the deployed app conforms to the Oxy MAX Agent build specs
(`70 - MAX Agent Build`, plus the `60 - MVP Scope and Design` and `30 - Agent Design` docs it
depends on). It is deliberately honest about what is built now and what is intentionally deferred.

## Method

Every buildable requirement across 14 spec docs was mapped to the actual code by a dedicated
reader, and every claimed gap was re-checked adversarially against the code before it counted.
Result: the deterministic safety core is fully conformant; the divergences were concentrated in the
UI / interaction model, which this build closes.

## Conformance by doc

| Doc | Area | Status |
|---|---|---|
| 70/08 | `oxy_gate_check` spec + tests | Fully conformant (0 gaps) - line-for-line, 34 spec cases pass |
| 70/09 | `pm_effectiveness_classifier` spec + tests | Fully conformant (0 gaps) - all labels + guards, tests pass |
| 70/10 | Core deterministic tool specs + tests | Fully conformant (0 gaps) |
| 70/04 | 24-tool library, waves, envelope, safety behaviors | Conformant (all 24 tools, fail-closed behaviors present) |
| 60/07 | Canonical tool names + left-chat shape + 6 tabs | Conformant |
| 70/02 | Repo scaffold | Conformant (matches recommended layout) |
| 70/07 | Demo capability carryover | Conformant (kept/changed/dropped map honored) |
| 70/01 | End-to-end build steps / UI | Conformant; `views.sql` ships 5 of 17 curated views (cutover target) |
| 70/05 | Genie / SQL safety | **Now built**: SELECT-only + view-allowlist + scope-filter guard (see below) |
| 70/06 | Deployment security + validation checklist | **Now built**: chat send/receive, signed-in actor identity |
| 60/04 | UI and artifact design | **Now built**: context bar, chat, pills, Decision confidence/readiness, approval UI |
| 30/AppExp | App experience requirements | **Now built**: chat-core, queue-first, drill-through, RAG readiness |
| 70/03 | Bulk synthetic data generator | Partially deferred (see below) |
| 60/05 | Acceptance criteria + Phase-7 persistence | Deferred: durable Delta persistence (see below) |

## Built in this pass (interaction model + safety guard)

- **Free-text chat** (`intent.py` + `orchestrator.answer`): a typed question resolves
  deterministically to an in-scope asset, then runs the governed pipeline. No LLM required; no Oxy
  value invented; if nothing resolves it asks the user to pick (never fabricates a target).
- **Top context bar**: asset, class, plant, criticality, time window, review type, active
  `bu_profile_id`, and an operated-vs-JV scope note - and the time-window / review-type controls
  drive the backend scope, not just the view.
- **Conversation tool pills**: the deterministic tools that ran, surfaced as pills.
- **Decision tab**: classifier confidence + data-readiness RAG + the approval lifecycle
  (current state, allowed/blocked transitions, required approvers).
- **PM Health = queue-first landing tab**: highest-attention PMs first, a per-row data-readiness
  (RED/AMBER/GREEN) badge, a data-readiness distribution chart, and **row drill-through** - clicking
  a row locks that asset's context across every tab.
- **Governed approve / request-changes / reject** controls with a comment and an in-session audit
  trail; the submit path is gated by gate status; MAX still never writes SAP.
- **Signed-in actor identity**: the acting user comes from the Databricks Apps sign-in headers
  (`X-Forwarded-*`), not a typed name, and flows into `approval_workflow_state`.
- **Generated-SQL safety guard** (`tools/sql_guard.py`, wired into `genie_query_scoped`): rejects
  anything that is not a single scoped, allowlisted `SELECT` (no INSERT/UPDATE/DELETE/DDL/multiple
  statements); a rejected query never surfaces rows. 11 unit tests.
- **Tool Trace** enriched: per-row confidence, the SQL/template/gate detail, and the run's
  `bu_profile_id` / criticality / time window.

Tests: 180 pass (`python -m pytest -q`).

## Intentionally deferred (with rationale)

These are documented rather than silently skipped. None blocks the Wave-1, synthetic-first demo.

- **Bulk multi-table synthetic generator** (70/03): the app intentionally uses a hand-authored
  12-asset gate/classifier driver, not a 200-10,000-row normalized generator. The bulk generator's
  real target is the governed Databricks views (`views.sql`) at cutover. The gate/classifier *logic*
  for every reason code is already unit-tested (`tests/test_oxy_gate.py`, 34 cases).
- **Full synthetic reason-code coverage** incl. a criticality-N asset and an ABC-4 missing-object-
  dependency asset (70/03): demo-completeness only; the logic is unit-tested. Low-risk follow-up.
- **Durable Phase-7 persistence** (60/05, 70/06): session / artifact / package / approval / trace
  Delta tables with stable IDs, a prior-run selector, and an append-only audit hash-chain. Wave 1 is
  synthetic-first and in-session; the approval audit trail is in-session today.
- **Remaining curated views** (70/01): `views.sql` defines the 5 core views used now; the other 12
  are added as each real source is confirmed at cutover.
- **Genie execution-time parameter binding** (70/05): server-side `:param` binding activates only
  when a SQL warehouse / Genie space is bound; the pre-execution safety guard and scope injection are
  built now.

## Unchanged guarantees

Draft-only, no direct SAP write-back; fail-closed (null thresholds -> describe-and-flag); the LLM
only narrates; every value is synthetic or PROPOSED until Oxy confirms it.
