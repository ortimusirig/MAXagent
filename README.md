# MAX Agent - Databricks App

MAX Agent is a governed preventive-maintenance strategy copilot for Oxy, built as a
Databricks App (Dash). It is a runnable, **synthetic-first** app: a two-panel chat + artifacts UI
driven by a deterministic tool core (pure, Databricks-free, unit-tested). It runs locally with no
Databricks connection and deploys to Databricks Apps; the real integrations (SQL warehouse, Genie,
LLM serving endpoint) are injectable and light up when bound. See `DEPLOY.md`.

Wave 1 is draft-only: MAX drafts governed recommendations and SAP change packages; humans approve;
MDC/BPDO or the official Oxy process updates SAP. No direct SAP write-back.

## Run it

```
pip install -r requirements.txt
python app.py          # http://127.0.0.1:8000 - pick an asset; header shows "data mode: local_synthetic"
python -m pytest -q    # deterministic core + orchestrator on synthetic data
```

The design source of truth is the Obsidian vault, folder `70 - MAX Agent Build`:

- `08 - oxy_gate_check Specification and Unit Tests` (the governance gate)
- `09 - pm_effectiveness_classifier Specification and Unit Tests` (the classifier)
- `10 - Core Deterministic Tool Specs and Unit Tests` (validate_scope, data_readiness_gate,
  approval_workflow_state, draft_sap_change_package, recommend_strategy_change)
- `02 - App Repository Scaffold`, `04 - MAX Tool Library Implementation Plan`
- `config/bu_profiles/default_oxy.yaml` (the BU profile / rule data)

## Hard rules (do not violate)

- **Draft-only.** MAX never writes to SAP directly in Wave 1 (`max_writes_sap` is always False).
- **One agent, one 24-tool library.** Canonical tool names only (e.g. `draft_sap_change_package`,
  never `sap_change_package_drafter`).
- **Safety decisions are deterministic**, not free-form LLM judgment. The LLM may explain a
  gate/classifier result; it must never invent it.
- **BU and threshold values are PROPOSED / BU_DEFINED** until Oxy confirms them.
  `classifier_thresholds` and `moc_threshold` stay **null** in the shipped profile; the
  classifier runs in describe-and-flag mode until Oxy sets them.

## Layout

```
max_agent/
  schemas.py            standard tool-result envelope
  config.py             BU profile loader; classifier-thresholds-set check
  config/bu_profiles/default_oxy.yaml   BU rule data (synced from the vault; thresholds null)
  tools/
    context.py          resolve_context, validate_scope
    retrieval.py        run_scoped_sql (thin, injectable; Databricks-free)
    classification.py   pm_effectiveness_classifier, data_readiness_gate
    recommendation.py   pm_strategy_comparator, risk_business_justification, recommend_strategy_change
    governance.py       oxy_gate_check, approval_workflow_state
    package.py          draft_sap_change_package
  orchestrator.py       MAX Agent pipeline (context -> scope -> classify -> readiness -> recommend -> gate -> package -> approval) + Tool Trace
  synthetic_data.py     manufactured Oxy-like fleet (flagged synthetic; runs the app with no Databricks)
  databricks_client.py  lazy/optional Databricks SDK + Genie + SQL + LLM seam (falls back to local synthetic)
  sql_templates.py      parameterized SQL templates + local synthetic executor
  prompts.py            LLM narration prompt + deterministic fallback summary
  ui/                   Dash UI: layout, chat, artifacts (Decision/Evidence/PM Health/Comparison/SAP Package/Tool Trace), charts, theme
app.py                  Dash entry point + callbacks
app.yaml                Databricks Apps manifest (optional resource bindings)
views.sql               curated v_* views for the real-data cutover
data/                   synthetic_data_plan.md, sample_seed_config.json
DEPLOY.md               run locally + deploy to Databricks Apps + real-data cutover
tests/                  unit tests + golden-set regression + end-to-end orchestrator tests
```

All 24 canonical tools are implemented and registered (`MAX_AGENT_TOOL_LIBRARY`): the deterministic
safety core (Wave A + governance), plus Wave B portfolio/comparison, Wave C execution-readiness (6
tools), Wave D monitoring/KPI, and the scoped `genie_query_scoped` retrieval path. The orchestrator
exercises the Wave B/C/D tools on the in-scope path (and skips them when scope fails closed), and the
Dash app surfaces them (PM Health metrics + triage + baseline KPIs, execution-readiness on Evidence,
like-equipment cohort + standardization candidates on Comparison). The remaining work is the real
Databricks data cutover; the Databricks integrations are injectable so binding them needs no code
change.

## Running the tests

The deterministic core needs only `pyyaml` and `pytest`:

```
pip install pyyaml pytest
cd max-agent-databricks-app
python -m pytest -q
```

The suite covers every unit-test case named in specs 08, 09, and 10, plus a data-driven
golden-set regression harness (`tests/fixtures/golden_gate_classifier_cases.json`). Tests
that must assert a concrete classifier label inject a clearly-labeled **straw-man** threshold
set that lives only in the tests - the shipped `default_oxy.yaml` keeps thresholds null.

## Gate design notes

- `oxy_gate_check` follows spec 08 line-for-line: scope is checked first (fail-closed), then
  the rule order encodes the status precedence BLOCKED > DRAFT_ONLY > REVIEW_REQUIRED > PASS.
- Each `REVIEW_REQUIRED` carries a distinct `review_trigger` and each `BLOCKED` / `DRAFT_ONLY`
  a precise `blocked_reason`, so tests assert the exact rule that fired rather than being
  masked by the final catch-all. An adversarial check confirms every emitted reason code is
  exercised by a test (no dead rules) and the RTF bar is exactly criticality {2, 3, 4}.
- The two mandate types are kept distinct: the asset strategy-coverage mandate (criticality
  2/3/4) blocks reduce/retire/RTF on evidence alone but lets keep-coverage improvements route
  to REVIEW; a per-PM regulatory basis (`pm_governance.mandatory_pm`, Table 2 codes) is the
  stricter per-PM signal.
