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
| LLM narration could contradict the deterministic gate (user-facing) | Built ONE shared **narration gate** that guards BOTH governed narration and free-flow: an answer affirming a non-PASS change gets ONE corrective re-prompt, then the deterministic template as a circuit breaker (`orchestrator._narrate_guarded` + `_narration_affirms_blocked_change`). The model may explain a gate, never affirm a non-PASS one; the deterministic layer wins ties | Action-anchored heuristic detector; not a semantic proof |
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
| J. Tests | 300 pass; the tests no longer bless a gate-contradicting narration (it is asserted rejected on BOTH the governed and free-flow lanes) |

## LLM orchestration - honest status

The **GOVERNED** lane is deterministic + narration-only: `_run_asset` runs the fixed tool pipeline
(incl. `oxy_gate_check`) and the LLM only narrates the finished decision. The optional LLM tool-selection
loop that used to sit on the governed lane was **removed** (it never changed a decision) - see
`ORCHESTRATION_DESIGN.md`; the code is archived in `prototypes/removed_governed_agentic_loop.py`.
`orchestration_mode` is only ever `deterministic_only` or `llm_narrated`. (It was a manual `bind_tools`
loop, never LangGraph - `create_react_agent` crashed on Databricks.)

The **FREE-FLOW** lane is a richer conversational lane, sub-routed by intent:
- **INFO** - read the last governed decision + fetch scoped evidence via READ-ONLY tools (`make_agent_tools`).
- **GATE_CHECK** - an ADVISORY, read-only gate preview: `preview_gate_check` runs the real deterministic
  `oxy_gate_check` on a HYPOTHETICAL change and reports the verdict. It is a preview, never the
  authoritative decision; it drafts nothing, and a governed review is still required to make a change official.
- **APPROVAL** - MAX SURFACES inline approve/reject buttons; the authenticated human clicks and
  `approval_workflow_state` decides (role + gate + self-approval + audit). Draft-only; never writes SAP.

Both LLM lanes pass one shared **narration gate** (`_narrate_guarded`): the model may explain a gate,
never affirm a non-PASS one; a contradiction gets one corrective re-prompt, then a deterministic template.
Free-flow answers also render a read-only card in the Artifacts panel. The one invariant: deterministic
tools decide; the LLM proposes/previews; the human commits approvals; nothing reaches SAP.

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
