---
title: SAP PM data model vs MAX - usage and completeness reference
tags: [max-agent, data, sap, data-readiness, houston]
status: living reference
sources: [SAP PM Data Model pre-read, Project Soar Data Set.xlsx, Oxy PM Data Gap Analysis, MAX Agent source]
---

# SAP PM tables vs MAX: what we use, and what to check for completeness

How each SAP Plant-Maintenance object in the workshop data model maps to MAX's tools, whether the
synthetic demo exercises it, and the best-practice completeness checks MAX should run and flag.
Grounded in the SAP PM data model pre-read, the Project Soar extract, and the MAX Agent source
(`max_agent/evidence.py`, `max_agent/tools/classification.py`, `max_agent/tools/readiness.py`).

> **Bottom line.** Tool coverage is broad - the demo already exercises most of these domains with the
> *same* deterministic logic MAX uses on real SAP, just on synthetic data. The gap is not tools, it is
> **data quality**: frequency, validated criticality, notification coding, fresh readings, and labor
> cost are the fields that make scored verdicts fail closed today. This is correct fail-closed
> behaviour, not a defect - but "in sync with the requirement" is false for anything beyond PM
> effectiveness triage until those close.

**At a glance**

| | Count | Meaning |
|---|---|---|
| Modelled | 11 | demo exercises it - same tool logic, synthetic data |
| Partial | 5 | proxy only, or a real quality gap |
| Not modelled | 4 | SAP object not modelled in the demo yet |
| Thresholds set | 0 | classifier cut-offs are BU_DEFINED - a Houston decision |

**Legend** - Demo: `Yes` = exercised (synthetic) / `Partial` = proxy or quality gap / `No` = not
modelled. Completeness flags are what a dedicated auditor tool should raise.

---

## A. Asset and classification

| SAP table(s) | What it contains | How it helps MAX | Demo | Demo behaviour | Completeness check - flag if |
|---|---|---|---|---|---|
| `EQUI / EQKT / EQUZ` | Equipment master, short text, time segment: number, category, class, plant, cost centre | Anchors every asset-scoped question; class drives like-equipment comparison | Yes | Same logic; synthetic fleet master data | Equipment number, plant, class present; **flag** equipment with no functional location |
| `IFLOT / IFLOTX / ILOA` | Functional location + PM object location: FLOC id, hierarchy, planning plant | Scope (operated / JV), FLOC roll-ups, hierarchy for impact | Yes | Same logic; synthetic FLOC + plant | FLOC present and linked; **flag** orphaned equipment or missing operated/JV tag |
| `AUSP / KSSK / CABN` | Classification: criticality class, ABC/HLM, catalog profile | Criticality is the do-not-touch guardrail; catalog profile sets the coding vocabulary | Partial | Synthetic criticality code + computed ABC; real MAX must enforce validated SAP 0/1/2/3/4/N | **Flag** criticality = `0-Pending Assessment` / unvalidated - guardrail cannot be trusted |
| `JEST / TJ02T / TJ30T` | Object and user status: system status (INST, DLFL), user status (CRW) | In-service vs deleted; critical-work flag on orders and task lists | No | Not modelled; CRW inferred from criticality in the task-list check | **Flag** deletion-flagged / inactive equipment held in analysis scope |

## B. Plan and strategy

| SAP table(s) | What it contains | How it helps MAX | Demo | Demo behaviour | Completeness check - flag if |
|---|---|---|---|---|---|
| `MPLA / MPOS` | Maintenance plan + item: plan number, plan type, item to equipment to task-list link | The PM under review; whether the asset has any PM coverage | Yes | Same logic; synthetic `pm_id` + plan link | **Flag** equipment with no PM plan (78% of Soar equipment lack visible coverage) |
| `MMPT / T351` | Maintenance cycle + strategy: cycle length and unit (e.g. 90 / DAY), strategy package | Frequency-optimisation target; no frequency change is possible without it | Yes | Same logic; synthetic `current_strategy.cycle` | **Flag** missing cycle / frequency / unit (59% of Soar plans missing frequency) |
| `MHIS / MHIO` | Maintenance plan + call history: scheduling history, due / call / completion dates | Planned-vs-actual scheduling adherence over time | No | Not modelled; adherence not computed | **Flag** active plans with no calls generated / no completion history |

## C. Task list and BOM

| SAP table(s) | What it contains | How it helps MAX | Demo | Demo behaviour | Completeness check - flag if |
|---|---|---|---|---|---|
| `PLKO / PLAS / PLPO` | Task-list header / selection / operation: work centre, planned hours, people, duration | Task-list cleanup, planned-hours baseline, actual work content | Yes | Same logic; synthetic readiness drives `task_list_bom_readiness` | **Flag** zero planned hours (18% of Soar ops) or more than one frequency per operation |
| `PLMZ / STPO / STKO / MAST` | Component to operation, BOM item/header, material to BOM link | Parts / component readiness for a change; staging the right spares | Yes | Same logic; `materials` list empty, mirroring Soar | **Flag** operations that need parts with no component/BOM linked (82% of Soar ops) |
| `MARA / MAKT` | Material master + text: material number, type, valuation | Identify spares, material cost basis for a component change | Partial | Material cost proxy only; no material master modelled | **Flag** components referencing a missing material master or valuation |

## D. Work-order execution

| SAP table(s) | What it contains | How it helps MAX | Demo | Demo behaviour | Completeness check - flag if |
|---|---|---|---|---|---|
| `AUFK / AFIH / AFKO / AFPO` | Order master + maintenance header + operations: type, cost object, malfunction/breakdown link | Work-order history; PM vs corrective vs reactive typing; the failure to PM linkage | Yes | Same tool (`work_order_history`); synthetic executor now, real via `views.sql` at cutover | Orders typed and linked to equipment; **flag** untyped or unlinked orders |
| `AFRU` | Order confirmation: actual hours / work per operation | Planned-vs-actual hours; the only source of real labor content | Partial | Does *not* penalise on empty actuals - flags LOW confidence, routes to SME (mirrors Soar's empty AFRU) | **Flag** absent confirmations - no planned-vs-actual, no labor ROI |
| `AUFM / MSEG` | Goods movement / parts consumed: issued vs reserved (RESB) | Spare effectiveness - planned vs actually-used parts | No | Not modelled | **Flag** orders with reserved-but-not-issued parts / no movement posted |
| `ACDOCA` (+ Cost) | Universal journal / order settlement: actual material, labor, services cost | Cost per finding, ROI ranking, honest cost view | Partial | Material-only cost; `labor_cost = 0` so no savings claim (mirrors Soar) | **Flag** labor cost absent (0% in Soar) - block any ROI / savings claim |

## E. Notification and findings

| SAP table(s) | What it contains | How it helps MAX | Demo | Demo behaviour | Completeness check - flag if |
|---|---|---|---|---|---|
| `QMEL` | Notification header: number, type, malfunction start/end, breakdown flag, equipment link | Failure events, breakdown history, the PM to failure linkage | Yes | Same tool (`notification_findings`); synthetic | **Flag** notifications not linked to equipment or missing breakdown flag (11.5% coded in Soar) |
| `QMFE / QMUR` | Finding + cause: damage code (FECOD), cause code (URCOD), object part | Reliability signals and root cause; empty coding = blind spot or over-maintenance | Yes | Same logic; synthetic coding % (`damage_coded_pct` / `cause_coded_pct`) | **Flag** uncoded damage/cause (44-49% missing in Soar) - classifier drops to describe-and-flag |
| `QPCD / QPGR / T352R` | Catalog codes / groups / revisions: standardised damage/cause vocabulary per catalog profile | Confirms codes come from the equipment's approved catalog, not free text | No | Catalog not modelled; coding % is a proxy | **Flag** notification codes off the equipment's catalog profile or free-text only |

## F. Condition (CBM) and measurement

| SAP table(s) | What it contains | How it helps MAX | Demo | Demo behaviour | Completeness check - flag if |
|---|---|---|---|---|---|
| `IMPTT` | Measuring point: point, characteristic, unit, target value, limits | Whether condition monitoring is even set up on the asset | Yes | Same logic; `measurement_points_present` flag (false in synthetic) | **Flag** points with no characteristic / unit / limits (100% missing in Soar) |
| `IMRG` | Measurement document: reading value, date, valuation | CBM conversion needs a real reading time-series - fails closed without it | Yes | Same fail-closed rule (`cbm_measurement_readiness`); no real readings -> RED | **Flag** stale (~2019) or unmatched readings (0.6% matched in Soar) - CBM blocked |

## G. Risk and scoring (not a single SAP table)

| Source | What it contains | How it helps MAX | Demo | Demo behaviour | Completeness check - flag if |
|---|---|---|---|---|---|
| Risk Scorecard (BU_DEFINED) | Criticality x consequence risk matrix and the classifier scoring cut-offs | The thresholds a scored verdict needs; without them MAX describes and flags | Partial | Risk RAG modelled; thresholds null -> every asset is Missing Evidence (honest fail-closed) | **Flag** thresholds unset (`status: BU_DEFINED`) - a Houston decision, not SAP data |

---

## How MAX should check it - a dedicated completeness-audit tool

One tool that walks every SAP-PM domain for a scoped equipment (or the whole fleet), tests
best-practice completeness, and returns a per-domain RAG plus a flat list of flags naming the exact
SAP field and Soar sheet to fix. It reuses MAX's existing SAP-source map (`evidence.DOMAIN_SAP`) and
the standard tool envelope. Best-practice thresholds are passed in (`completeness_config`, BU_DEFINED),
never hardcoded - so it stays fail-closed and invents no Oxy value.

Proposed home in the codebase: `max_agent/tools/completeness.py`, registered in the tool library and
feeding both the "can MAX answer this?" preflight and the PM Health view.

```python
"""data_completeness_auditor - dedicated SAP-PM data-completeness review tool for MAX.

For a scoped equipment (or a portfolio slice), check each SAP PM domain against best-practice
completeness rules; return a per-domain RAG + a flat list of flags naming the exact SAP field and
Project Soar sheet to fix, plus an overall verdict. Thresholds are BU_DEFINED (passed in, never
hardcoded), so the auditor stays fail-closed and never invents an Oxy value.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
from ..schemas import STATUS_SUCCESS, STATUS_WARNING, tool_envelope


def _blank(v: Any) -> bool:
    return v is None or v == "" or v == 0 or v == []


# One rule set per SAP domain. required = fields SAP best practice expects populated;
# quality = (name, predicate, flag_message) checks beyond mere presence.
# sap = source table(s); soar = the Project Soar sheet standing in for it today.
COMPLETENESS_RULES: Dict[str, Dict[str, Any]] = {
    "criticality": {
        "sap": "EQUI.ABCKZ / AUSP", "soar": "Eq & Floc: Equipment_Criticality",
        "required": ["criticality_code"],
        "quality": [("validated",
            lambda r, cfg: r.get("criticality_validation_status") == "VALIDATED"
                            and str(r.get("criticality_code")) not in ("0", "None", ""),
            "criticality unvalidated (0-Pending Assessment) - guardrail cannot be trusted")],
    },
    "pm_plans": {
        "sap": "MPLA / MMPT / MPOS", "soar": "Plans & Items: Cycle / Frequency / Maint_Strategy",
        "required": ["plan_number", "cycle", "frequency", "maint_strategy"],
        "quality": [],
    },
    "task_lists": {
        "sap": "PLKO / PLPO", "soar": "Tasklist: Work_Center / Planned_Work_Hours",
        "required": ["work_center", "planned_work_hours", "number_of_people"],
        "quality": [("single_frequency",
            lambda r, cfg: r.get("single_frequency_per_operation", True) is True,
            "operation carries more than one frequency")],
    },
    "notifications_failures": {
        "sap": "QMEL / QMFE / QMUR (+ QPCD catalog)", "soar": "Notifications: Damage_Code / Cause_Code",
        "required": ["damage_code", "cause_code"],
        "quality": [("object_part", lambda r, cfg: not _blank(r.get("object_part_code")),
            "object-part code missing - failure-mode picture incomplete")],
    },
    "cost_actuals": {
        "sap": "ACDOCA / order settlement", "soar": "Cost: Actual_Material_Cost / Actual_*_Labor_Cost",
        "required": ["actual_material_cost"],
        "quality": [("labor_posted", lambda r, cfg: not _blank(r.get("actual_labor_cost")),
            "labor cost not posted - no savings / ROI claim is defensible")],
    },
    "recent_readings": {
        "sap": "IMRG", "soar": "Measurement Points: Measurement_Reading / _Date_Time",
        "required": ["last_reading_value", "last_reading_date"],
        "quality": [("fresh",
            lambda r, cfg: _within_days(r.get("last_reading_date"), cfg.get("reading_freshness_days")),
            "no reading within the freshness window (stale) - CBM cannot be scored")],
    },
    "risk_scorecard": {
        "sap": "not SAP - Oxy Risk Scorecard (BU_DEFINED)", "soar": "Houston workshop decision",
        "required": [],
        "quality": [("thresholds_set", lambda r, cfg: cfg.get("classifier_thresholds_set") is True,
            "classifier thresholds unset (BU_DEFINED) - MAX describes and flags, cannot score")],
    },
    # ... equipment, components, work_orders, work_order_actuals, measurement_points: same shape.
}


def _within_days(date_value, window_days) -> bool:
    # TODO: parse date_value, return True when it is within window_days of 'now'.
    ...


def data_completeness_auditor(
    record: Dict[str, Any],
    domains: Optional[List[str]] = None,
    completeness_config: Optional[Dict[str, Any]] = None,
    max_flags: int = 12,
) -> Dict[str, Any]:
    """Audit ONE scoped equipment record for SAP-PM data completeness.

    record: the flattened per-equipment view (real SAP views at cutover; synthetic fleet today).
    completeness_config: BU_DEFINED knobs (reading_freshness_days, classifier_thresholds_set, ...)
    - passed in, never hardcoded. Returns per-domain RAG + a flat, actionable flag list.
    """
    cfg = completeness_config or {}
    domains = domains or list(COMPLETENESS_RULES)
    per_domain: Dict[str, Any] = {}
    flags: List[Dict[str, Any]] = []

    for d in domains:
        rule = COMPLETENESS_RULES.get(d)
        if not rule:
            continue
        missing = [f for f in rule["required"] if _blank(record.get(f))]
        quality_flags = [msg for (_n, pred, msg) in rule["quality"] if not pred(record, cfg)]
        rag = "RED" if missing else ("YELLOW" if quality_flags else "GREEN")
        per_domain[d] = {"rag": rag, "missing_fields": missing, "quality_flags": quality_flags,
                         "sap_source": rule["sap"], "soar_sheet": rule["soar"]}
        for f in missing:
            flags.append({"domain": d, "issue": f"missing: {f}",
                          "sap_source": rule["sap"], "soar_sheet": rule["soar"]})
        for msg in quality_flags:
            flags.append({"domain": d, "issue": msg,
                          "sap_source": rule["sap"], "soar_sheet": rule["soar"]})

    rank = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    overall = max((v["rag"] for v in per_domain.values()), key=lambda r: rank[r], default="GREEN")

    return tool_envelope(
        tool="data_completeness_auditor",
        status=STATUS_SUCCESS if overall == "GREEN" else STATUS_WARNING,
        summary=f"Data completeness {overall}: {len(flags)} field(s) to remediate.",
        data={"overall_completeness": overall, "per_domain": per_domain,
              "flags": flags[:max_flags], "flag_count": len(flags)},
        confidence="high", scope_validated=True,
    )


def portfolio_completeness(records: List[Dict[str, Any]], **kw) -> Dict[str, Any]:
    # Population view: run per equipment, aggregate coverage % per domain
    # (this is where "59% of plans missing frequency" comes from).
    audits = [data_completeness_auditor(r, **kw)["data"] for r in records]
    coverage: Dict[str, Any] = {}
    for d in COMPLETENESS_RULES:
        graded = [a["per_domain"][d]["rag"] for a in audits if d in a["per_domain"]]
        n = len(graded) or 1
        coverage[d] = {"green_pct": round(100 * sum(g == "GREEN" for g in graded) / n),
                       "red_pct": round(100 * sum(g == "RED" for g in graded) / n), "n": len(graded)}
    return {"coverage_by_domain": coverage, "equipment_audited": len(records)}
```

---

## Notes

- The auditor is a thin, additive layer: it reuses the SAP-source mapping already in
  `max_agent/evidence.py` (`DOMAIN_SAP` / `REASON_SAP`) and returns the same envelope as every other
  MAX tool, so it slots straight into the tool library.
- Every threshold it applies (reading-freshness window, minimum coverage %, whether criticality `0`
  is a hard block) is a `completeness_config` value confirmed by Oxy at Houston - the tool ships
  fail-closed with them unset.
- Coverage percentages are from the Project Soar extract via the existing gap analysis
  (`outputs/Oxy_PM_Process_App_Data_Gap_Analysis_Applexus_McKinsey.pptx`).

## Related

- `CONFORMANCE.md` - conformance of the build to the specs (fail-closed, do-not-invent).
- `ORCHESTRATION_DESIGN.md` - how MAX selects and sequences tools.
- `max_agent/evidence.py` - the SAP-source data-needs mapping this reference is built on.
- `max_agent/tools/classification.py` - `data_readiness_gate` and the classifier reason codes.
- SAP PM Data Model pre-read + Day 2 "Data, Risk & Agent Design" deck (Houston workshop folder).
