"""READ-ONLY LangChain tools for the MAX Agent FREE-FLOW loop.

These are the tools the FREE-FLOW loop (agent_loop.run_free_flow_agent) may call to answer a follow-up
about the asset whose governance decision has ALREADY been computed deterministically. `governed_decision`
returns that authoritative result; the model must cite it and never contradict it. Every tool here is
READ-ONLY: it reads the frozen decision or fetches scoped evidence/reliability/comparison/BOM/portfolio.
NONE decides a gate or a label, re-runs oxy_gate_check, or writes anything - so free-flow can explore and
explain but can never mint a new decision (a fresh decision goes through the governed lane).

Built as a factory that closes over the locked run context (mirrors the finance agent's make_*_tools
pattern). langchain_core is imported lazily so this package stays importable, and the app runs in
deterministic-only mode, when the agentic stack is not installed. The old FULL compute registry
(make_orchestration_tools) + enforce_mandatory were removed to prototypes/removed_governed_agentic_loop.py.
"""

from __future__ import annotations

from typing import Any, Dict, List


def make_agent_tools(agent, result: Dict[str, Any]) -> List[Any]:
    """Return the read-only LangChain tools bound to one governed result. Requires langchain_core (lazy).

    Used by the FREE-FLOW loop (bound to the LAST governed result). Every tool reads the frozen decision
    or fetches scoped evidence; none re-runs the gate or re-decides."""
    from langchain_core.tools import tool  # lazy: only needed when the agentic stack is present

    scope = result.get("scope", {}) or {}
    eid = result.get("equipment_id")
    time_window = result.get("time_window", "LAST_24_MONTHS")

    @tool
    def governed_decision() -> dict:
        """The authoritative, deterministic governance decision for this asset. This is the source of
        truth: cite it and NEVER contradict it, re-decide it, or state a different gate/label."""
        return {
            "equipment_id": eid,
            "gate_status": result.get("gate_status"),
            "effectiveness_label": result.get("classifier_label"),
            "recommendation_type": result.get("recommendation_type"),
            "recommendation_rationale": result.get("recommendation_rationale"),
            "gate_reason": result.get("gate_reason") or result.get("gate_review_trigger"),
            "required_approvers": result.get("required_approvers", []),
            "data_readiness": result.get("data_readiness_rag"),
            "do_not_optimize": result.get("do_not_optimize"),
        }

    @tool
    def evidence(question: str) -> dict:
        """Scoped evidence for THIS asset to answer a data question (work orders, cost, findings).
        Always scoped to the locked equipment; never runs unscoped. Args: question (natural language)."""
        from .tools import genie_query_scoped
        # Forward in_scope so free-flow evidence gets the SAME out-of-scope guard the governed lane has: an
        # out-of-scope prior result must never trigger a scoped Genie read (genie_query_scoped fails closed).
        env = genie_query_scoped(
            question,
            {"equipment_id": eid, "time_window": time_window,
             "scope_validated": scope.get("scope_validated", True), "in_scope": scope.get("in_scope")},
            client=agent.client,
        )
        d = env.get("data", {})
        ev = result.get("evidence", {}) or {}
        return {
            "genie_bound": d.get("genie_bound"),
            "genie_rows": d.get("row_count", 0),
            "work_order_history": ev.get("work_order_history", []),
            "cost_summary": ev.get("cost_summary", []),
            "notification_findings": ev.get("notification_findings", []),
        }

    @tool
    def like_equipment_comparison() -> dict:
        """Compare this asset's PM to like equipment (same class) and list standardization candidates.
        Read-only; standardization is a draft, and each change still clears the gate."""
        cmp = result.get("comparison_result")
        if not cmp:
            return {"note": "comparison not available (asset is out of analysis scope)"}
        return {"cohort": cmp.get("cohort", []), "standardization_candidates": cmp.get("standardization_candidates", [])}

    @tool
    def execution_readiness() -> dict:
        """Execution-readiness for this asset: task list / object dependency, materials, procurement,
        contractor, CBM measurement, planned hours; plus any active trial. Read-only RAG statuses."""
        checks = result.get("readiness_checks") or {}
        out = {}
        for name, data in checks.items():
            out[name] = (
                data.get("task_list_readiness") or data.get("material_readiness")
                or data.get("procurement_readiness") or data.get("contractor_readiness")
                or data.get("cbm_readiness") or data.get("calibration")
            )
        if result.get("trial"):
            out["trial"] = result["trial"].get("decision")
        return out or {"note": "readiness not available (asset is out of analysis scope)"}

    @tool
    def reliability() -> dict:
        """Reliability EVIDENCE for this asset: MTBF/MTTR/availability, the Weibull failure-hazard shape
        + P(fail)/RUL, and the top failure modes. Read-only evidence - it does NOT change the gate or
        label, and the judgment thresholds are BU-defined/unset."""
        rel = result.get("reliability") or {}
        return {"metrics": rel.get("metrics"), "weibull": rel.get("weibull"),
                "failure_modes": rel.get("failure_modes"),
                "interpretation": result.get("reliability_interpretation")}

    @tool
    def parts_bom() -> dict:
        """Spare parts / BOM completeness for this asset: which components its PM task list links vs the
        components like equipment carry, and any missing ones. Read-only evidence - a gap supports the
        ADD_COMPONENT recommendation but does NOT change the gate or label."""
        bom = result.get("bom_completeness") or {}
        return {"bom_completeness": bom.get("bom_completeness"), "coverage_pct": bom.get("coverage_pct"),
                "components_linked": bom.get("components_linked"), "components_expected": bom.get("components_expected"),
                "components_missing": bom.get("components_missing"), "interpretation": bom.get("interpretation")}

    @tool
    def reliability_drift() -> dict:
        """SAP-transactional drift / anomaly EVIDENCE for this asset: failure-interval drift + trend,
        MTTR drift (fail-closed on Oxy's all-zero Breakdown_Duration), reactive-work-mix level + trend,
        and a cohort bad-actor outlier. Read-only evidence - each signal reports an arithmetic statistic
        and a CANDIDATE recommendation type, but it does NOT change the gate or label, and every
        actionability threshold is BU-defined/unset."""
        drift = result.get("reliability_drift") or {}
        return {"any_drift_flag": drift.get("any_drift_flag"), "flagged_signals": drift.get("flagged_signals"),
                "signals": drift.get("signals"), "interpretation": drift.get("interpretation")}

    @tool
    def cost_distribution() -> dict:
        """Maintenance-cost distribution EVIDENCE for this asset: own P10/P50/P90 bands + any cohort-cost
        outlier, on material/services cost only (Oxy labor actuals are ~0, so NO labor-cost or savings
        claim is made). Read-only evidence; whether a P90 exceedance is actionable is BU-defined/unset."""
        cost = result.get("cost_distribution") or {}
        return {"computable": cost.get("computable"), "cost_p10": cost.get("cost_p10"),
                "cost_p50": cost.get("cost_p50"), "cost_p90": cost.get("cost_p90"),
                "cohort_cost_outlier": cost.get("cohort_cost_outlier"), "cost_basis": cost.get("cost_basis"),
                "savings_claim_allowed": cost.get("savings_claim_allowed"), "interpretation": cost.get("interpretation")}

    @tool
    def portfolio_health() -> dict:
        """Fleet-level PM health across the scoped population: gate-status distribution, blocked count,
        and the top triage rows. Read-only; counts only, no realized-savings implied."""
        ph = agent.portfolio_health()
        return {
            "by_gate_status": ph["metrics"]["by_gate_status"],
            "blocked_count": ph["metrics"].get("blocked_count"),
            "triage_top": ph["triage"]["queue"][:5],
        }

    return [governed_decision, evidence, like_equipment_comparison, execution_readiness, reliability,
            parts_bom, reliability_drift, cost_distribution, portfolio_health]


def make_gate_preview_tool(agent, asset: Dict[str, Any]):
    """An ADVISORY, READ-ONLY gate-preview tool for the free-flow GATE_CHECK branch. It runs the REAL
    deterministic oxy_gate_check on a HYPOTHETICAL change for this asset and returns the verdict, clearly
    marked advisory. It does NOT produce the authoritative governed decision, draft a package, or record
    an approval - a governed review is still required to make any change official."""
    from langchain_core.tools import tool  # lazy

    from .tools import oxy_gate_check, resolve_context, validate_scope

    profile = agent.bu_profile
    crit = asset["master_data"]["criticality"]
    pm_gov = asset["pm_governance"]

    @tool
    def preview_gate_check(change_type: str, direction: str = "") -> dict:
        """ADVISORY preview: would a hypothetical change clear the Oxy governance gate for this asset? Runs
        the real deterministic oxy_gate_check READ-ONLY. Args: change_type (e.g. PM_FREQUENCY_CHANGE,
        RETIRE_PM, MOVE_TO_RTF, TASK_LIST_CLEANUP, ADD_CBM, ADD_COMPONENT), direction (EXTEND / SHORTEN / '').
        This is NOT the authoritative decision and drafts nothing - a governed review is still required."""
        ctx = resolve_context(
            equipment_id=asset["equipment_id"], functional_location_id=asset["functional_location_id"],
            plant=asset["plant"], business_unit=asset["business_unit"], bu_profile_id=profile["profile_id"],
            asset_class=asset["asset_class"], time_window="LAST_24_MONTHS",
            pm_strategy_type=asset["current_strategy"]["strategy_type"], pm_id=asset["pm_id"])["data"]["context"]
        scope = validate_scope(ctx, profile, asset["master_data"])["data"]
        proposed = {"type": change_type, "direction": (direction or None)}
        env = oxy_gate_check(ctx, scope, profile, crit, pm_gov, proposed, asset["readiness"],
                             asset["risk"], asset["approval"], asset["approval_state"], asset["requested_action"])
        g = env["data"]
        return {
            "advisory": True,
            "hypothetical_change": {"type": change_type, "direction": direction or None},
            "gate_status": g.get("gate_status"),
            "reason": env.get("blocked_reason") or g.get("review_trigger"),
            "required_approvers": g.get("required_approvers", []),
            "note": ("ADVISORY preview only - NOT the governed decision. It drafts nothing and approves "
                     "nothing; a governed review is required to make any change official."),
        }

    return preview_gate_check
