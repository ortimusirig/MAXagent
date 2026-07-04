"""Comparison tools (Wave B): like_equipment_matcher, pm_comparison_engine.

Support PM standardization across like equipment. Deterministic matching and comparison; no
invented Oxy value, no savings claim.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..schemas import STATUS_SUCCESS, STATUS_WARNING, tool_envelope


def like_equipment_matcher(target: Dict[str, Any], fleet: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Find comparable equipment by asset class and criticality (extendable to object type / duty / location)."""
    tclass = target.get("asset_class")
    tcrit = (target.get("master_data", {}) or {}).get("criticality", {}).get("code")
    cohort = []
    for a in fleet or []:
        if a.get("equipment_id") == target.get("equipment_id"):
            continue
        acrit = (a.get("master_data", {}) or {}).get("criticality", {}).get("code")
        if a.get("asset_class") == tclass:
            match = "class+criticality" if acrit == tcrit else "class"
            cohort.append({"equipment_id": a.get("equipment_id"), "asset_class": a.get("asset_class"),
                           "criticality": acrit, "match_basis": match})
    return tool_envelope(
        tool="like_equipment_matcher",
        status=STATUS_SUCCESS if cohort else STATUS_WARNING,
        summary=f"{len(cohort)} like-equipment matches for {target.get('equipment_id')} (class {tclass}).",
        data={"target": target.get("equipment_id"), "asset_class": tclass, "cohort": cohort},
        confidence="medium" if cohort else "low",
    )


def pm_comparison_engine(target: Dict[str, Any], cohort_assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare frequency / strategy / package / planned hours across a like-equipment cohort."""
    def _row(a: Dict[str, Any]) -> Dict[str, Any]:
        s = a.get("current_strategy", {})
        r = a.get("readiness", {})
        return {"equipment_id": a.get("equipment_id"), "strategy_type": s.get("strategy_type"),
                "cycle": s.get("cycle"), "package": r.get("maintenance_package"),
                "planned_hours": r.get("planned_hours"), "work_center": r.get("work_center")}

    target_row = _row(target)
    rows = [_row(a) for a in cohort_assets or []]
    # Standardization candidate: a cohort strategy/cycle that differs from the target.
    differing = [r for r in rows if (r["strategy_type"], r["cycle"]) != (target_row["strategy_type"], target_row["cycle"])]
    return tool_envelope(
        tool="pm_comparison_engine", status=STATUS_SUCCESS,
        summary=f"Compared {target.get('equipment_id')} against {len(rows)} like PMs; {len(differing)} differ on strategy/cycle.",
        data={"target": target_row, "cohort": rows,
              "standardization_candidates": [r["equipment_id"] for r in differing],
              "note": "standardization is a draft recommendation; each change still clears oxy_gate_check"},
        confidence="medium",
    )
