# MAX Agent - LLM Tool-Calling Orchestration (Design Note)

Status: **CONSIDERED AND DEFERRED / REMOVED (2026-07-06).** This was built as an optional, default-off
governed tool-selection loop and then removed, because it never changed a decision (the deterministic
`_run_asset` is authoritative) - it only added a tool-DAG + narration, at the cost of extra LLM calls
and a fourth `orchestration_mode`. The GOVERNED lane is now deterministic + a single narration routed
through the shared narration gate (`orchestrator._narrate_guarded`); `orchestration_mode` is only
`deterministic_only` or `llm_narrated`. The removed code is preserved verbatim (this is not a git repo)
in `prototypes/removed_governed_agentic_loop.py`.

What DID survive from this idea: the **FREE-FLOW** lane keeps a genuine agentic tool loop, sub-routed by
intent. **INFO** binds the READ-ONLY tools (`agent_tools.make_agent_tools`) - it reads the last decision
and fetches evidence and re-decides nothing. **GATE_CHECK** adds an ADVISORY, read-only preview tool
(`make_gate_preview_tool -> preview_gate_check`) that runs the real deterministic `oxy_gate_check` on a
HYPOTHETICAL change and reports the verdict as a preview (never the authoritative decision; it drafts
nothing; a governed review is still required). **APPROVAL** surfaces inline approve/reject buttons that a
human clicks, routed through `approval_workflow_state`. So free-flow can preview the gate and surface the
approval action, but the LLM never mints a governed decision, authorizes, or writes SAP - the
deterministic tools decide, the human commits. The section below is retained as the historical design
rationale for the (removed) GOVERNED tool-selection loop; it does not describe the current lanes.

## Why

The current app runs a **deterministic-only** orchestration: `MaxAgent._run_asset` executes a fixed,
scope-branched pipeline and the LLM only narrates. That is a sanctioned configuration
(`70/01` line 246, `70/06` line 227: "explicitly deterministic-only mode"). But the documented
*target* pattern is **LLM tool-calling orchestration**:

- `70/02 - App Repository Scaffold`: `orchestrator.py - Decides which tools to call...`
- `70/05` / `70/06`: a model serving endpoint is "Required if using **LLM tool-calling orchestration**".
- `60/02 - Architecture`: "reuse the current agent... orchestration pattern".

So this note adds an LLM planner that **selects and sequences** tools, while the deterministic tools
still **decide** everything that is Oxy policy.

## The one invariant this design must never break

`70/00` line 94 - "Oxy policy enforcement belongs in deterministic tools and tests, not in free-form
LLM behavior." `70/05` line 183 / `60/02` line 107 - the LLM "may explain a gate result but must
never invent one".

Therefore the LLM may plan/select/sequence the **conversational and evidence** tools and narrate;
it must **never** decide, skip, or override the **safety spine**.

### Safety spine (always runs, always deterministic, LLM cannot bypass)

For any asset-scoped decision, these always execute and their outputs are authoritative regardless of
what the LLM says or does:

```
resolve_context -> validate_scope (scope fail-closed)
  -> pm_effectiveness_classifier -> data_readiness_gate
  -> risk_business_justification -> recommend_strategy_change
  -> oxy_gate_check -> draft_sap_change_package -> approval_workflow_state
```

### Agentic surface (LLM plans/selects, deterministic tools execute)

The LLM chooses which of these to call, in what order, and how many times, based on the question:

- Retrieval: `genie_query_scoped` (NL question over data), `run_scoped_sql` (fixed templates)
- Portfolio: `pm_portfolio_triage`, `pm_health_dashboard_metrics`, `value_kpi_tracker`
- Comparison: `like_equipment_matcher`, `pm_comparison_engine`
- Execution readiness: the six `*_readiness` / calibration tools
- Monitoring: `trial_monitor`

The tools still run their deterministic logic; the LLM only decides *whether/when* to call them and
then explains the results.

## Architecture

```
                         model serving endpoint bound?
                          /                         \
                       yes                           no
                        |                             |
             AgentPlanner (LLM loop)         deterministic-only mode
                        |                       (current _run_asset)
   system rules + question + tool schemas
                        |
        LLM emits tool calls  <----------------+
                        |                       |
        Dispatcher: inject locked scope,        | results fed back
        validate args, run DETERMINISTIC tool --+
                        |
        LLM finalizes narration
                        |
   ENFORCE safety spine ran + recompute gate/label deterministically
                        |
        result (deterministic artifacts + LLM narration + plan in Tool Trace)
```

Key point: the loop is a *wrapper*. Whatever the LLM does, before returning, the orchestrator
guarantees the safety spine has run (injecting any missing safety tool) and that the gate/classifier
outputs are the deterministic ones - never the LLM's opinion.

## Code seam (files to add / change)

- `max_agent/tool_schemas.py` (new): a `TOOL_SCHEMAS` dict mapping each canonical tool name to its
  JSON function-schema (name, description, parameters). Canonical names only (`60/07`). Safety-spine
  tools are marked `mandatory: true` so the enforcer knows they must run.
- `max_agent/agent_loop.py` (new): `AgentPlanner.run(question, context, actor)`:
  1. resolve/lock scope (reuse `resolve_context` + `validate_scope`; scope is injected into every
     tool call so the LLM cannot widen it).
  2. tool-calling loop against `client.llm_complete_tools(...)`, capped at `MAX_STEPS` (e.g. 6).
  3. `Dispatcher.execute(name, args)`: validate args (e.g. `equipment_id` must be in scope), inject
     locked scope predicates, call the deterministic tool from `MAX_AGENT_TOOL_LIBRARY`, return the
     envelope. Any `genie_query_scoped` still passes `sql_guard`.
  4. enforce: run any un-called mandatory safety tool; recompute gate/label deterministically.
  5. return the same result shape as today (artifacts unchanged) + `llm_plan` (the ordered tool
     choices) recorded in the Tool Trace.
- `max_agent/databricks_client.py` (change): add `llm_complete_tools(messages, tools)` - lazy
  `WorkspaceClient`, `serving_endpoints.query(..., tools=...)`; returns `None` if not `llm_bound()`
  (which triggers the deterministic fallback). Requires a **function-calling-capable** endpoint
  (e.g. `databricks-claude-*`).
- `max_agent/orchestrator.py` (change): `MaxAgent.answer()` delegates to `AgentPlanner` when
  `client.llm_bound()`, else to the current deterministic `_run_asset` (unchanged). `run()` (dropdown
  path) stays deterministic - a pick is not a conversation.
- `app.py` (change): the chat callback uses the agentic path; the mode chip ("deterministic-only" vs
  "LLM-orchestrated") is shown honestly in the header/context bar. Tool pills already show which
  tools ran - now they reflect the LLM's plan.
- `app.yaml` (change): document/enable `LLM_AGENT_ENDPOINT` binding.

Nothing in `tools/`, the gate, the classifier, `sql_guard`, or their tests changes. The safety core
stays exactly as it is (and stays 100% conformant).

## Guardrails (how the invariant is enforced in code)

1. Scope is locked once (`validate_scope`) and injected into every tool call - the LLM's args cannot
   widen scope; out-of-scope assets short-circuit before any agentic step (fail-closed, unchanged).
2. Safety-spine tools are `mandatory`; the enforcer runs any the LLM didn't call, and the gate/label
   are always the deterministic outputs, never parsed from LLM text.
3. Retrieval stays guarded: `genie_query_scoped` -> `sql_guard` (SELECT-only, view allowlist, scope)
   applies to anything the LLM triggers.
4. The LLM narrates only; every value shown in artifacts comes from a deterministic tool envelope.
   The narration prompt forbids inventing Oxy values (thresholds, MOC %, approvers, cost).
5. Bounded loop (`MAX_STEPS`) and a per-run tool-call allowlist prevent runaway or off-scope calls.
6. Determinism where it matters: safety outputs are reproducible; only narration/plan may vary. The
   Tool Trace records the plan for audit.

## Conformance mapping

| Requirement | Doc | How this design satisfies it |
|---|---|---|
| Orchestrator decides which tools to call | 70/02 | `AgentPlanner` (LLM when bound; deterministic router otherwise) |
| LLM tool-calling orchestration | 70/05, 70/06 | `llm_complete_tools` against the bound serving endpoint |
| Deterministic-only mode is valid | 70/01, 70/06 | fallback to current `_run_asset` when unbound |
| LLM must never decide/invent the gate | 70/00, 70/05, 60/02 | safety spine always runs; gate/label recomputed deterministically |
| Genie never the deciding engine | 70/05 | retrieval is evidence-only; `sql_guard` still applies |
| Canonical tool names | 60/07 | schemas use `MAX_AGENT_TOOL_LIBRARY` names |
| Scope never widened | 70/08, validate_scope | scope injected into every tool call; fail-closed short-circuit unchanged |

## Test plan

- Unit: a mock `llm_complete_tools` that returns scripted tool calls -> assert the dispatcher injects
  scope, validates args, and the enforcer runs missing mandatory tools.
- Invariant tests: (a) LLM that "forgets" `oxy_gate_check` -> gate still present and correct;
  (b) LLM that requests an out-of-scope `equipment_id` -> rejected; (c) LLM that returns a fabricated
  gate string -> ignored, deterministic gate wins; (d) unbound client -> identical result to today's
  deterministic path.
- Regression: the existing 180 tests stay green (safety core untouched).

## Phased build

1. Schemas + `llm_complete_tools` + `AgentPlanner` + enforcer + fallback + unit/invariant tests.
2. Wire into the chat callback; Tool Trace shows LLM plan vs deterministic results; mode chip in UI.
3. Bind a function-calling serving endpoint in `app.yaml`; validate end-to-end on Databricks; keep
   deterministic-only as the automatic fallback.

## Open questions for you / Oxy

- Which Databricks serving endpoint (function-calling capable) should be the default binding?
- Max tool-call steps per turn (cost/latency vs. depth)?
- Should the dropdown/queue path stay deterministic (recommended) while only the chat path is
  agentic, or should both be agentic?
