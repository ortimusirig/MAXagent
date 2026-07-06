# Deploy the MAX Agent AI/BI (Lakeview) dashboard

A simple Databricks **AI/BI dashboard** for fleet PM health, plus the seam that embeds it into the
MAX Agent app (the Ask MAX -> **Dashboard** tab).

## Files
| File | What it is |
|---|---|
| `pm_health.lvdash.json` | the AI/BI (Lakeview) dashboard asset: 6 KPI counters + 3 distribution bars + the governed queue table |
| `pm_health_dashboard_setup.sql` | creates the one backing table `supplychain.max_agent.pm_health` (synthetic seed now; production view template commented) |
| `export_pm_health_seed.py` | regenerates the seed from the app's `portfolio_health()` so the dashboard = the app's governed truth |
| `pm_health_seed.csv` / `pm_health_seed_values.sql` | generated seed (row-level CSV + a `CREATE TABLE ... VALUES` block) |

The dashboard reads exactly one table: `supplychain.max_agent.pm_health`. Change that catalog/schema to
match your workspace in BOTH `pm_health_dashboard_setup.sql` and `pm_health.lvdash.json` (find/replace
`supplychain.max_agent.pm_health`).

## Step 1 - create the backing data (SQL warehouse)
Run `pm_health_dashboard_setup.sql` on a SQL warehouse. It creates `supplychain.max_agent.pm_health` seeded
with the 13 governed synthetic rows, so the dashboard shows real MAX outcomes immediately - no Oxy data
needed. To refresh the seed after code changes:
```
python dashboards/export_pm_health_seed.py    # rewrites pm_health_seed*.{csv,sql}
```
In production, drop the seed and uncomment Section B (a view over governed `v_*` data). The dashboard is
unchanged - it still reads `supplychain.max_agent.pm_health`.

## Step 2 - import + publish the dashboard
Import the asset (either path):
- **CLI:** `databricks workspace import ./dashboards/pm_health.lvdash.json "/Workspace/Users/<you>/pm_health.lvdash.json" --format AUTO`
- **UI:** Workspace -> your folder -> Import -> select `pm_health.lvdash.json`.

Then open it, attach a **SQL warehouse**, confirm the counters/bars/table populate, and click **Publish**
(publishing is required to embed).

## Step 3 - wire it into the app
1. From the published dashboard: **Share / Embed** -> copy the embed URL
   (`https://<host>/embed/dashboardsv3/<dashboard-id>`).
2. In `app.yaml` set:
   ```
   - name: "AIBI_DASHBOARD_EMBED_URL"
     value: "https://<host>/embed/dashboardsv3/<dashboard-id>"
   - name: "AIBI_DASHBOARD_URL"           # optional "Open in Databricks" button
     value: "https://<host>/dashboardsv3/<dashboard-id>/published"
   ```
3. Grant the app's **service principal** `SELECT` on `supplychain.max_agent.pm_health` and **CAN VIEW** on the
   dashboard, so the embedded iframe renders for app users.
4. Redeploy the app. The Ask MAX **Dashboard** tab now embeds the live AI/BI dashboard.

## Behaviour without the env var
Until `AIBI_DASHBOARD_EMBED_URL` is set, the Dashboard tab renders the **same governed fleet metrics
in-app** (Plotly charts from `portfolio_health()`), with a note pointing here. So the tab is never empty,
and both surfaces read one governed truth - the AI/BI dashboard can never diverge from the app.

## Notes / caveats
- **Auth:** embedding works cleanly when the app and dashboard are in the same workspace (the viewer's
  SSO session carries auth). Cross-workspace or public embedding needs the workspace embedding allowlist
  and the app domain added; check your workspace's dashboard-embedding settings.
- **Draft-only / honest:** the dashboard shows counts and gate outcomes only - no realized-savings or
  effectiveness score is implied (thresholds are null; value is baseline-only), matching the app.
- **Widget tweaks:** the `.lvdash.json` is built to the Lakeview format; if a widget spec version differs
  in your workspace, open the dashboard and adjust in the editor - the datasets/SQL stay valid.
