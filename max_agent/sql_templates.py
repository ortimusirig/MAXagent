"""Parameterized SQL templates for repeatable core metrics + a local synthetic executor.

The templates are the REAL-path SQL used once a Databricks SQL warehouse and governed views are
bound (see views.sql). Until then, `local_synthetic_executor` serves the same shapes from the
manufactured fleet so `run_scoped_sql` works offline. Templates are scoped by equipment/time so
Genie / SQL never run unscoped (07).

These reference curated views (v_*) rather than raw SAP tables; the view layer is where real Oxy
field mapping lands after the workshop. No Oxy value is hardcoded here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Trusted server-side row cap for LIMIT (our own constant, never user input). Mirrors the orchestrator's
# _DETAIL_ROW_CAP; inlined as an integer literal so LIMIT needs no parameter marker.
_DEFAULT_ROW_CAP = 50
_MARKER_RE = re.compile(r":(\w+)")

# name -> parameterized statement (real path). :equipment_id / :time_window are bound params.
TEMPLATES: Dict[str, str] = {
    "work_order_history": (
        "SELECT order_type, count(*) AS n FROM {relation} "
        "WHERE equipment_id = :equipment_id AND time_window = :time_window GROUP BY order_type"
    ),
    "notification_findings": (
        "SELECT damage_code, cause_code, count(*) AS n FROM {relation} "
        "WHERE equipment_id = :equipment_id GROUP BY damage_code, cause_code"
    ),
    "cost_summary": (
        "SELECT sum(labor_cost) AS labor_cost, sum(material_cost) AS material_cost FROM {relation} "
        "WHERE equipment_id = :equipment_id"
    ),
    "pm_plan_current": (
        "SELECT pm_id, strategy_type, cycle, package FROM {relation} WHERE equipment_id = :equipment_id"
    ),
    # Row-level detail (Level 2): individual records, scope-locked + row-capped, NO GROUP BY.
    "work_order_detail": (
        "SELECT wo_number, order_date, order_type, activity_type, description, planned_hours, "
        "actual_labor_hours, material_cost, labor_cost, work_center, status FROM {relation} "
        "WHERE equipment_id = :equipment_id AND time_window = :time_window "
        "ORDER BY order_date DESC LIMIT :row_cap"
    ),
    "notification_detail": (
        "SELECT notification_number, failure_date, damage_code, cause_code, object_part, "
        "breakdown_duration_hrs, linked_wo FROM {relation} "
        "WHERE equipment_id = :equipment_id AND time_window = :time_window "
        "ORDER BY failure_date DESC LIMIT :row_cap"
    ),
    # Task-list components / spare parts (BOM), scope-locked. Feeds pm_bom_completeness (tool 28).
    "bom_components": (
        "SELECT component_code, description, material_group, on_pm_task_list FROM {relation} "
        "WHERE equipment_id = :equipment_id ORDER BY component_code"
    ),
}

_RELATION_BY_TEMPLATE = {
    "work_order_history": "v_work_order_history",
    "notification_findings": "v_notification_history",
    "cost_summary": "v_cost_summary",
    "pm_plan_current": "v_pm_plan_current",
    "work_order_detail": "v_work_order_detail",
    "notification_detail": "v_notification_detail",
    "bom_components": "v_bom",
}


def render_sql(template_name: str, params: Dict[str, Any], catalog: Optional[str] = None, schema: Optional[str] = None) -> str:
    tmpl = TEMPLATES.get(template_name)
    if tmpl is None:
        raise KeyError(f"unknown SQL template: {template_name}")
    relation = _RELATION_BY_TEMPLATE.get(template_name, template_name)
    if catalog and schema:
        relation = f"{catalog}.{schema}.{relation}"
    return tmpl.format(relation=relation)


def sql_execution_plan(
    template_name: str, params: Dict[str, Any], catalog: Optional[str] = None, schema: Optional[str] = None
) -> Tuple[str, List[Dict[str, Any]]]:
    """Return ``(statement, named_parameters)`` for the Databricks Statement Execution API.

    Scope predicates (``:equipment_id`` / ``:time_window``) stay as NAMED MARKERS and are BOUND
    server-side (``named_parameters``), never string-interpolated - so the warehouse enforces the scope
    filter and there is no SQL-injection surface (07: Genie/SQL never run unscoped). ``row_cap`` is a
    trusted server-side integer (our own cap, not user input), so it is inlined as a validated integer
    literal to avoid a parameter marker inside ``LIMIT``. A scope predicate with no value is left as an
    unbound marker on purpose: the statement then FAILS at the warehouse (fail-closed) rather than
    running without its scope filter.
    """
    statement = render_sql(template_name, params, catalog=catalog, schema=schema)
    if ":row_cap" in statement:
        statement = statement.replace(":row_cap", str(int(params.get("row_cap") or _DEFAULT_ROW_CAP)))
    template = TEMPLATES.get(template_name, "")
    marker_names = [n for n in dict.fromkeys(_MARKER_RE.findall(template)) if n != "row_cap"]
    named_parameters = [
        {"name": name, "value": str(params.get(name))}
        for name in marker_names
        if params.get(name) is not None
    ]
    return statement, named_parameters


def local_synthetic_executor(fleet_index: Dict[str, Dict[str, Any]]):
    """A `(template_name, params) -> rows` executor backed by the synthetic fleet.

    Wired into `run_scoped_sql` when no Databricks SQL warehouse is bound. Rows are clearly
    synthetic (they come from the manufactured fleet).
    """

    def _execute(template_name: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        eq = params.get("equipment_id")
        asset = fleet_index.get(eq)
        if asset is None:
            return []
        if template_name == "work_order_history":
            wo = asset.get("wo_history", {})
            return [{"order_type": k, "n": v} for k, v in wo.items()]
        if template_name == "notification_findings":
            f = asset.get("findings", {})
            return [{"damage_coded_pct": f.get("damage_coded_pct"), "cause_coded_pct": f.get("cause_coded_pct")}]
        if template_name == "cost_summary":
            c = asset.get("cost", {})
            return [{"labor_cost": c.get("labor_cost"), "material_cost": c.get("material_cost"), "basis": c.get("basis")}]
        if template_name == "pm_plan_current":
            s = asset.get("current_strategy", {})
            return [{"pm_id": asset.get("pm_id"), "strategy_type": s.get("strategy_type"), "cycle": s.get("cycle")}]
        if template_name == "work_order_detail":
            return list(asset.get("wo_detail", []))[: int(params.get("row_cap") or 50)]
        if template_name == "notification_detail":
            return list(asset.get("notif_detail", []))[: int(params.get("row_cap") or 50)]
        if template_name == "bom_components":
            return list(asset.get("bom", []))
        return []

    return _execute
