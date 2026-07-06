"""MAX Agent orchestrator.

One MAX Agent that selects and sequences the deterministic tool library for a single asset (the
Wave-A path from 04): resolve context -> validate scope -> retrieve evidence -> classify ->
data-readiness -> recommend -> gate -> draft package -> approval state. Safety decisions are
deterministic; the LLM only narrates. Every tool call is recorded in a Tool Trace.

The orchestrator reads the same record shape whether it comes from the synthetic fleet or (later)
governed Databricks views, so real-data cutover changes only the data source, not this pipeline.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .config import load_bu_profile
from .databricks_client import MaxDatabricksClient
from .evidence import build_evidence_digest, data_needs
from .prompts import NARRATION_SYSTEM, deterministic_summary, narration_prompt
from .sql_templates import local_synthetic_executor
from .synthetic_data import fleet_index, synthetic_fleet
from .tools import (
    approval_workflow_state,
    cbm_measurement_readiness,
    contractor_service_readiness,
    data_readiness_gate,
    draft_sap_change_package,
    failure_mode_summary,
    genie_query_scoped,
    like_equipment_matcher,
    materials_component_readiness,
    oxy_gate_check,
    pm_bom_completeness,
    reliability_metrics,
    planned_hours_calibration,
    pm_comparison_engine,
    pm_effectiveness_classifier,
    pm_health_dashboard_metrics,
    pm_portfolio_triage,
    procurement_readiness,
    reactive_share,
    recommend_strategy_change,
    reliability_drift_monitor,
    resolve_context,
    risk_business_justification,
    run_scoped_sql,
    sap_cost_distribution,
    task_list_bom_readiness,
    trial_monitor,
    validate_scope,
    value_kpi_tracker,
    weibull_reliability,
)

# Row cap for the Level-2 detail retrieval (individual work orders / notifications).
_DETAIL_ROW_CAP = 50

# Proposed-recommendation type -> data_readiness_gate domain-map key (informational readiness view).
_READINESS_TYPE = {
    "PM_FREQUENCY_CHANGE": "PM_FREQUENCY_CHANGE",
    "TASK_LIST_CLEANUP": "TASK_LIST_CLEANUP",
    "ADD_COMPONENT": "ADD_COMPONENT",
    "ADD_CBM": "ADD_CBM",
    "CBM_CONVERSION": "CBM_CONVERSION",
}


def _trace_entry(env: Dict[str, Any], keep: Optional[List[str]] = None) -> Dict[str, Any]:
    data = env.get("data", {}) if isinstance(env, dict) else {}
    kept = {k: data.get(k) for k in (keep or [])}
    return {
        "tool": env.get("tool"),
        "status": env.get("status"),
        "summary": env.get("summary"),
        "blocked_reason": env.get("blocked_reason"),
        "confidence": env.get("confidence"),
        "params_used": env.get("params_used", {}),
        "data": kept,
    }


# Language that AFFIRMS the REVIEWED CHANGE is approved / safe to DO (not merely explaining a non-PASS
# gate or routing to a review). Anchored to an ACTION verb so it does NOT false-positive on definitions
# ("cleared to draft means...") or legitimate routing ("proceed with a governance review"). A false
# positive costs only one corrective round-trip (and usually still yields a corrected model answer); a
# false negative is a safety miss, so the strong, unambiguous approvals are always caught.
_AFFIRM_ACTION = (r"(?:reduc\w*|retir\w*|extend\w*|shorten\w*|remov\w*|drop\w*|implement\w*|"
                  r"make (?:the|this) change|apply (?:the|this) change|reduce coverage|"
                  r"proceed with (?:the|this) (?:change|reduction|retirement))")
_AFFIRM_LEAD_RE = re.compile(
    r"\b(?:safe to|ok(?:ay)? to|free to|good to|cleared to|approved to|you (?:can|may)|go ahead and)\s+"
    + _AFFIRM_ACTION)
_AFFIRM_STRONG = (
    "go ahead", "green light", "green-light", "no approval needed", "you are cleared",
    "the change is approved", "this change is approved", "change has been approved",
    "cleared for implementation", "approved and ready to",
)


def _narration_affirms_blocked_change(text: str, gate_status: Optional[str] = None) -> bool:
    """True only when the text AFFIRMS the reviewed change is approved / safe to DO - not when it merely
    explains a non-PASS gate or routes to a review. Conservative and ACTION-anchored so it does not fire
    on definitions. (Renamed from _narration_contradicts_gate: this is about the change under review, not
    the oxy_gate_check tool.)"""
    t = " ".join((text or "").lower().split())
    if not t:
        return False
    if _AFFIRM_LEAD_RE.search(t):
        return True
    return any(p in t for p in _AFFIRM_STRONG)


class MaxAgent:
    def __init__(self, bu_profile: Optional[Dict[str, Any]] = None, client: Optional[MaxDatabricksClient] = None) -> None:
        self.bu_profile = bu_profile or load_bu_profile("default_oxy")
        self.client = client or MaxDatabricksClient()
        self._fleet_index = fleet_index()

    # --- single-asset run --------------------------------------------------
    def run(self, equipment_id: str, actor: Optional[Dict[str, Any]] = None,
            time_window: str = "LAST_24_MONTHS", review_type: Optional[str] = None,
            question: Optional[str] = None, thread_id: str = "default", on_step=None) -> Dict[str, Any]:
        asset = self._fleet_index.get(equipment_id)
        if asset is None:
            return {"error": f"Unknown asset: {equipment_id}", "known_assets": list(self._fleet_index)}
        # Dropdown browsing stays fast and deterministic; the LLM narration happens only when the user
        # asks a question (clicks Ask), so selecting assets never waits on an LLM call.
        result = self._run_asset(asset, actor=actor, time_window=time_window, review_type=review_type,
                                 narrate=False, on_step=on_step)
        result["orchestration_mode"] = "deterministic_only"
        if question:
            result["user_question"] = question
            # One question-aware LLM narration, routed through the shared narration gate (which may run a
            # corrective re-prompt and, as a last resort, the deterministic template). Mode reflects who
            # produced the final text: "llm_narrated" or "deterministic_only". No LLM tool-loop here.
            if on_step:
                on_step("synthesizing")
            text, producer = self._summary(result)
            result["chat_summary"] = text
            result["orchestration_mode"] = "llm_narrated" if producer == "llm" else "deterministic_only"
        return result

    def answer(self, text: str, actor: Optional[Dict[str, Any]] = None,
               time_window: str = "LAST_24_MONTHS", review_type: Optional[str] = None,
               thread_id: str = "default") -> Dict[str, Any]:
        """Free-text chat entry: resolve the asked-about asset deterministically, then run the pipeline."""
        from .intent import resolve_asset_from_text
        resolved = resolve_asset_from_text(text, self._fleet_index)
        eid = resolved.get("equipment_id")
        if not eid:
            return {"error": "Could not resolve an in-scope asset from that question.",
                    "resolved_from_text": resolved, "user_question": text,
                    "known_assets": list(self._fleet_index)}
        result = self.run(eid, actor=actor, time_window=time_window, review_type=review_type,
                          question=text, thread_id=thread_id)
        result["resolved_from_text"] = resolved
        result["user_question"] = text or result.get("user_question")
        return result

    def extract_entities(self, question: str) -> Dict[str, Any]:
        """Entity extraction for the chat (Finance-style): the model proposes typed entities that scope
        the run; the deterministic resolver + fleet membership are the fail-closed floor. Degrades to
        the deterministic resolver when no LLM is bound. See entities.py."""
        from .entities import extract_entities
        return extract_entities(self.client, question, self._fleet_index)

    def preview_narrative(self, result: Dict[str, Any], concise: bool = False) -> str:
        """A short, governed MAX-written assessment paragraph for the PM preview panel (LLM when bound,
        deterministic paragraph otherwise). Explains why the PM is in this state and whether it warrants
        a deeper look - it only explains the deterministic result, it never invents a value or a gate.
        concise=True is the compact triage version for the Command Center / Ask preview panel; the full
        version stays in the Work Strategy Studio."""
        if not result or result.get("error"):
            return ""
        from .prompts import PREVIEW_SYSTEM, _fix_preamble, preview_narration_prompt, preview_summary
        # Route the preview narration through the SAME shared narration gate as governed / free-flow
        # narration: the preview panel shows gate + recommendation language, so it must never affirm a
        # non-PASS change. Affirming first draft -> ONE corrective re-prompt -> deterministic preview_summary.
        gate = result.get("gate_status")
        first = self.client.llm_complete(preview_narration_prompt(result, concise=concise), PREVIEW_SYSTEM)
        text, _ = self._narrate_guarded(
            first, gate,
            regenerate=lambda: self.client.llm_complete(
                _fix_preamble(gate, first) + "\n\n" + preview_narration_prompt(result, concise=concise),
                PREVIEW_SYSTEM),
            fallback=lambda: preview_summary(result, concise=concise))
        return text

    def classify_intent(self, question: str, messages: Optional[List[Dict[str, Any]]] = None,
                        has_last_result: bool = False) -> str:
        """Route a chat turn: GOVERNED (needs a governed decision -> run the pipeline) or FREE_FLOW
        (follow-up / definition / greeting -> answer conversationally). LLM when bound, deterministic
        keyword floor otherwise. Fail-safe: anything not clearly FREE_FLOW is GOVERNED, so a real
        analysis question can never skip the governance DAG."""
        from .prompts import INTENT_SYSTEM, deterministic_intent, intent_prompt
        if not self.client.llm_bound():
            return deterministic_intent(question, has_last_result)
        raw = self.client.llm_complete(intent_prompt(question, messages or [], has_last_result), INTENT_SYSTEM)
        # Exact/prefix match, not a loose substring: anything ambiguous (e.g. "GOVERNED, not FREE_FLOW")
        # falls to GOVERNED, the safe direction.
        r = (raw or "").strip().upper()
        return "FREE_FLOW" if r.startswith("FREE_FLOW") else "GOVERNED"

    def classify_free_flow_intent(self, question: str, messages: Optional[List[Dict[str, Any]]] = None,
                                  has_last_result: bool = False) -> str:
        """Sub-route a FREE_FLOW turn: INFO (explain / look up), GATE_CHECK (advisory 'is X allowed / would
        it pass?'), or APPROVAL (approve / reject the recommendation just discussed). LLM when bound,
        deterministic keyword floor otherwise. Fail-safe: unclear -> INFO (the read-only, action-free
        branch); with no prior governed result there is nothing to gate-check or approve -> INFO."""
        from .prompts import (FREE_FLOW_INTENT_SYSTEM, classify_free_flow_intent_deterministic,
                              free_flow_intent_prompt)
        if not has_last_result:
            return "INFO"
        if not self.client.llm_bound():
            return classify_free_flow_intent_deterministic(question, has_last_result)
        raw = (self.client.llm_complete(free_flow_intent_prompt(question, messages or []),
                                        FREE_FLOW_INTENT_SYSTEM) or "").strip().upper()
        if raw.startswith("APPROVAL"):
            return "APPROVAL"
        if raw.startswith("GATE_CHECK"):
            return "GATE_CHECK"
        return "INFO"

    def free_flow_answer(self, question: str, messages: Optional[List[Dict[str, Any]]] = None,
                         last_result: Optional[Dict[str, Any]] = None, intent: Optional[str] = None,
                         on_step=None) -> str:
        """The FREE_FLOW answer, sub-routed by intent (classified here if not passed in):

        - INFO: the read-only tool loop / single conversational call (read the decision + fetch evidence).
        - GATE_CHECK: an ADVISORY, READ-ONLY gate preview - it may call preview_gate_check to run the real
          deterministic gate on a HYPOTHETICAL change and reports the verdict, clearly as a preview (never
          the authoritative decision; drafts nothing; a governed review is still required).
        - APPROVAL: a short lead-in only (the caller renders the inline approve/reject buttons; the human
          clicks and approval_workflow_state decides - the LLM never approves).

        Every text answer passes through the shared narration gate, so it can never affirm a non-PASS
        change. Falls back to a single call, then a deterministic answer, when the stack / LLM is absent."""
        from .prompts import (FREE_FLOW_SYSTEM, GATE_CHECK_SYSTEM, _fix_preamble, advisory_gate_answer,
                              approval_leadin, deterministic_free_flow, free_flow_prompt, gate_check_prompt)
        gate = (last_result or {}).get("gate_status")
        if intent is None:
            intent = self.classify_free_flow_intent(question, messages, has_last_result=bool(last_result))

        # APPROVAL: MAX only SURFACES the action; the caller renders the buttons, the human commits.
        if intent == "APPROVAL" and last_result and not last_result.get("error"):
            return approval_leadin(last_result)

        # GATE_CHECK: advisory, READ-ONLY gate preview, through the narration gate.
        if intent == "GATE_CHECK" and last_result:
            ans = None
            try:
                from .agent_loop import run_free_flow_agent
                from .agent_tools import make_gate_preview_tool
                asset = self._fleet_index.get(last_result.get("equipment_id"))
                extra = [make_gate_preview_tool(self, asset)] if asset else None
                ans = run_free_flow_agent(self, question, messages or [], last_result,
                                          extra_tools=extra, system=GATE_CHECK_SYSTEM, on_step=on_step)
            except Exception:
                ans = None
            if not ans:
                if not self.client.llm_bound():
                    return advisory_gate_answer(question, last_result)
                ans = self.client.llm_complete(gate_check_prompt(question, messages or [], last_result),
                                               GATE_CHECK_SYSTEM)
            # An advisory gate answer must NEVER contain approving language for ANY hypothetical (PASS or
            # not) - so FORCE the narration gate's affirm-check on this branch. The hypothetical being
            # previewed may be non-PASS even when the last governed result was PASS, so a PASS last_result
            # must not make the check lenient.
            check_gate = gate if (gate and gate != "PASS") else "REVIEW_REQUIRED"
            if on_step:
                on_step("synthesizing")
            text, _ = self._narrate_guarded(
                ans, check_gate,
                regenerate=lambda: self.client.llm_complete(
                    _fix_preamble(check_gate, ans) + "\n\n" + gate_check_prompt(question, messages or [], last_result),
                    GATE_CHECK_SYSTEM),
                fallback=lambda: advisory_gate_answer(question, last_result))
            return text

        # INFO (default): the read-only tool loop / single call, through the narration gate.
        ans = None
        try:
            from .agent_loop import run_free_flow_agent
            ans = run_free_flow_agent(self, question, messages or [], last_result, on_step=on_step)
        except Exception:
            ans = None
        if not ans:
            if not self.client.llm_bound():
                return deterministic_free_flow(question, last_result)
            ans = self.client.llm_complete(free_flow_prompt(question, messages or [], last_result), FREE_FLOW_SYSTEM)
        if on_step:
            on_step("synthesizing")
        text, _ = self._narrate_guarded(
            ans, gate,
            regenerate=lambda: self.client.llm_complete(
                _fix_preamble(gate, ans) + "\n\n" + free_flow_prompt(question, messages or [], last_result),
                FREE_FLOW_SYSTEM),
            fallback=lambda: deterministic_free_flow(question, last_result))
        return text

    def _narrate_guarded(self, text, gate_status, regenerate, fallback):
        """The ONE shared narration gate for GOVERNED narration and FREE_FLOW. Returns (final_text,
        producer) where producer is 'llm' or 'deterministic'.

        - empty answer                                  -> deterministic template (circuit breaker)
        - gate is PASS / absent, or the answer is clean -> the model's answer
        - answer affirms a non-PASS change              -> ONE corrective re-prompt, then re-check
        - still affirms                                 -> deterministic template (circuit breaker)

        The model may EXPLAIN a gate; it may never AFFIRM a non-PASS one - whichever path wrote the
        sentence. When the model and the deterministic layer disagree, the deterministic layer wins."""
        if not text:
            return fallback(), "deterministic"
        if not gate_status or gate_status == "PASS":
            return text, "llm"
        if not _narration_affirms_blocked_change(text, gate_status):
            return text, "llm"
        fixed = regenerate()                              # ONE targeted corrective re-prompt
        if fixed and not _narration_affirms_blocked_change(fixed, gate_status):
            return fixed, "llm"
        return fallback(), "deterministic"                # last-resort circuit breaker

    def _sql_executor(self):
        return self.client.sql_executor() or local_synthetic_executor(self._fleet_index)

    def _run_asset(self, asset: Dict[str, Any], actor: Optional[Dict[str, Any]] = None,
                   time_window: str = "LAST_24_MONTHS", review_type: Optional[str] = None,
                   narrate: bool = True, on_step=None) -> Dict[str, Any]:
        trace: List[Dict[str, Any]] = []
        profile = self.bu_profile
        # on_step is DISPLAY-ONLY (the live progress checklist); it never touches scope, decisions, the
        # gate, or narration. Each key maps to a friendly STEP_LABELS phrase. Guarded so portfolio() and
        # tests can call _run_asset with no callback.
        def _emit(key):
            if on_step:
                on_step(key)

        _emit("lock_scope")
        # 1. resolve_context
        ctx_env = resolve_context(
            equipment_id=asset["equipment_id"], functional_location_id=asset["functional_location_id"],
            plant=asset["plant"], business_unit=asset["business_unit"], bu_profile_id=profile["profile_id"],
            asset_class=asset["asset_class"], time_window=time_window,
            pm_strategy_type=asset["current_strategy"]["strategy_type"], pm_id=asset["pm_id"],
        )
        context = ctx_env["data"]["context"]
        trace.append(_trace_entry(ctx_env))

        # 2. validate_scope
        scope_env = validate_scope(context, profile, asset["master_data"])
        scope = scope_env["data"]
        trace.append(_trace_entry(scope_env, ["scope_validated", "in_scope", "provenance", "blocked_reason", "scope_flags"]))

        provenance = scope.get("provenance", "SYNTHETIC")
        criticality = asset["master_data"]["criticality"]
        pm_governance = asset["pm_governance"]

        result: Dict[str, Any] = {
            "equipment_id": asset["equipment_id"], "asset_class": asset["asset_class"], "plant": asset["plant"],
            "business_unit": asset["business_unit"], "pm_id": asset["pm_id"],
            "user_question": asset["user_question"], "provenance": provenance,
            "criticality_code": criticality.get("code"), "criticality_label": criticality.get("label"),
            "bu_profile_id": profile.get("profile_id"), "time_window": time_window,
            "review_type": review_type or "PM effectiveness and strategy review",
            "actor": actor or {"user_id": "local", "roles": []},
            "operated_status": asset["master_data"].get("operated_status"),
            "exemption_status": asset["master_data"].get("exemption_status"),
            "data_readiness_rag": asset["readiness"].get("data_readiness"),
            "scope": scope, "evidence": {}, "expected_gate_status": asset.get("expected_gate_status"),
            "databricks_mode": self.client.mode(),
        }

        proposed = dict(asset["proposed_recommendation"])
        result["proposed_summary"] = f"{asset.get('current_value')} -> {asset.get('proposed_value')}"

        # --- Scope fail-closed short-circuit ---
        if not scope.get("scope_validated") or scope.get("in_scope") is False:
            _emit("run_oxy_gate")
            gate_env = oxy_gate_check(
                context, scope, profile, criticality, pm_governance, proposed, asset["readiness"],
                asset["risk"], asset["approval"], asset["approval_state"], asset["requested_action"],
            )
            trace.append(_trace_entry(gate_env, ["gate_status", "review_trigger", "required_approvers"]))
            result.update(self._finish_gate(gate_env, proposed, asset, criticality, provenance, actor=actor))
            result["classifier_label"] = "Not classified (out of analysis scope)"
            result["recommendation_type"] = "NONE"
            result["recommendation_rationale"] = f"Asset held: {scope.get('blocked_reason')}."
            result["do_not_optimize"] = False
            result["tool_trace"] = trace
            self._attach_evidence(result)
            result["chat_summary"] = self._summary(result)[0] if narrate else deterministic_summary(result)
            return result

        # 3. run_scoped_sql (evidence). Scope is authoritative: these reads happen only after the
        # fail-closed scope check has passed, so held/JV/exempt assets do not expose scoped records.
        _emit("retrieve_evidence")
        sql_scope = {"equipment_id": asset["equipment_id"], "time_window": time_window,
                     "scope_validated": scope.get("scope_validated", True)}
        evidence = {}
        executor = self._sql_executor()
        for tmpl in ("work_order_history", "cost_summary", "notification_findings"):
            sql_env = run_scoped_sql(
                tmpl, sql_scope, {"equipment_id": asset["equipment_id"], "time_window": time_window},
                executor=executor,
            )
            evidence[tmpl] = sql_env["data"].get("records", [])
            trace.append(_trace_entry(sql_env, ["template_name", "row_count", "executor_bound"]))
        result["evidence"] = evidence

        # 4. pm_effectiveness_classifier
        _emit("classify_effectiveness")
        clf_env = pm_effectiveness_classifier(
            context, profile, criticality, pm_governance, asset["pm_attributes"],
            asset["effectiveness_signals"], asset["evidence_readiness"],
        )
        clf = clf_env["data"]
        trace.append(_trace_entry(clf_env, ["label", "protected", "protection_basis", "thresholds_status", "low_findings_guard_applied"]))

        # 5. data_readiness_gate (informational per-domain view)
        _emit("check_data_readiness")
        rd_type = _READINESS_TYPE.get(proposed.get("type"), "PM_EFFECTIVENESS_CLASSIFICATION")
        rd_env = data_readiness_gate(rd_type, asset["data_domain_status"], criticality, provenance)
        trace.append(_trace_entry(rd_env, ["data_readiness", "action", "missing_domains"]))

        # 6. risk_business_justification (honest cost view)
        rbj_env = risk_business_justification(
            cost_actuals_present=asset["evidence_readiness"].get("cost_actuals_present", False),
            material_cost_present=asset["cost"].get("material_cost", 0) > 0,
        )
        trace.append(_trace_entry(rbj_env, ["cost_view", "labor_cost_claim_allowed", "savings_claim_allowed"]))

        # 6b. Parts / BOM completeness (tool 28): read this PM's linked components (v_bom) and compare to
        # like equipment; a missing-component gap FEEDS the ADD_COMPONENT recommendation below. Evidence
        # only for the label/gate. The cohort is computed ONCE here and reused by _run_extras (no
        # double like_equipment_matcher call).
        fleet = list(self._fleet_index.values())
        lem_env = like_equipment_matcher(asset, fleet)
        trace.append(_trace_entry(lem_env, ["cohort"]))
        cohort_assets = [self._fleet_index[c["equipment_id"]] for c in lem_env["data"]["cohort"]]
        bom_scope = {"equipment_id": asset["equipment_id"], "time_window": time_window,
                     "scope_validated": scope.get("scope_validated", True)}
        target_bom = run_scoped_sql("bom_components", bom_scope,
                                    {"equipment_id": asset["equipment_id"]}, executor=executor)["data"].get("records", [])
        cohort_boms = [{"equipment_id": ca["equipment_id"],
                        "linked": [c["component_code"] for c in (ca.get("bom") or []) if c.get("on_pm_task_list")]}
                       for ca in cohort_assets]
        bom_env = pm_bom_completeness(target_bom, cohort_boms, asset_class=asset["asset_class"])
        trace.append(_trace_entry(bom_env, ["bom_completeness", "coverage_pct", "component_gap"]))
        result["bom_completeness"] = bom_env["data"]
        result["bom_interpretation"] = bom_env["data"].get("interpretation")
        # Feed the deterministic recommendation: a real BOM gap surfaces component_gap so
        # recommend_strategy_change can choose ADD_COMPONENT (a keep-coverage improvement, still gated).
        readiness_for_rec = dict(asset["readiness"])
        if bom_env["data"].get("component_gap"):
            readiness_for_rec["component_gap"] = True

        # 7. recommend_strategy_change (MAX's own recommendation)
        _emit("recommend_change")
        rec_env = recommend_strategy_change(
            classifier_label=clf["label"], data_readiness=asset["readiness"]["data_readiness"],
            risk=asset["risk"], comparison=asset.get("comparison", {}), criticality=criticality,
            pm_governance=pm_governance, readiness=readiness_for_rec, bu_profile=profile,
        )
        rec = rec_env["data"]
        trace.append(_trace_entry(rec_env, ["recommendation", "do_not_optimize"]))

        # 8. oxy_gate_check on the change under review (the scenario's proposed change).
        _emit("run_oxy_gate")
        gate_env = oxy_gate_check(
            context, scope, profile, criticality, pm_governance, proposed, asset["readiness"],
            asset["risk"], asset["approval"], asset["approval_state"], asset["requested_action"],
        )
        trace.append(_trace_entry(gate_env, ["gate_status", "review_trigger", "required_approvers"]))

        # 8b. Also gate MAX's OWN recommendation - 70/10: "every recommendation passes to
        # oxy_gate_check." When MAX recommends something other than the change under review (e.g.
        # DATA_REMEDIATION vs a raw retain), this surfaces the recommendation's own gate outcome so
        # the UI never shows a recommendation MAX has not gate-checked.
        rec_reco = rec["recommendation"]
        rec_change = {"type": rec_reco.get("type"), "direction": rec_reco.get("direction")}
        rec_gate_env = oxy_gate_check(
            context, scope, profile, criticality, pm_governance, rec_change, asset["readiness"],
            asset["risk"], asset["approval"], asset["approval_state"], asset["requested_action"],
        )
        trace.append(_trace_entry(rec_gate_env, ["gate_status", "review_trigger"]))
        recommendation_diverges = rec_reco.get("type") != proposed.get("type")

        result.update({
            "classifier_label": clf["label"], "classifier_protected": clf.get("protected"),
            "protection_basis": clf.get("protection_basis"), "thresholds_status": clf.get("thresholds_status"),
            "classifier_confidence": clf_env.get("confidence"),
            # Promote the classifier's reasoning (today only in the tool trace) so the chat can explain WHY.
            "classifier_reason": clf.get("missing_evidence_reason") or clf.get("needs_improvement_reason"),
            "dimension_results": clf.get("dimension_results"),
            "missing_domains": rd_env["data"].get("missing_domains"),
            "data_readiness": rd_env["data"]["data_readiness"], "data_readiness_action": rd_env["data"].get("action"),
            "cost_view": rbj_env["data"]["cost_view"],
            "change_under_review_type": proposed.get("type"),
            "recommendation_type": rec_reco["type"],
            "recommendation_rationale": rec_reco["rationale"],
            "recommendation_next_action": rec_reco["next_action"],
            "recommendation_gate_status": rec_gate_env["data"].get("gate_status"),
            "recommendation_gate_reason": rec_gate_env.get("blocked_reason") or rec_gate_env["data"].get("review_trigger"),
            "recommendation_diverges": recommendation_diverges,
            "do_not_optimize": rec["do_not_optimize"],
        })
        result.update(self._finish_gate(gate_env, proposed, asset, criticality, provenance, actor=actor,
                                        rec_reco=rec_reco, rec_gate_env=rec_gate_env))
        self._run_extras(asset, context, scope, criticality, trace, result, cohort_assets, on_step=on_step)
        result["tool_trace"] = trace
        self._attach_evidence(result)
        result["chat_summary"] = self._summary(result)[0] if narrate else deterministic_summary(result)
        return result

    def _run_extras(self, asset, context, scope, criticality, trace, result, cohort_assets=None,
                    on_step=None) -> None:
        """Run the Wave B/C/D tools (retrieval, execution readiness, comparison, trial) and record them.

        `cohort_assets` is the like-equipment cohort already computed in `_run_asset` (for the BOM tool);
        it is reused here so like_equipment_matcher is not run twice. `on_step` is DISPLAY-ONLY (progress
        checklist); it never affects any decision.
        """
        profile = self.bu_profile
        r = asset["readiness"]

        def _emit(key):
            if on_step:
                on_step(key)

        # genie_query_scoped (scoped; local returns empty, never runs unscoped)
        genie_env = genie_query_scoped(
            asset["user_question"],
            {"equipment_id": asset["equipment_id"], "time_window": result.get("time_window", "LAST_24_MONTHS"),
             "scope_validated": scope.get("scope_validated", True)},
            client=self.client,
        )
        trace.append(_trace_entry(genie_env, ["genie_bound", "row_count", "referenced_relations"]))

        # Execution readiness (Wave C)
        _emit("execution_readiness")
        checks: Dict[str, Any] = {}
        for env in (
            task_list_bom_readiness(r, criticality, profile),
            materials_component_readiness(r),
            procurement_readiness(r),
            contractor_service_readiness(r),
            planned_hours_calibration(r),
            cbm_measurement_readiness(r),
        ):
            checks[env["tool"]] = env["data"]
            trace.append(_trace_entry(env, list(env.get("data", {}).keys())[:3]))
        result["readiness_checks"] = checks

        # Comparison (Wave B) - reuse the cohort computed in _run_asset (like_equipment_matcher already
        # ran and was traced there); fall back to computing it if not provided.
        _emit("compare_like_equipment")
        if cohort_assets is None:
            lem_env = like_equipment_matcher(asset, list(self._fleet_index.values()))
            trace.append(_trace_entry(lem_env, ["cohort"]))
            cohort_assets = [self._fleet_index[c["equipment_id"]] for c in lem_env["data"]["cohort"]]
        cmp_env = pm_comparison_engine(asset, cohort_assets)
        trace.append(_trace_entry(cmp_env, ["standardization_candidates"]))
        result["comparison_result"] = cmp_env["data"]

        # Trial monitoring (Wave D), only when a trial is active
        if asset.get("trial"):
            tm_env = trial_monitor(asset["trial"])
            trace.append(_trace_entry(tm_env, ["decision", "reason"]))
            result["trial"] = tm_env["data"]

        # Row-level detail (Level 2): individual work orders + notifications, scope-locked + row-capped.
        # In-scope path only (this method is skipped on the scope short-circuit), so out-of-scope assets
        # never expose line items - scope stays authoritative.
        tw = result.get("time_window", "LAST_24_MONTHS")
        detail_scope = {"equipment_id": asset["equipment_id"], "time_window": tw,
                        "scope_validated": scope.get("scope_validated", True)}
        for tmpl in ("work_order_detail", "notification_detail"):
            d_env = run_scoped_sql(tmpl, detail_scope,
                                   {"equipment_id": asset["equipment_id"], "time_window": tw, "row_cap": _DETAIL_ROW_CAP},
                                   executor=self._sql_executor())
            result.setdefault("evidence", {})[tmpl] = d_env["data"].get("records", [])
            trace.append(_trace_entry(d_env, ["template_name", "row_count", "executor_bound"]))

        # Reliability EVIDENCE (Wave-B extension, tools 25-27). Computes MTBF/MTTR/availability, the
        # Weibull hazard shape + P(fail)/RUL, and a light failure-mode (RCA) grouping from the dated
        # failure history. EVIDENCE ONLY: it populates result["reliability"] + a prominent, math-
        # defensible interpretation for the narration / recommendation - it NEVER changes the classifier
        # label or the gate, and every judgment threshold stays BU_DEFINED.
        _emit("reliability_evidence")
        window_days = {"LAST_12_MONTHS": 365, "LAST_24_MONTHS": 730, "LAST_36_MONTHS": 1095}.get(tw, 730)
        events = asset.get("failure_events") or []
        rm_env = reliability_metrics(events, window_days)
        wb_env = weibull_reliability(events, window_days)
        fm_env = failure_mode_summary(events)
        for env in (rm_env, wb_env, fm_env):
            trace.append(_trace_entry(env, ["computable", "n_failures"]))
        result["reliability"] = {"metrics": rm_env["data"], "weibull": wb_env["data"], "failure_modes": fm_env["data"]}
        result["reliability_interpretation"] = " ".join(
            d.get("interpretation") for d in (rm_env["data"], wb_env["data"], fm_env["data"]) if d.get("interpretation"))

        # SAP-transactional anomaly / drift EVIDENCE (tools 29-30). Runs on the SAME feeds as the
        # reliability tools (failure_events + wo_detail) plus the like-equipment cohort already computed
        # here. EVIDENCE ONLY, placed AFTER the recommendation + gate are formed, so it can never change
        # the label or the gate - it only enriches the narration + artifacts. reliability_drift_monitor
        # flags failure-interval drift/trend, MTTR drift (fail-closed on Oxy's all-zero Breakdown_Duration),
        # reactive-work-mix level+trend, and a cohort bad-actor outlier; sap_cost_distribution reports the
        # material/services cost bands (labor-blind; no savings claim). Every threshold stays BU_DEFINED.
        wo_detail = asset.get("wo_detail") or []
        cohort_stats = [{"equipment_id": ca["equipment_id"],
                         "failure_count": len(ca.get("failure_events") or []),
                         "reactive_share": reactive_share(ca.get("wo_detail") or [])}
                        for ca in (cohort_assets or [])]
        uncoded = (fm_env["data"] or {}).get("uncoded_pct")
        crit_unvalidated = bool((criticality or {}).get("validated") is False
                                or (criticality or {}).get("code") in (None, "", "0"))
        drift_env = reliability_drift_monitor(
            events, wo_detail=wo_detail, cohort=cohort_stats, window_days=window_days,
            uncoded_pct=uncoded, cohort_criticality_unvalidated=crit_unvalidated)
        cost_events = [{"total_cost": w.get("total_cost"), "material_cost": w.get("material_cost"),
                        "order_type": w.get("order_type")} for w in wo_detail]
        cost_env = sap_cost_distribution(cost_events)
        for env in (drift_env, cost_env):
            trace.append(_trace_entry(env, ["computable", "any_drift_flag", "cost_p50"]))
        result["reliability_drift"] = drift_env["data"]
        result["cost_distribution"] = cost_env["data"]
        drift_interp = " ".join(x for x in (drift_env["data"].get("interpretation"),
                                            cost_env["data"].get("interpretation")) if x)
        if drift_interp:
            result["reliability_interpretation"] = (
                (result.get("reliability_interpretation") or "") + " " + drift_interp).strip()

    def _finish_gate(self, gate_env, proposed, asset, criticality, provenance, actor=None,
                     rec_reco=None, rec_gate_env=None) -> Dict[str, Any]:
        gate = gate_env["data"]
        # The acting user comes from Databricks authentication when available (70/06); a self-typed
        # name is never accepted as authorization. Falls back to the planner stub in local mode.
        actor = actor or {"user_id": "planner-01", "roles": ["planner_scheduler"]}

        # Coupling (70/10): the package drafts MAX's RECOMMENDATION, gated by the recommendation's
        # own gate - so the package and the recommendation always agree. On the scope-blocked path
        # (no recommendation supplied) it drafts the requested change as before (fail-closed).
        if rec_reco is not None and rec_gate_env is not None:
            pkg_reco = {**proposed, **rec_reco}  # rec type/direction wins; keep strategy context
            pkg_gate_env = rec_gate_env
            pkg_current = asset.get("current_value")
            pkg_proposed = rec_reco.get("next_action") or rec_reco.get("type")
        else:
            pkg_reco, pkg_gate_env = proposed, gate_env
            pkg_current, pkg_proposed = asset.get("current_value"), asset.get("proposed_value")
        pkg_gate_status = pkg_gate_env["data"].get("gate_status")

        # 9. draft_sap_change_package (drafts the recommendation on the in-scope path)
        pkg_env = draft_sap_change_package(
            recommendation=pkg_reco, gate_result=pkg_gate_env, evidence=[], criticality=criticality,
            readiness=asset["readiness"], bu_profile=self.bu_profile,
            current_value=pkg_current, proposed_value=pkg_proposed,
            provenance=provenance, affected_sap_objects=["MaintenanceItem", "TaskList"],
        )
        # 10. approval_workflow_state (approves the PACKAGE, so it follows the package's gate)
        wf_env = approval_workflow_state(
            package_id=f"PKG-{asset['equipment_id']}", current_state="DRAFT",
            requested_transition="ANALYST_REVIEWED",
            actor=actor,
            gate_status=pkg_gate_status, readiness=asset["readiness"],
            approval_state=asset["approval_state"], creator_user_id=actor.get("user_id", "analyst-09"),
        )
        return {
            # Headline gate = the requested change's gate (exercises all 4 statuses; demo + tests).
            "gate_status": gate.get("gate_status"), "gate_reason": gate_env.get("blocked_reason"),
            "gate_review_trigger": gate.get("review_trigger"),
            "required_approvers": gate.get("required_approvers", []),
            "allowed_next_actions": gate.get("allowed_next_actions", []),
            "blocked_actions": gate.get("blocked_actions", []),
            # The package (and its approval path) follow MAX's recommendation.
            "package": pkg_env["data"], "package_gate_status": pkg_gate_status,
            "workflow": wf_env["data"],
        }

    def _attach_evidence(self, result: Dict[str, Any]) -> None:
        """Attach the evidence digest ('what the data shows') + the SAP data-needs list so every
        summary path (deterministic, LLM narration, agentic) can cite them. Presentation only."""
        result["evidence_digest"] = build_evidence_digest(result)
        result["data_needs"] = data_needs(result)

    def _summary(self, result: Dict[str, Any]):
        """Governed narration through the shared narration gate. Returns (text, producer) where producer
        is 'llm' or 'deterministic'. Callers that only want the text use [0]."""
        from .prompts import _fix_preamble
        gate = result.get("gate_status")
        first = self.client.llm_complete(narration_prompt(result), NARRATION_SYSTEM)
        return self._narrate_guarded(
            first, gate,
            regenerate=lambda: self.client.llm_complete(
                _fix_preamble(gate, first) + "\n\n" + narration_prompt(result), NARRATION_SYSTEM),
            fallback=lambda: deterministic_summary(result))

    # --- portfolio (PM Health) --------------------------------------------
    def portfolio(self) -> List[Dict[str, Any]]:
        rows = []
        for asset in synthetic_fleet():
            r = self._run_asset(asset, narrate=False)  # portfolio rows never use chat_summary; skip the LLM
            rows.append({
                "equipment_id": r["equipment_id"], "asset_class": r["asset_class"],
                "pm_id": r.get("pm_id"),
                "criticality": asset["master_data"]["criticality"]["code"],
                "label": r.get("classifier_label"), "gate_status": r.get("gate_status"),
                "gate_reason": r.get("gate_reason") or r.get("gate_review_trigger"),
                "do_not_optimize": r.get("do_not_optimize"), "provenance": r.get("provenance"),
                "data_readiness": asset["readiness"].get("data_readiness"),
                "next_action": r.get("recommendation_next_action"),
            })
        return rows

    def portfolio_health(self) -> Dict[str, Any]:
        """PM Health view: triage queue + distribution metrics + baseline KPIs over the scoped fleet.

        Composes the Wave B/D aggregators (pm_portfolio_triage, pm_health_dashboard_metrics,
        value_kpi_tracker) over the same rows the PM Health table renders.
        """
        rows = self.portfolio()
        return {
            "rows": rows,
            "triage": pm_portfolio_triage(rows)["data"],
            "metrics": pm_health_dashboard_metrics(rows)["data"],
            "kpis": value_kpi_tracker(rows)["data"],
        }
