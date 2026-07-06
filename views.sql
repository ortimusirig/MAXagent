-- Curated view definitions for the MAX Agent (real-data path).
--
-- SYNTHETIC-FIRST: the app runs on the manufactured fleet (max_agent/synthetic_data.py) with NO
-- Databricks connection. These views are the cutover target: after the Houston workshop confirms
-- the SAP source fields (Decision Register P1/F1/E1/B2), point these at the governed Oxy PM extract
-- and the tools read the same shapes with no code change.
--
-- Do NOT hardcode any Oxy value here. Field names below are placeholders to be confirmed against the
-- real extract; leave mandatory-PM tag, operated/JV field, and thresholds out until Oxy confirms.
-- Replace {catalog}.{schema} with the bound catalog/schema (MAX_CATALOG / MAX_SCHEMA).

-- Current PM plan per equipment.
CREATE OR REPLACE VIEW {catalog}.{schema}.v_pm_plan_current AS
SELECT
  equipment_id,
  pm_id,
  strategy_type,          -- ST_* strategy key (46-54% populated in the SOAR sample)
  cycle,                  -- maintenance cycle / frequency
  package                 -- maintenance package
FROM {catalog}.{schema}.pm_plan_source;   -- TODO(P1): bind to governed PM plan/item extract

-- Work-order history (scoped by equipment + window).
CREATE OR REPLACE VIEW {catalog}.{schema}.v_work_order_history AS
SELECT
  equipment_id,
  order_type,             -- preventive / corrective / reactive
  time_window
FROM {catalog}.{schema}.work_order_source;  -- TODO(P1): bind to governed WO extract

-- Notification findings (damage/cause coding is partial in the SOAR sample).
CREATE OR REPLACE VIEW {catalog}.{schema}.v_notification_history AS
SELECT
  equipment_id,
  damage_code,            -- QMFE (partial)
  cause_code              -- QMUR (partial)
FROM {catalog}.{schema}.notification_source;  -- TODO(F1): confirm findings coding source

-- Cost (labor cost is 0 in the SOAR sample; material/services partial). Value stays baseline-only.
CREATE OR REPLACE VIEW {catalog}.{schema}.v_cost_summary AS
SELECT
  equipment_id,
  labor_cost,             -- measured 0 in the sample (F1) - no labor-savings claim
  material_cost           -- partial
FROM {catalog}.{schema}.cost_source;   -- TODO(F1): confirm actual-cost source

-- Row-level work-order detail (Level 2): one row per order, scope-locked + row-capped at query time.
-- Cutover target = the SOAR WOs sheet (112 cols); select only the reviewer-relevant columns. Actual
-- labor hrs / labor cost stay blank until Oxy posts labor actuals (F1) - the emptiness is the signal.
CREATE OR REPLACE VIEW {catalog}.{schema}.v_work_order_detail AS
SELECT
  equipment_id,
  order_number        AS wo_number,        -- SOAR WOs: Order_Number
  basic_start_date    AS order_date,       -- SOAR WOs: Basic_Start_Date
  wo_type             AS order_type,       -- SOAR WOs: WO_Type -> preventive/corrective/reactive
  maint_activity_type AS activity_type,    -- SOAR WOs: Maint_Activity_Type
  order_short_text    AS description,
  planned_work_hours  AS planned_hours,    -- SOAR Tasklist: Planned_Work_Hours
  actual_labor_hours,                      -- AFRU actuals (BLANK in the sample - F1)
  actual_material_cost AS material_cost,   -- SOAR Cost: Actual_Material_Cost (partial)
  actual_labor_cost    AS labor_cost,      -- SOAR Cost: Actual_Internal/External_Labor_Cost (0 - F1)
  work_center,
  order_status         AS status,
  time_window
FROM {catalog}.{schema}.work_order_source;   -- TODO(P1/F1): bind to governed WO extract

-- Row-level notification detail (Level 2): one row per notification, scope-locked + row-capped.
-- Cutover target = the SOAR Notifications sheet. Damage/cause codes are partial (~56%/51%); the
-- blank-coded rows are the coding gap the classifier flags.
CREATE OR REPLACE VIEW {catalog}.{schema}.v_notification_detail AS
SELECT
  equipment_id,
  notification_number,
  failure_start_date   AS failure_date,    -- SOAR Notifications: Failure_Start_Date
  damage_code,                             -- QMFE (partial)
  cause_code,                              -- QMUR (partial)
  object_part_code     AS object_part,     -- SOAR Notifications: Object_Part_Code
  breakdown_duration   AS breakdown_duration_hrs,
  linked_order         AS linked_wo,
  time_window
FROM {catalog}.{schema}.notification_source;  -- TODO(F1): confirm findings coding source

-- Measurement readings (ABSENT in the SOAR sample: 0/175). CBM stays fail-closed until real
-- reading time-series exist. Point-master data alone is NOT sufficient.
CREATE OR REPLACE VIEW {catalog}.{schema}.v_measurement_reading_timeseries AS
SELECT
  equipment_id,
  measurement_point,
  reading_value,
  reading_ts
FROM {catalog}.{schema}.measurement_source;  -- TODO(F1): confirm reading source; empty until then
