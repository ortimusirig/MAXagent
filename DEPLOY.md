# MAX Agent - run locally and deploy to Databricks Apps

MAX Agent is a governed PM strategy copilot (Dash app). It runs on synthetic data with no
Databricks connection, and lights up real integrations once you bind Databricks resources. Wave 1
is draft-only: MAX drafts governed recommendations and SAP change packages; humans approve;
MDC/BPDO or the official Oxy process updates SAP. No direct SAP write-back.

## 1. Run locally (synthetic-first)

```
cd max-agent-databricks-app
pip install -r requirements.txt          # dash, plotly, pandas, numpy, pyyaml (databricks-sdk optional)
python app.py                            # serves on http://127.0.0.1:8000
```

Pick an asset from the dropdown. The right-panel tabs show Decision, Evidence, PM Health,
Comparison, SAP Package, and Tool Trace. The header shows `data mode: local_synthetic`.

Run the tests (deterministic core + orchestrator on synthetic data):

```
python -m pytest -q                      # expect: all passed
```

## 2. Deploy to Databricks Apps

Prereqs: the Databricks CLI configured for your workspace, and (optionally) a SQL warehouse, a
Genie space, and an LLM serving endpoint.

```
databricks apps create max-agent                       # once
databricks sync . /Workspace/Users/<you>/max-agent     # push the code
databricks apps deploy max-agent --source-code-path /Workspace/Users/<you>/max-agent
```

The runtime provides `$DATABRICKS_APP_PORT`; `app.py` binds to it. The app runs as its service
principal - no tokens in code.

## 3. Leave synthetic mode (bind real resources)

Uncomment and set these in `app.yaml` (as Databricks App resources / env), then redeploy. No code
change is needed - `max_agent/databricks_client.py` picks them up:

- `SQL_WAREHOUSE_ID` - a SQL warehouse for `run_scoped_sql` (scoped, parameterized templates).
- `GENIE_SPACE_ID` - a Genie space for scoped conversational retrieval.
- `LLM_AGENT_ENDPOINT` - a serving endpoint for chat narration (the LLM only explains; it never
  decides a gate or a label).
- `MAX_CATALOG` / `MAX_SCHEMA` - where the curated `v_*` views live (see `views.sql`).

Grant the app service principal: `CAN USE` on the warehouse, `CAN RUN` on the Genie space,
`CAN QUERY` on the serving endpoint, and `SELECT` on the `v_*` views.

## 4. Real-data cutover (after the Houston workshop)

The app stays synthetic-first and fail-closed until Oxy confirms the source fields and thresholds
in Houston (Decision Register B2/C7, P2/B1, F1/F3, E1, G1/G2, C3). To cut over:

1. Create the governed views in `views.sql` over the real Oxy PM extract (bind `pm_plan_source`
   etc. to the confirmed SAP objects).
2. Set `classifier_thresholds` and `moc_threshold` in the BU profile ONLY once Oxy confirms them
   (they stay null until then - the classifier describes and flags, the gate stays conservative).
3. Point the orchestrator's data source at the views instead of the synthetic fleet.

Until then: no realized-savings, CBM-on-real-readings, or fixed-equipment claims; the gate blocks
direct SAP write-back, mandatory-PM reductions, RTF on criticality 2/3/4, and CBM without readings.

## Production server (optional)

For a production WSGI server instead of the Dash dev server, run gunicorn against `app:server`:

```
gunicorn -b 0.0.0.0:$DATABRICKS_APP_PORT app:server
```

(Set the `command` in `app.yaml` accordingly.)
