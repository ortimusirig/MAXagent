"""Parameterized SQL templates for repeatable core metrics + a local synthetic executor.

The templates are the REAL-path SQL used once a Databricks SQL warehouse and governed views are
bound (see views.sql). Until then, `local_synthetic_executor` serves the same shapes from the
manufactured fleet so `run_scoped_sql` works offline. Templates are scoped by equipment/time so
Genie / SQL never run unscoped (07).

These reference curated views (v_*) rather than raw SAP tables; the view layer is where real Oxy
field mapping lands after the workshop. No Oxy value is hardcoded here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
}

_RELATION_BY_TEMPLATE = {
    "work_order_history": "v_work_order_history",
    "notification_findings": "v_notification_history",
    "cost_summary": "v_cost_summary",
    "pm_plan_current": "v_pm_plan_current",
}


def render_sql(template_name: str, params: Dict[str, Any], catalog: Optional[str] = None, schema: Optional[str] = None) -> str:
    tmpl = TEMPLATES.get(template_name)
    if tmpl is None:
        raise KeyError(f"unknown SQL template: {template_name}")
    relation = _RELATION_BY_TEMPLATE.get(template_name, template_name)
    if catalog and schema:
        relation = f"{catalog}.{schema}.{relation}"
    return tmpl.format(relation=relation)


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
        return []

    return _execute
