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
