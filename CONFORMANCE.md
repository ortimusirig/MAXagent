# MAX Agent - Conformance to the Build Documentation

How this app conforms to the Oxy MAX Agent build specs (`70 - MAX Agent Build`, plus the
`60 - MVP Scope and Design` and `30 - Agent Design` docs). This file is deliberately honest,
including where an earlier version of it over-claimed.

**Verdict: CONFORMANT-WITH-GAPS.** The deterministic tools match their specs and tests, but the
orchestration, SQL safety, approval UI, and LLM layer have documented partials below. This is not
"fully conformant" and is not sign-off-ready for full Oxy process/data/requirements approval.

## What an external review (Codex) found, and what changed

An independent review flagged five real issues and several over-claims in the prior CONFORMANCE.md.
All were valid. Fixes applied:

| Finding | Fix | Residual |
|---|---|---|
| LLM narration could contradict the deterministic gate (user-facing) | Added a narration guard: a narration that affirms/approves a non-PASS gate is **rejected**, keeping the deterministic summary (`orchestrator._narration_contradicts_gate`) | Heuristic phrase list; not a semantic proof |
| Gate/package evaluated `proposed`, not MAX's recommendation (70/10:107) | **Coupled**: the SAP package now drafts MAX's recommendation, gated by the recommendation's own gate; the requested change + its gate stay visible for the demo; out-of-scope stays documentation-only (fail-closed) | Closed |
| SQL guard only checked scope column *names* | Guard now requires scope predicates to be **value/param bound** (`col = :param` / `IN(...)` / `= 'value'`); `IS NOT NULL` is rejected (`sql_guard._scope_bound`) | Server-side param binding in the executor still TODO - see F |
| Approval buttons bypassed `approval_workflow_state` | Callback now routes each click through the tool: **verifies role, blocks self-approval, records denied attempts** (`app.on_approval`) | Databricks groups are not yet mapped to approver roles, so real users are denied until the BU profile maps them (correct fail-closed) |
| PM Health queue missing "recommended next action" | Column added | - |

## Conformance by area (A-J)

| Area | Status |
|---|---|
| A. 24 tool names / envelopes | Conformant |
| B. `oxy_gate_check` (70/08) | Tool conformant (34 cases); the orchestrator now gates the recommendation too |
| C. `pm_effectiveness_classifier` (70/09) | Conformant |
| D. Core deterministic tools (70/10) | **Conformant** - the SAP package now drafts MAX's recommendation, gated by the recommendation's own gate (70/10:107 "every recommendation passes to oxy_gate_check"); the requested change + its gate remain visible; out-of-scope stays documentation-only (fail-closed) |
| E. Two mandate types | Conformant |
| F. Genie / SQL safety (70/05) | **Partial** - SELECT-only + view allowlist + value-bound scope guard built; server-side parameter binding, row-cap injection at execution, and rejected-SQL hash not built |
| G. UI (60/04, 30/AppExp) | **Partial** - context bar, chat, pills, queue-first, drill-through, readiness, governed approval, next-action column built; durable approval persistence pending |
| H. No invented Oxy values | Conformant for deterministic outputs; LLM narration is now guarded against contradicting the gate |
| I. Databricks seam | **Partial** - lazy/optional bindings present; server-side SQL parameter binding incomplete |
| J. Tests | 190 pass; the tests no longer bless a gate-contradicting narration (it is asserted rejected) |

## LLM orchestration - honest status

A **partial narration-only layer exists** (`agent_loop.py`, `agent_tools.py`): a LangGraph
`create_react_agent` that, when a serving endpoint is bound, plans **read-only** tools and narrates,
with the deterministic gate/label authoritative and the narration guarded. It is **not** a fully
governed LLM-selected tool DAG that drives the recommendation/package, and it is dormant until
`LLM_AGENT_ENDPOINT` is bound (deterministic-only fallback). Design: `ORCHESTRATION_DESIGN.md`.

## Still deferred (with rationale)

- **Server-side SQL parameter binding + row-cap injection + rejected-SQL hash** (70/05): activate
  when SQL/Genie are bound; the pre-execution value-bound guard is built now.
- **Bulk multi-table synthetic generator** (70/03): the 12-asset gate/classifier driver is
  intentional; the bulk generator's target is `views.sql` at cutover. Gate/classifier logic is
  unit-tested (34 cases).
- **Criticality-N and ABC-4 missing-object-dependency synthetic assets** (70/03): demo-completeness;
  logic is unit-tested.
- **Durable Phase-7 persistence** (60/05, 70/06): Delta tables + run selector + append-only audit
  hash-chain; approval audit is in-session today.
- **Remaining 12 of 17 curated views** (70/01): added as each real source is confirmed.

## Unchanged guarantees

Draft-only, no direct SAP write-back; fail-closed (null thresholds -> describe-and-flag); the LLM
narrates and is guarded, never decides a gate/label; every value is synthetic or PROPOSED until Oxy
confirms it.
