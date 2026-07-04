# Synthetic Data Plan (MAX Agent app)

The app ships with a MANUFACTURED, clearly-flagged synthetic fleet in
`max_agent/synthetic_data.py` so it runs end-to-end with no Databricks connection. It invents no
Oxy policy value; the BU profile thresholds stay null and the gate/classifier behave fail-closed.

Mirrors the SOAR sample shape (see the vault Data Readiness Scorecard):

- rotating-only (`Equipment_Category = R`);
- labor cost 0 (no labor-savings claim is defensible);
- measurement readings absent (real CBM stays blocked);
- no distinct mandatory-PM tag (criticality-4 is a conservative proxy);
- findings coding partial (damage ~56%, cause ~51%).

## Gate-status coverage (one or more assets per outcome)

| Asset | Criticality | Change under consideration | Gate outcome |
|---|---|---|---|
| PUMP-4102 | 1 | retain PM | PASS |
| PUMP-4110 | 2 | shorten frequency (trial) | REVIEW_REQUIRED |
| HX-6601 | 0 (unvalidated) | strategy-type change | REVIEW_REQUIRED |
| FAN-7701 | 1 | add inspection | REVIEW_REQUIRED |
| COMP-2201 | 3 | extend frequency (reduce) | BLOCKED (mandatory) |
| VALVE-3301 | 4 HSE | retire PM | BLOCKED (mandatory/HSE) |
| PUMP-4115 | 2 | add CBM, no readings | BLOCKED (CBM readings) |
| PUMP-4120 | 3 | move to run-to-failure | BLOCKED (RTF barred) |
| PUMP-4130 | 2 (JV) | any | BLOCKED (out of scope) |
| PUMP-4140 | 1 (exempt) | any | BLOCKED (out of scope) |
| PUMP-4116 | 1 | add CBM (synthetic readings) | DRAFT_ONLY (synthetic demo) |
| MOTOR-5501 | 1 | task-list cleanup, no WSO | DRAFT_ONLY (WSO required) |

The classifier runs in describe-and-flag mode (thresholds null): mandatory / criticality-2/3/4 PMs
return `Governance Review Required`; non-mandatory PMs return `Missing Evidence`. It does not assert
`Effective` / `Ineffective` until Oxy confirms thresholds (Decision Register B1/P2).

## Cutover to real Oxy data

Replace `synthetic_data.py` as the source with the governed views in `views.sql` (bound after the
workshop confirms P1/F1/E1/B2). The tools read the same record shapes, so nothing downstream changes.
