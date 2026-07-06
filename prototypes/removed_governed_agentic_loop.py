"""ARCHIVE - NOT IMPORTED. Removed 2026-07-06 during the narration-gate refactor.

This file preserves (never hard-delete; this is not a git repo) the code that was removed when the
GOVERNED lane stopped using an LLM tool-calling loop:

- run_agentic_answer + NARRATION_AGENT_SYSTEM: the optional read-only tool-calling loop that narrated
  the already-governed result. It never changed a decision, only added a tool-DAG + narration, and it
  was the only producer of orchestration_mode == "llm_orchestrated". Governed narration is now a single
  question-aware LLM call routed through MaxAgent._narrate_guarded (check -> one corrective re-prompt ->
  deterministic template), so the mode is only ever "deterministic_only" or "llm_narrated".
- make_orchestration_tools + enforce_mandatory + _MANDATORY: the FULL analysis+decision tool registry
  (it included the DECIDE tools classify_effectiveness / run_oxy_gate / recommend_change). Free-flow no
  longer uses this - it uses the READ-ONLY make_agent_tools (agent_tools.py) so it never re-runs
  oxy_gate_check (the stated invariant). enforce_mandatory was the fence for the old compute loop and
  had no remaining live caller.

These are kept verbatim for reference only. The relative imports below are NOT valid from prototypes/;
do not import this module.
"""

# ======================================================================================================
# from max_agent/agent_loop.py
# ======================================================================================================

NARRATION_AGENT_SYSTEM = """You are MAX, a governed preventive-maintenance copilot for Oxy. The governed
DECISION for this asset is ALREADY made (computed deterministically). Your job is to EXPLAIN it, not to
re-decide it.

CALL the READ-ONLY tools to ground your answer in the real values: governed_decision (the authoritative
gate / effectiveness label / recommendation - cite it, NEVER contradict or restate a different one),
evidence, like_equipment_comparison, execution_readiness, reliability, parts_bom, portfolio_health. Read
the few you need, then answer.

HARD RULES:
- The gate status, label, and recommendation come ONLY from governed_decision. Never state a different
  one. Never invent an Oxy value (threshold, MOC %, approver, cost, savings) - if it is not in a tool
  result, say it is not available.
- Cite the specific numbers you read (work-order counts, failure-coding %, MTBF, reliability shape). When
  present, state the RELIABILITY read prominently (it is evidence, it does not move the label/gate).
- When the data is not enough to conclude, say so plainly and list the SPECIFIC SAP data still needed.
- Use plain language, not raw ALL_CAPS codes. Wave 1 is draft-only: MAX never writes SAP.
- Answer as short bulleted findings under Overview / What the data shows / Recommendation. No emoji."""


def run_agentic_answer(agent, result, question, thread_id="default", on_step=None):
    """Narrate the ALREADY-governed `result` via a READ-ONLY tool-calling loop. (ARCHIVED)"""
    from .agent_loop import free_flow_tools_available  # was agentic_available
    if not free_flow_tools_available(agent.client) or not result.get("equipment_id"):
        return None
    try:
        import json

        from databricks_langchain import ChatDatabricks
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        from .agent_tools import make_agent_tools

        tools = make_agent_tools(agent, result)
        tool_map = {t.name: t for t in tools}
        llm = ChatDatabricks(endpoint=agent.client.llm_endpoint, max_tokens=800).bind_tools(tools)

        ev_lines = (result.get("evidence_digest") or {}).get("lines") or []
        ev_block = "\n".join(f"- {l}" for l in ev_lines)
        needs = result.get("data_needs") or []
        needs_block = "\n".join(f"- {n['need']} (SAP: {n['sap_source']})" for n in needs)
        from .labels import gate_label, rec_label
        rec = result.get("recommendation_type")
        facts = ""
        if rec:
            facts += (f"\n\nRECOMMENDATION (use this PLAIN label, never the code): MAX recommends "
                      f"'{rec_label(rec)}' - gate '{gate_label(result.get('recommendation_gate_status'))}'.")
        if ev_block:
            facts += f"\n\nEVIDENCE ALREADY RETRIEVED (cite these exact numbers; do not invent others):\n{ev_block}"
        if needs_block:
            facts += f"\n\nDATA STILL NEEDED before MAX can score effectiveness (state these, do not invent others):\n{needs_block}"
        rel = result.get("reliability_interpretation")
        if rel:
            facts += ("\n\nRELIABILITY READ (evidence - state it prominently; it does NOT change the label or "
                      f"gate, and the judgment thresholds are BU-defined/unset):\n{rel}")
        bom = result.get("bom_interpretation")
        if bom:
            facts += ("\n\nSPARE-PARTS / BOM COMPLETENESS (evidence; a missing-component gap supports the "
                      f"ADD_COMPONENT recommendation, but does NOT change the label or gate):\n{bom}")

        messages = [
            SystemMessage(content=NARRATION_AGENT_SYSTEM),
            HumanMessage(content=(
                f"Asset {result.get('equipment_id')} ({result.get('asset_class')}), plant "
                f"{result.get('plant')}, criticality {result.get('criticality_code')}. Question: {question}"
                f"{facts}")),
        ]
        narration, plan = "", []
        for _ in range(8):
            if on_step:
                on_step("thinking")
            resp = llm.invoke(messages)
            messages.append(resp)
            tcs = getattr(resp, "tool_calls", None) or []
            if not tcs:
                if on_step:
                    on_step("synthesizing")
                narration = resp.content if isinstance(resp.content, str) else narration
                break
            for tc in tcs:
                name = tc.get("name")
                plan.append(name)
                if on_step:
                    on_step(name)
                fn = tool_map.get(name)
                out = fn.invoke(tc.get("args", {}) or {}) if fn else {"error": f"unknown tool {name}"}
                messages.append(ToolMessage(content=json.dumps(out, default=str), tool_call_id=tc.get("id")))
        return {"narration": (narration or "").strip(), "plan": plan, "mode": "llm_orchestrated"}
    except Exception:
        return None


# ======================================================================================================
# from max_agent/agent_tools.py
# ======================================================================================================

_MANDATORY = ("lock_scope", "classify_effectiveness", "run_oxy_gate")


def make_orchestration_tools(agent, asset, state):
    """Real deterministic tools exposed for AI tool-calling (FULL registry, incl. DECIDE tools). ARCHIVED.

    Removed from free-flow because it contained run_oxy_gate / classify_effectiveness / recommend_change,
    which would let free-flow re-run the gate - violating "FREE_FLOW never re-runs oxy_gate_check". See
    the live max_agent/agent_tools.py make_agent_tools (read-only) for what free-flow uses now.
    """
    from langchain_core.tools import tool

    from .tools import (
        resolve_context, validate_scope, genie_query_scoped, run_scoped_sql,
        pm_effectiveness_classifier, data_readiness_gate, risk_business_justification,
        recommend_strategy_change, oxy_gate_check, like_equipment_matcher, pm_comparison_engine,
        task_list_bom_readiness, cbm_measurement_readiness, pm_bom_completeness,
    )
    from .sql_templates import local_synthetic_executor

    profile = agent.bu_profile
    crit = asset["master_data"]["criticality"]
    pm_gov = asset["pm_governance"]
    tw = state.get("time_window", "LAST_24_MONTHS")

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
        """Retrieve SCOPED evidence for this asset (work orders, cost, findings)."""
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
        """Run the deterministic PM-effectiveness classifier."""
        c = _clf()
        return {"label": c["label"], "thresholds_status": c.get("thresholds_status"), "protected": c.get("protected")}

    @tool
    def check_data_readiness() -> dict:
        """Run the deterministic per-domain data-readiness gate."""
        rd = data_readiness_gate("PM_EFFECTIVENESS_CLASSIFICATION", asset["data_domain_status"], crit, _scope().get("provenance", "SYNTHETIC"))["data"]
        return {"data_readiness": rd.get("data_readiness"), "action": rd.get("action"), "missing_domains": rd.get("missing_domains")}

    @tool
    def recommend_change() -> dict:
        """Form MAX's deterministic recommendation."""
        return dict(_rec())

    @tool
    def run_oxy_gate() -> dict:
        """Run the deterministic Oxy governance gate on MAX's recommendation."""
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
        """Fleet-level PM health: gate-status distribution + top triage rows."""
        ph = agent.portfolio_health()
        return {"by_gate_status": ph["metrics"]["by_gate_status"], "triage_top": ph["triage"]["queue"][:5]}

    @tool
    def reliability() -> dict:
        """Reliability EVIDENCE from the asset's failure history."""
        from .tools import failure_mode_summary, reliability_metrics, weibull_reliability
        events = asset.get("failure_events") or []
        window = {"LAST_12_MONTHS": 365, "LAST_24_MONTHS": 730, "LAST_36_MONTHS": 1095}.get(tw, 730)
        return {"metrics": reliability_metrics(events, window)["data"],
                "weibull": weibull_reliability(events, window)["data"],
                "failure_modes": failure_mode_summary(events)["data"]}

    @tool
    def bom_completeness() -> dict:
        """Parts / BOM-completeness EVIDENCE."""
        this_bom = [{"component_code": c.get("component_code"), "on_pm_task_list": c.get("on_pm_task_list")}
                    for c in (asset.get("bom") or [])]
        cohort = like_equipment_matcher(asset, list(agent._fleet_index.values()))["data"]["cohort"]
        cohort_boms = [{"equipment_id": c["equipment_id"],
                        "linked": [b["component_code"] for b in (agent._fleet_index[c["equipment_id"]].get("bom") or [])
                                   if b.get("on_pm_task_list")]}
                       for c in cohort]
        return pm_bom_completeness(this_bom, cohort_boms, asset_class=asset.get("asset_class"))["data"]

    return [lock_scope, retrieve_evidence, classify_effectiveness, check_data_readiness,
            recommend_change, run_oxy_gate, execution_readiness, compare_like_equipment,
            reliability, bom_completeness, portfolio_health]


def enforce_mandatory(agent, asset, state):
    """The FENCE for the old compute loop: guarantee scope -> classifier -> gate ran. ARCHIVED."""
    tools = {t.name: t for t in make_orchestration_tools(agent, asset, state)}
    for name in _MANDATORY:
        if name == "lock_scope" and "scope" not in state:
            tools["lock_scope"].invoke({})
        elif name == "classify_effectiveness" and "classifier" not in state:
            tools["classify_effectiveness"].invoke({})
        elif name == "run_oxy_gate" and "gate" not in state:
            tools["run_oxy_gate"].invoke({})
    return {"scope": state.get("scope"), "classifier": state.get("classifier"), "gate": state.get("gate")}
