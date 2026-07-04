"""Evidence digest + SAP data-needs mapping.

Two jobs, both presentation-layer only (no gate/label/threshold logic here):

1. ``build_evidence_digest`` turns the evidence MAX ALREADY retrieves (work orders, cost, findings)
   into short plain-language analysis lines - the "what the data shows" that justifies the
   recommendation. It only reports numbers the deterministic tools computed; it never invents a rate.

2. ``data_needs`` answers "what should MAX do when there isn't enough data to conclude": it names the
   SPECIFIC Oxy SAP data that would let MAX score effectiveness, grounded in the Project Soar SAP
   extract (sheets Eq & Floc, Plans & Items, Tasklist, Components, WOs, Notifications, Measurement
   Points, Cost). These are the source FIELDS/objects - not Oxy thresholds or values.

Fail-closed and do-not-invent stay intact: MAX describes and flags what the data shows, and states
plainly what is still needed, but never asserts a scored verdict the deterministic tools did not make.
"""

from __future__ import annotations

from typing import Any, Dict, List

# --- classifier reason code -> (gap phrase, what is needed, SAP source, kind) ----------------------
# kind: "sap" = a real SAP data gap; "decision" = an Oxy workshop decision (not a data gap).
REASON_SAP: Dict[str, Dict[str, str]] = {
    "THRESHOLDS_UNSET": {
        "gap": "Oxy has not confirmed the classifier scoring thresholds yet",
        "need": "Oxy-confirmed classifier thresholds (Risk Scorecard)",
        "sap_source": "Houston workshop decision (BU_DEFINED) - not a SAP data gap",
        "kind": "decision",
    },
    "CRITICALITY_UNVALIDATED": {
        "gap": "equipment criticality is not validated",
        "need": "a validated equipment criticality",
        "sap_source": "Eq & Floc: Equipment_Criticality / Functional_Location_Criticality (many read '0-Pending Assessment')",
        "kind": "sap",
    },
    "FAILURE_SIGNAL_NULL": {
        "gap": "no post-PM failure signal could be computed",
        "need": "failure / breakdown history linked to this equipment",
        "sap_source": "Notifications: Failure_Start_Date / Breakdown_Duration (+ Damage/Cause codes)",
        "kind": "sap",
    },
    "SIGNAL_CONFIDENCE_LOW": {
        "gap": "the effectiveness-signal confidence is low",
        "need": "more complete work-order and notification history",
        "sap_source": "WOs + Notifications coverage for this equipment",
        "kind": "sap",
    },
    "NOTIFICATION_CODING_ABSENT": {
        "gap": "failure notifications are not coded",
        "need": "coded failure notifications (damage / cause / object-part)",
        "sap_source": "Notifications: Damage_Code / Cause_Code / Object_Part_Code",
        "kind": "sap",
    },
    "COST_ACTUALS_ABSENT": {
        "gap": "actual maintenance costs are not posted",
        "need": "posted actual costs on the work orders",
        "sap_source": "Cost: Actual_Total_Cost / Actual_Material_Cost / Actual_Internal_Labor_Cost",
        "kind": "sap",
    },
    "MEASUREMENT_READINGS_ABSENT": {
        "gap": "there is no current condition-reading series",
        "need": "current measurement-point readings",
        "sap_source": "Measurement Points: Measurement_Reading / Measurement_Date_Time (latest reading is stale)",
        "kind": "sap",
    },
}

# --- data_readiness_gate domain -> (what is needed, SAP source) ------------------------------------
DOMAIN_SAP: Dict[str, Dict[str, str]] = {
    "equipment": {"need": "equipment master", "sap_source": "Eq & Floc"},
    "pm_plans": {"need": "maintenance plans", "sap_source": "Plans & Items: Plan_Number / Cycle / Maint_Strategy"},
    "work_orders": {"need": "work-order history", "sap_source": "WOs: WO_Type / Maint_Activity_Type"},
    "task_lists": {"need": "task lists", "sap_source": "Tasklist: Operation_Description / Work_Center / Planned_Work_Hours"},
    "notifications_failures": {"need": "coded failure notifications", "sap_source": "Notifications: Damage_Code / Cause_Code"},
    "risk_scorecard": {"need": "risk scorecard", "sap_source": "Oxy Risk Scorecard (Houston workshop)"},
    "criticality": {"need": "validated criticality", "sap_source": "Eq & Floc: Equipment_Criticality"},
    "work_centers": {"need": "work-center assignments", "sap_source": "Tasklist: Work_Center"},
    "planned_hours": {"need": "planned hours", "sap_source": "Tasklist: Planned_Work_Hours / Number_Of_People"},
    "package_assignments": {"need": "maintenance-package assignments", "sap_source": "Tasklist: Maint_Package"},
    "bom_components": {"need": "task-list components (BOM)", "sap_source": "Components: Material_Group / Cost_Element / Net_Price"},
    "material_availability": {"need": "material availability", "sap_source": "Components + Purchasing (Po_Number)"},
    "task_list_service": {"need": "service task list", "sap_source": "Tasklist: Activity_Type / Vendor_Name"},
    "procurement_service": {"need": "service procurement", "sap_source": "WOs: Po_Number / Vendor_Number"},
    "measurement_points": {"need": "measurement points", "sap_source": "Measurement Points: Measurement_Point_Number"},
    "characteristic_unit": {"need": "measurement characteristic & unit", "sap_source": "Measurement Points: Characteristic / Characteristic_Unit"},
    "recent_readings": {"need": "recent condition readings", "sap_source": "Measurement Points: Measurement_Reading / Measurement_Date_Time"},
}

# Cost-basis code -> plain phrase (honest cost view; no labor-savings claim when labor is not posted).
_BASIS_LABEL = {
    "material_services_partial_only": "material / services only (labor actuals not posted)",
    "material_only": "material only (no labor actuals)",
    "full": "full actuals (labor + material)",
}

_PREVENTIVE = {"preventive", "pm01", "pm02", "planned", "pm"}
_CORRECTIVE = {"corrective", "crmn", "reactive", "breakdown", "crm"}


def _humanize_window(tw: Any) -> str:
    m = {"LAST_12_MONTHS": "last 12 months", "LAST_24_MONTHS": "last 24 months",
         "LAST_36_MONTHS": "last 36 months"}
    return m.get(str(tw), "the review window")


def _pct(x: Any) -> str:
    try:
        return f"{round(float(x) * 100)}%"
    except (TypeError, ValueError):
        return "n/a"


def build_evidence_digest(result: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate the retrieved evidence into safe-to-cite counts + plain-language analysis lines.

    Reads result['evidence'] (the work_order_history / cost_summary / notification_findings records
    the orchestrator already fetched via run_scoped_sql). Returns structured fields plus ``lines`` -
    the "what the data shows" bullets. Numbers come only from the tool records; nothing is invented.
    """
    ev = result.get("evidence") or {}
    wo_records = ev.get("work_order_history") or []
    find_records = ev.get("notification_findings") or []
    cost_records = ev.get("cost_summary") or []

    by_type: Dict[str, int] = {}
    for r in wo_records:
        ot, n = r.get("order_type"), r.get("n")
        if ot is not None and isinstance(n, (int, float)):
            by_type[str(ot)] = by_type.get(str(ot), 0) + int(n)
    total = sum(by_type.values())
    corrective = sum(v for k, v in by_type.items() if k.lower() in _CORRECTIVE)
    preventive = sum(v for k, v in by_type.items() if k.lower() in _PREVENTIVE)

    findings = find_records[0] if find_records else {}
    damage_pct = findings.get("damage_coded_pct")
    cause_pct = findings.get("cause_coded_pct")

    cost = cost_records[0] if cost_records else {}
    labor = cost.get("labor_cost")
    material = cost.get("material_cost")
    basis = cost.get("basis")

    lines: List[str] = []
    if total:
        breakdown = ", ".join(f"{v} {k}" for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]))
        line = f"Work-order history ({_humanize_window(result.get('time_window'))}): {total} orders - {breakdown}."
        if corrective and preventive:
            line += f" That is {corrective} corrective/reactive against {preventive} preventive."
        lines.append(line)
    if damage_pct is not None or cause_pct is not None:
        lines.append(
            f"Failure coding: {_pct(damage_pct)} of notifications carry a damage code, "
            f"{_pct(cause_pct)} a cause code."
        )
    if basis is not None or material is not None:
        basis_txt = _BASIS_LABEL.get(str(basis), str(basis) if basis else "partial")
        claim = " so no labor-savings claim is defensible" if (labor in (0, 0.0, None)) else ""
        lines.append(f"Cost basis: {basis_txt}{claim}.")

    return {
        "work_orders_total": total,
        "work_orders_by_type": by_type,
        "corrective_count": corrective,
        "preventive_count": preventive,
        "damage_coded_pct": damage_pct,
        "cause_coded_pct": cause_pct,
        "labor_cost": labor,
        "material_cost": material,
        "cost_basis": basis,
        "lines": lines,
    }


def is_insufficient(result: Dict[str, Any]) -> bool:
    """True when MAX cannot pass a scored effectiveness verdict (describe-and-flag / RED readiness)."""
    if result.get("classifier_label") == "Missing Evidence":
        return True
    if result.get("data_readiness") == "RED":
        return True
    return False


def data_needs(result: Dict[str, Any]) -> List[Dict[str, str]]:
    """The specific SAP data (or Oxy decision) MAX still needs before it can score effectiveness.

    Grounded in the Project Soar SAP extract. Returns [] when the asset is not in a describe-and-flag /
    insufficient-data state (e.g. out of scope, or a confident label). Deduped, capped for readability.
    """
    if not is_insufficient(result):
        return []
    needs: List[Dict[str, str]] = []

    reason = result.get("classifier_reason")
    if reason in REASON_SAP:
        needs.append(dict(REASON_SAP[reason]))

    for d in (result.get("missing_domains") or []):
        if d in DOMAIN_SAP:
            m = DOMAIN_SAP[d]
            needs.append({"gap": f"{m['need']} not ready", "need": m["need"],
                          "sap_source": m["sap_source"], "kind": "sap"})

    seen, out = set(), []
    for n in needs:
        key = (n["need"], n["sap_source"])
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out[:5]
