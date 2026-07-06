-- =====================================================================================
-- MAX Agent - AI/BI (Lakeview) dashboard backing data
-- =====================================================================================
-- The dashboard (pm_health.lvdash.json) queries ONE table: supplychain.max_agent.pm_health.
-- This script creates it. Two options:
--   A. SYNTHETIC SEED (default) - governed rows exported from the app's portfolio_health(),
--      so the dashboard shows real MAX outcomes immediately, with no Oxy data. (Section A)
--   B. PRODUCTION VIEW - point the same table name at governed v_* views over real SAP PM
--      data once it lands. (Section B, commented.)
-- Change the catalog/schema (supplychain.max_agent) to match your workspace; keep it consistent with
-- the datasetName table in pm_health.lvdash.json (find/replace supplychain.max_agent.pm_health).
-- =====================================================================================

-- Uses the existing supplychain catalog (owned by sumitro.giri@applexus.com).
CREATE SCHEMA IF NOT EXISTS supplychain.max_agent;

-- -------------------------------------------------------------------------------------
-- Section A: synthetic seed (regenerate any time with: python dashboards/export_pm_health_seed.py)
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE supplychain.max_agent.pm_health AS
SELECT * FROM VALUES
  ('PUMP-4102', 'CENTRIFUGAL_PUMP', '1', 'Missing Evidence', 'PASS', 'GREEN', false, 'Request evidence', '-', 'SYNTHETIC'),
  ('PUMP-4110', 'CENTRIFUGAL_PUMP', '2', 'Governance Review Required', 'REVIEW_REQUIRED', 'YELLOW', true, 'Route to governance review (keep-coverage improvement)', 'RISK_REVIEW_REQUIRED', 'SYNTHETIC'),
  ('COMP-2201', 'RECIP_COMPRESSOR', '3', 'Governance Review Required', 'BLOCKED', 'GREEN', true, 'Route to governance review (keep-coverage improvement)', 'MANDATORY_PM_CANNOT_REDUCE_COVERAGE', 'SYNTHETIC'),
  ('VALVE-3301', 'ESD_VALVE', '4', 'Governance Review Required', 'BLOCKED', 'GREEN', true, 'Route to governance review (keep-coverage improvement)', 'MANDATORY_PM_CANNOT_REDUCE_COVERAGE', 'SYNTHETIC'),
  ('PUMP-4115', 'CENTRIFUGAL_PUMP', '2', 'Governance Review Required', 'BLOCKED', 'GREEN', true, 'Route to governance review (keep-coverage improvement)', 'CBM_REQUIRES_REAL_MEASUREMENT_READINGS', 'SYNTHETIC'),
  ('PUMP-4116', 'CENTRIFUGAL_PUMP', '1', 'Missing Evidence', 'DRAFT_ONLY', 'GREEN', false, 'Request evidence', 'CBM_SYNTHETIC_DEMO_ONLY', 'SYNTHETIC'),
  ('MOTOR-5501', 'ELECTRIC_MOTOR', '1', 'Missing Evidence', 'DRAFT_ONLY', 'GREEN', false, 'Draft least-invasive improvement (gated)', 'WORK_STRATEGY_OWNER_REQUIRED', 'SYNTHETIC'),
  ('PUMP-4120', 'CENTRIFUGAL_PUMP', '3', 'Governance Review Required', 'BLOCKED', 'GREEN', true, 'Route to governance review (keep-coverage improvement)', 'RTF_BARRED_FOR_CRITICAL_2_3_4', 'SYNTHETIC'),
  ('HX-6601', 'HEAT_EXCHANGER', '0', 'Missing Evidence', 'REVIEW_REQUIRED', 'GREEN', false, 'Route to governance review', 'CRITICALITY_NOT_VALIDATED', 'SYNTHETIC'),
  ('PUMP-4130', 'CENTRIFUGAL_PUMP', '2', 'Not classified (out of analysis scope)', 'BLOCKED', 'GREEN', false, '-', 'NON_OPERATED_OR_JV_OUT_OF_SCOPE', 'SYNTHETIC'),
  ('PUMP-4140', 'CENTRIFUGAL_PUMP', '1', 'Not classified (out of analysis scope)', 'BLOCKED', 'GREEN', false, '-', 'EXEMPT_ASSET_OUT_OF_SCOPE', 'SYNTHETIC'),
  ('FAN-7701', 'COOLING_FAN', '1', 'Missing Evidence', 'REVIEW_REQUIRED', 'GREEN', false, 'Request evidence', 'CRITICALITY_OR_STRATEGY_CHANGE', 'SYNTHETIC'),
  ('PUMP-4150', 'CENTRIFUGAL_PUMP', '1', 'Missing Evidence', 'PASS', 'GREEN', false, 'Draft least-invasive improvement (gated)', '-', 'SYNTHETIC')
AS t(equipment_id, asset_class, criticality, label, gate_status, data_readiness, do_not_optimize, next_action, reason, provenance);

-- Optional: let the dashboard viewers read it.
-- GRANT SELECT ON TABLE supplychain.max_agent.pm_health TO `account users`;

-- -------------------------------------------------------------------------------------
-- Section B: PRODUCTION view (uncomment when governed v_* views exist; drop the seed above).
-- The dashboard is unchanged - it still reads supplychain.max_agent.pm_health.
-- These columns must be produced by MAX's governed pipeline (gate/classifier/readiness),
-- NOT computed in SQL, so the dashboard never diverges from the app's decisions. In practice
-- a scheduled job writes portfolio_health() to this table; the view below is a stand-in shape.
-- -------------------------------------------------------------------------------------
-- CREATE OR REPLACE VIEW supplychain.max_agent.pm_health AS
-- SELECT h.equipment_id, e.asset_class, e.criticality, h.label, h.gate_status,
--        h.data_readiness, h.do_not_optimize, h.next_action, h.reason, 'GOVERNED' AS provenance
-- FROM   supplychain.max_agent.max_pm_health_runs h              -- written by the MAX portfolio job
-- JOIN   supplychain.max_agent.v_equipment_master e USING (equipment_id)
-- WHERE  h.run_id = (SELECT max(run_id) FROM supplychain.max_agent.max_pm_health_runs);
