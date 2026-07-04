"""MAX Agent orchestrator.

One MAX Agent that selects and sequences the deterministic tool library for a single asset (the
Wave-A path from 04): resolve context -> validate scope -> retrieve evidence -> classify ->
data-readiness -> recommend -> gate -> draft package -> approval state. Safety decisions are
deterministic; the LLM only narrates. Every tool call is recorded in a Tool Trace.

The orchestrator reads the same record shape whether it comes from the synthetic fleet or (later)
governed Databricks views, so real-data cutover changes only the data source, not this pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import load_bu_profile
from .databricks_client import MaxDatabricksClient
from .prompts import NARRATION_SYSTEM, deterministic_summary, narration_prompt
from .sql_templates import local_synthetic_executor
from .synthetic_data import fleet_index, synthetic_fleet
from .tools import (
    approval_workflow_state,
    cbm_measurement_readiness,
    contractor_service_readiness,
    data_readiness_gate,
    draft_sap_change_package,
    genie_query_scoped,
    like_equipment_matcher,
    materials_component_readiness,
    oxy_gate_check,
    planned_hours_calibration,
    pm_comparison_engine,
    pm_effectiveness_classifier,
    pm_health_dashboard_metrics,
    pm_portfolio_triage,
    procurement_readiness,
    recommend_strategy_change,
    resolve_context,
    risk_business_justification,
    run_scoped_sql,
    task_list_bom_readiness,
    trial_monitor,
    validate_scope,
    value_kpi_tracker,
)

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


class MaxAgent:
    def __init__(self, bu_profile: Optional[Dict[str, Any]] = None, client: Optional[MaxDatabricksClient] = None) -> None:
        self.bu_profile = bu_profile or load_bu_profile("default_oxy")
        self.client = client or MaxDatabricksClient()
        self._fleet_index = fleet_index()

    # --- single-asset run --------------------------------------------------
    def run(self, equipment_id: str) -> Dict[str, Any]:
        asset = self._fleet_index.get(equipment_id)
        if asset is None:
            return {"error": f"Unknown asset: {equipment_id}", "known_assets": list(self._fleet_index)}
        return self._run_asset(asset)

    def _sql_executor(self):
        return self.client.sql_executor() or local_synthetic_executor(self._fleet_index)

    def _run_asset(self, asset: Dict[str, Any]) -> Dict[str, Any]:
        trace: List[Dict[str, Any]] = []
        profile = self.bu_profile

        # 1. resolve_context
        ctx_env = resolve_context(
            equipment_id=asset["equipment_id"], functional_location_id=asset["functional_location_id"],
            plant=asset["plant"], business_unit=asset["business_unit"], bu_profile_id=profile["profile_id"],
            asset_class=asset["asset_class"], time_window="LAST_24_MONTHS",
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

        # 3. run_scoped_sql (evidence)
        sql_scope = {"equipment_id": asset["equipment_id"], "time_window": "LAST_24_MONTHS", "scope_validated": scope.get("scope_validated", True)}
        evidence = {}
        executor = self._sql_executor()
        for tmpl in ("work_order_history", "cost_summary", "notification_findings"):
            sql_env = run_scoped_sql(tmpl, sql_scope, {"equipment_id": asset["equipment_id"], "time_window": "LAST_24_MONTHS"}, executor=executor)
            evidence[tmpl] = sql_env["data"].get("records", [])
            trace.append(_trace_entry(sql_env, ["template_name", "row_count", "executor_bound"]))

        result: Dict[str, Any] = {
            "equipment_id": asset["equipment_id"], "asset_class": asset["asset_class"], "plant": asset["plant"],
            "pm_id": asset["pm_id"], "user_question": asset["user_question"], "provenance": provenance,
            "scope": scope, "evidence": evidence, "expected_gate_status": asset.get("expected_gate_status"),
            "databricks_mode": self.client.mode(),
        }

        proposed = dict(asset["proposed_recommendation"])
        result["proposed_summary"] = f"{asset.get('current_value')} -> {asset.get('proposed_value')}"

        # --- Scope fail-closed short-circuit ---
        if not scope.get("scope_validated") or scope.get("in_scope") is False:
            gate_env = oxy_gate_check(
                context, scope, profile, criticality, pm_governance, proposed, asset["readiness"],
                asset["risk"], asset["approval"], asset["approval_state"], asset["requested_action"],
            )
            trace.append(_trace_entry(gate_env, ["gate_status", "review_trigger", "required_approvers"]))
            result.update(self._finish_gate(gate_env, proposed, asset, criticality, provenance))
            result["classifier_label"] = "Not classified (out of analysis scope)"
            result["recommendation_type"] = "NONE"
            result["recommendation_rationale"] = f"Asset held: {scope.get('blocked_reason')}."
            result["do_not_optimize"] = False
            result["tool_trace"] = trace
            result["chat_summary"] = self._summary(result)
            return result

        # 4. pm_effectiveness_classifier
        clf_env = pm_effectiveness_classifier(
            context, profile, criticality, pm_governance, asset["pm_attributes"],
            asset["effectiveness_signals"], asset["evidence_readiness"],
        )
        clf = clf_env["data"]
        trace.append(_trace_entry(clf_env, ["label", "protected", "protection_basis", "thresholds_status", "low_findings_guard_applied"]))

        # 5. data_readiness_gate (informational per-domain view)
        rd_type = _READINESS_TYPE.get(proposed.get("type"), "PM_EFFECTIVENESS_CLASSIFICATION")
        rd_env = data_readiness_gate(rd_type, asset["data_domain_status"], criticality, provenance)
        trace.append(_trace_entry(rd_env, ["data_readiness", "action", "missing_domains"]))

        # 6. risk_business_justification (honest cost view)
        rbj_env = risk_business_justification(
            cost_actuals_present=asset["evidence_readiness"].get("cost_actuals_present", False),
            material_cost_present=asset["cost"].get("material_cost", 0) > 0,
        )
        trace.append(_trace_entry(rbj_env, ["cost_view", "labor_cost_claim_allowed", "savings_claim_allowed"]))

        # 7. recommend_strategy_change (MAX's own recommendation)
        rec_env = recommend_strategy_change(
            classifier_label=clf["label"], data_readiness=asset["readiness"]["data_readiness"],
            risk=asset["risk"], comparison=asset.get("comparison", {}), criticality=criticality,
            pm_governance=pm_governance, readiness=asset["readiness"], bu_profile=profile,
        )
        rec = rec_env["data"]
        trace.append(_trace_entry(rec_env, ["recommendation", "do_not_optimize"]))

        # 8. oxy_gate_check on the change under consideration
        gate_env = oxy_gate_check(
            context, scope, profile, criticality, pm_governance, proposed, asset["readiness"],
            asset["risk"], asset["approval"], asset["approval_state"], asset["requested_action"],
        )
        trace.append(_trace_entry(gate_env, ["gate_status", "review_trigger", "required_approvers"]))

        result.update({
            "classifier_label": clf["label"], "classifier_protected": clf.get("protected"),
            "protection_basis": clf.get("protection_basis"), "thresholds_status": clf.get("thresholds_status"),
            "data_readiness": rd_env["data"]["data_readiness"], "cost_view": rbj_env["data"]["cost_view"],
            "recommendation_type": rec["recommendation"]["type"],
            "recommendation_rationale": rec["recommendation"]["rationale"],
            "recommendation_next_action": rec["recommendation"]["next_action"],
            "do_not_optimize": rec["do_not_optimize"],
        })
        result.update(self._finish_gate(gate_env, proposed, asset, criticality, provenance))
        self._run_extras(asset, context, scope, criticality, trace, result)
        result["tool_trace"] = trace
        result["chat_summary"] = self._summary(result)
        return result

    def _run_extras(self, asset, context, scope, criticality, trace, result) -> None:
        """Run the Wave B/C/D tools (retrieval, execution readiness, comparison, trial) and record them."""
        profile = self.bu_profile
        r = asset["readiness"]

        # genie_query_scoped (scoped; local returns empty, never runs unscoped)
        genie_env = genie_query_scoped(
            asset["user_question"],
            {"equipment_id": asset["equipment_id"], "time_window": "LAST_24_MONTHS", "scope_validated": scope.get("scope_validated", True)},
            client=self.client,
        )
        trace.append(_trace_entry(genie_env, ["genie_bound", "row_count", "referenced_relations"]))

        # Execution readiness (Wave C)
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

        # Comparison (Wave B)
        fleet = list(self._fleet_index.values())
        lem_env = like_equipment_matcher(asset, fleet)
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

    def _finish_gate(self, gate_env, proposed, asset, criticality, provenance) -> Dict[str, Any]:
        gate = gate_env["data"]
        # 9. draft_sap_change_package
        pkg_env = draft_sap_change_package(
            recommendation=proposed, gate_result=gate_env, evidence=[], criticality=criticality,
            readiness=asset["readiness"], bu_profile=self.bu_profile,
            current_value=asset.get("current_value"), proposed_value=asset.get("proposed_value"),
            provenance=provenance, affected_sap_objects=["MaintenanceItem", "TaskList"],
        )
        # 10. approval_workflow_state (initial)
        wf_env = approval_workflow_state(
            package_id=f"PKG-{asset['equipment_id']}", current_state="DRAFT",
            requested_transition="ANALYST_REVIEWED",
            actor={"user_id": "planner-01", "roles": ["planner_scheduler"]},
            gate_status=gate.get("gate_status"), readiness=asset["readiness"],
            approval_state=asset["approval_state"], creator_user_id="analyst-09",
        )
        return {
            "gate_status": gate.get("gate_status"), "gate_reason": gate_env.get("blocked_reason"),
            "gate_review_trigger": gate.get("review_trigger"),
            "required_approvers": gate.get("required_approvers", []),
            "allowed_next_actions": gate.get("allowed_next_actions", []),
            "blocked_actions": gate.get("blocked_actions", []),
            "package": pkg_env["data"], "workflow": wf_env["data"],
        }

    def _summary(self, result: Dict[str, Any]) -> str:
        narrated = self.client.llm_complete(narration_prompt(result), NARRATION_SYSTEM)
        return narrated or deterministic_summary(result)

    # --- portfolio (PM Health) --------------------------------------------
    def portfolio(self) -> List[Dict[str, Any]]:
        rows = []
        for asset in synthetic_fleet():
            r = self._run_asset(asset)
            rows.append({
                "equipment_id": r["equipment_id"], "asset_class": r["asset_class"],
                "criticality": asset["master_data"]["criticality"]["code"],
                "label": r.get("classifier_label"), "gate_status": r.get("gate_status"),
                "gate_reason": r.get("gate_reason") or r.get("gate_review_trigger"),
                "do_not_optimize": r.get("do_not_optimize"), "provenance": r.get("provenance"),
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
