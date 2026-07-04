"""LangChain tool wrappers for the MAX Agent conversational orchestration layer.

These are READ-ONLY tools the LLM planner (agent_loop) may call to answer a user's question about an
asset whose governance decision has ALREADY been computed deterministically. `governed_decision`
returns that authoritative result; the planner must cite it and never contradict it. No tool here
decides a gate, a label, or writes anything - the governance fence the finance agent lacks.

Built as a factory that closes over the locked run context (mirrors the finance agent's make_*_tools
pattern). langchain_core is imported lazily so this package stays importable, and the app runs in
deterministic-only mode, when the agentic stack is not installed.
"""

from __future__ import annotations

from typing import Any, Dict, List


def make_agent_tools(agent, result: Dict[str, Any]) -> List[Any]:
    """Return the read-only LangChain tools for one governed run. Requires langchain_core (lazy)."""
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
        env = genie_query_scoped(
            question,
            {"equipment_id": eid, "time_window": time_window, "scope_validated": scope.get("scope_validated", True)},
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
    def portfolio_health() -> dict:
        """Fleet-level PM health across the scoped population: gate-status distribution, blocked count,
        and the top triage rows. Read-only; counts only, no realized-savings implied."""
        ph = agent.portfolio_health()
        return {
            "by_gate_status": ph["metrics"]["by_gate_status"],
            "blocked_count": ph["metrics"].get("blocked_count"),
            "triage_top": ph["triage"]["queue"][:5],
        }

    return [governed_decision, evidence, like_equipment_comparison, execution_readiness, portfolio_health]


# ---------------------------------------------------------------------------
# Orchestration tools: the AI SELECTS and SEQUENCES these; each one CALLS a real deterministic tool
# (parameterized by the locked asset) and stores its output in a shared run-state. Dependencies
# auto-resolve (gate needs a recommendation needs a classification needs scope), so the AI can call
# them in any order. The tools compute the deterministic outputs; the AI never fabricates them.
# ---------------------------------------------------------------------------
_MANDATORY = ("lock_scope", "classify_effectiveness", "run_oxy_gate")


def make_orchestration_tools(agent, asset: Dict[str, Any], state: Dict[str, Any]) -> List[Any]:
    """Real deterministic tools exposed for AI tool-calling. `state` is shared across the run."""
    from langchain_core.tools import tool  # lazy

    from .tools import (
        resolve_context, validate_scope, genie_query_scoped, run_scoped_sql,
        pm_effectiveness_classifier, data_readiness_gate, risk_business_justification,
        recommend_strategy_change, oxy_gate_check, like_equipment_matcher, pm_comparison_engine,
        task_list_bom_readiness, cbm_measurement_readiness,
    )
    from .sql_templates import local_synthetic_executor

    profile = agent.bu_profile
    crit = asset["master_data"]["criticality"]
    pm_gov = asset["pm_governance"]
    tw = state.get("time_window", "LAST_24_MONTHS")

    # --- plain dependency resolvers (deterministic; not exposed as tools) ---
    def _ctx():
        if "context" not in state:
            env = resolve_context(
                equipment_id=asset["equipment_id"], functional_location_id=asset["functional_location_id"],
                plant=asset["plant"], business_unit=asset["business_unit"], bu_profile_id=profile["profile_id"],
                asset_class=asset["asset_class"], time_window=tw,
                pm_strategy_type=asset["current_strategy"]["strategy_type"], pm_id=asset["pm_id"])
            state["context"] = env["data"]["context"]
        return state["context"]

    def _scope():
        if "scope" not in state:
            state["scope"] = validate_scope(_ctx(), profile, asset["master_data"])["data"]
        return state["scope"]

    def _clf():
        if "classifier" not in state:
            state["classifier"] = pm_effectiveness_classifier(
                _ctx(), profile, crit, pm_gov, asset["pm_attributes"],
                asset["effectiveness_signals"], asset["evidence_readiness"])["data"]
        return state["classifier"]

    def _rec():
        if "recommendation" not in state:
            state["recommendation"] = recommend_strategy_change(
                classifier_label=_clf()["label"], data_readiness=asset["readiness"]["data_readiness"],
                risk=asset["risk"], comparison=asset.get("comparison", {}), criticality=crit,
                pm_governance=pm_gov, readiness=asset["readiness"], bu_profile=profile)["data"]["recommendation"]
        return state["recommendation"]

    def _gate():
        if "gate" not in state:
            rec = _rec()
            env = oxy_gate_check(_ctx(), _scope(), profile, crit, pm_gov,
                                 {"type": rec.get("type"), "direction": rec.get("direction")},
                                 asset["readiness"], asset["risk"], asset["approval"],
                                 asset["approval_state"], asset["requested_action"])
            state["gate"] = env["data"]
            state["gate_reason"] = env.get("blocked_reason") or env["data"].get("review_trigger")
        return state["gate"]

    @tool
    def lock_scope() -> dict:
        """Resolve context and validate scope (operated/JV, exemptions). Run this FIRST for any asset."""
        s = _scope()
        return {"scope_validated": s.get("scope_validated"), "in_scope": s.get("in_scope"),
                "provenance": s.get("provenance"), "blocked_reason": s.get("blocked_reason")}

    @tool
    def retrieve_evidence(question: str) -> dict:
        """Retrieve SCOPED evidence for this asset (work orders, cost, findings) to answer a data
        question. Always filtered to the locked equipment; never runs unscoped."""
        sc = _scope()
        scope = {"equipment_id": asset["equipment_id"], "time_window": tw, "scope_validated": sc.get("scope_validated", True)}
        ex = agent.client.sql_executor() or local_synthetic_executor(agent._fleet_index)
        ev = {t: run_scoped_sql(t, scope, {"equipment_id": asset["equipment_id"], "time_window": tw}, executor=ex)["data"].get("records", [])
              for t in ("work_order_history", "cost_summary", "notification_findings")}
        genie = genie_query_scoped(question, scope, client=agent.client)["data"]
        state["evidence"] = ev
        return {"work_order_history": ev["work_order_history"], "cost_summary": ev["cost_summary"],
                "notification_findings": ev["notification_findings"], "genie_bound": genie.get("genie_bound")}

    @tool
    def classify_effectiveness() -> dict:
        """Run the deterministic PM-effectiveness classifier (describe-and-flag under null thresholds)."""
        c = _clf()
        return {"label": c["label"], "thresholds_status": c.get("thresholds_status"), "protected": c.get("protected")}

    @tool
    def check_data_readiness() -> dict:
        """Run the deterministic per-domain data-readiness gate."""
        rd = data_readiness_gate("PM_EFFECTIVENESS_CLASSIFICATION", asset["data_domain_status"], crit, _scope().get("provenance", "SYNTHETIC"))["data"]
        return {"data_readiness": rd.get("data_readiness"), "action": rd.get("action"), "missing_domains": rd.get("missing_domains")}

    @tool
    def recommend_change() -> dict:
        """Form MAX's deterministic recommendation from classifier + readiness + risk. It never
        recommends a reduce/retire on a mandatory PM; keep-coverage improvements route to review."""
        return dict(_rec())

    @tool
    def run_oxy_gate() -> dict:
        """Run the deterministic Oxy governance gate on MAX's recommendation. This is the AUTHORITATIVE
        gate result (PASS / REVIEW_REQUIRED / BLOCKED / DRAFT_ONLY); do not infer it yourself."""
        g = _gate()
        return {"gate_status": g.get("gate_status"), "reason": state.get("gate_reason"),
                "required_approvers": g.get("required_approvers", [])}

    @tool
    def execution_readiness() -> dict:
        """Check execution readiness (task list / object dependency; CBM fails closed without readings)."""
        r = asset["readiness"]
        tl = task_list_bom_readiness(r, crit, profile)["data"]
        cbm = cbm_measurement_readiness(r)["data"]
        return {"task_list_readiness": tl.get("task_list_readiness"), "cbm_readiness": cbm.get("cbm_readiness")}

    @tool
    def compare_like_equipment() -> dict:
        """Compare this asset's PM to like equipment (same class) for standardization candidates."""
        fleet = list(agent._fleet_index.values())
        cohort = like_equipment_matcher(asset, fleet)["data"]["cohort"]
        cohort_assets = [agent._fleet_index[c["equipment_id"]] for c in cohort]
        cmp = pm_comparison_engine(asset, cohort_assets)["data"]
        return {"cohort": cohort, "standardization_candidates": cmp.get("standardization_candidates", [])}

    @tool
    def portfolio_health() -> dict:
        """Fleet-level PM health: gate-status distribution + top triage rows. Counts only, no savings."""
        ph = agent.portfolio_health()
        return {"by_gate_status": ph["metrics"]["by_gate_status"], "triage_top": ph["triage"]["queue"][:5]}

    return [lock_scope, retrieve_evidence, classify_effectiveness, check_data_readiness,
            recommend_change, run_oxy_gate, execution_readiness, compare_like_equipment, portfolio_health]


def enforce_mandatory(agent, asset: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """The FENCE: guarantee scope -> classifier -> gate ran (run them if the AI skipped them) and
    return their authoritative deterministic outputs. Called after the AI's tool-calling turn so the
    governed decision is deterministic no matter what the AI did or narrated."""
    tools = {t.name: t for t in make_orchestration_tools(agent, asset, state)}
    for name in _MANDATORY:
        if name == "lock_scope" and "scope" not in state:
            tools["lock_scope"].invoke({})
        elif name == "classify_effectiveness" and "classifier" not in state:
            tools["classify_effectiveness"].invoke({})
        elif name == "run_oxy_gate" and "gate" not in state:
            tools["run_oxy_gate"].invoke({})
    return {"scope": state.get("scope"), "classifier": state.get("classifier"), "gate": state.get("gate")}
