"""LLM tool-calling orchestration for the MAX Agent chat path.

Sonnet SELECTS and SEQUENCES the real deterministic tools to answer the question, via a manual
`bind_tools` loop (the supply-chain agent pattern; no langgraph, which avoids its version fragility),
with the GOVERNANCE FENCE the finance/supply-chain agents lack:

- The AI calls the tools; each tool runs DETERMINISTIC Oxy logic (parameterized by the locked asset)
  and returns its real output. The AI never computes or invents a gate/label/Oxy value - it reads
  them from the tool results.
- MANDATORY tools (lock_scope -> classify_effectiveness -> run_oxy_gate) are ENFORCED after the AI's
  turn: if the AI skipped one it is run deterministically, so the governed decision always exists and
  is deterministic. The separately-computed deterministic result (orchestrator._run_asset) remains
  the authoritative source the UI renders; this layer contributes the AI's tool-call DAG + narration.
- Retrieval stays scoped (genie_query_scoped + the SELECT-only sql_guard); the narration is guarded
  against contradicting the gate.

Off unless MAX_AGENTIC_ORCHESTRATION is set (it makes several LLM calls per turn). When the stack /
endpoint is absent, `run_agentic_answer` returns None and the caller keeps the single-call narration.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .agent_tools import _MANDATORY

REACT_MAX_STEPS = 8

AGENT_SYSTEM_PROMPT = """You are MAX, a governed preventive-maintenance strategy copilot for Oxy.

Answer the user's question by CALLING tools. Each tool runs deterministic Oxy logic - you decide
which tools to call and in what order; you never compute or guess their outputs yourself.

For any question about whether a PM is effective or whether anything should change, you MUST establish
the governed decision by calling, in dependency order:
  lock_scope -> classify_effectiveness -> recommend_change -> run_oxy_gate
Then call whichever of retrieve_evidence / check_data_readiness / execution_readiness /
compare_like_equipment / portfolio_health the question needs, read the outputs, and answer.

HARD RULES:
- The gate status, effectiveness label, and recommendation come ONLY from run_oxy_gate /
  classify_effectiveness / recommend_change. Never state a different gate or label than the tools
  returned. Never invent an Oxy value (thresholds, MOC %, approvers, cost, mandatory tags) - if it is
  not in a tool result, say it is not available.
- Wave 1 is draft-only: MAX never writes SAP. Do not imply an action was taken.
- Answer in 3-6 sentences (headings/bold are fine; no emoji).
"""


def agentic_available(client) -> bool:
    """True only if the multi-step react agent is explicitly enabled AND usable.

    The react tool-calling loop is OPT-IN (env MAX_AGENTIC_ORCHESTRATION) because it makes several
    LLM calls per turn; by default the chat path uses a single question-aware LLM narration, which is
    fast and already conversational. Enable the flag to turn on LLM-selected tool orchestration.
    """
    if not os.environ.get("MAX_AGENTIC_ORCHESTRATION"):
        return False
    if not bool(getattr(client, "llm_bound", lambda: False)()):
        return False
    try:
        import databricks_langchain  # noqa: F401
        import langchain_core  # noqa: F401
    except Exception:
        return False
    return True


def run_agentic_answer(agent, result: Dict[str, Any], question: str,
                       thread_id: str = "default", on_step=None) -> Optional[Dict[str, Any]]:
    """Answer `question` about the already-governed `result` via a LangGraph react agent.

    Returns {"narration", "plan", "mode"} or None when the agentic stack / endpoint is unavailable
    (the caller then keeps the deterministic summary). Any failure degrades to None, never raises.
    """
    if not agentic_available(agent.client):
        return None
    try:
        import json

        from databricks_langchain import ChatDatabricks
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        from .agent_tools import enforce_mandatory, make_orchestration_tools

        asset = agent._fleet_index.get(result.get("equipment_id"))
        if asset is None:
            return None
        state: Dict[str, Any] = {"time_window": result.get("time_window", "LAST_24_MONTHS")}
        tools = make_orchestration_tools(agent, asset, state)
        tool_map = {t.name: t for t in tools}
        # Manual tool-calling loop (ChatDatabricks.bind_tools) - no langgraph, avoids its version
        # fragility. This is the finance/supply-chain agent pattern: invoke -> run tool_calls -> feed
        # ToolMessages back -> repeat until the model answers.
        llm = ChatDatabricks(endpoint=agent.client.llm_endpoint, max_tokens=800).bind_tools(tools)

        messages: List[Any] = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Asset {result.get('equipment_id')} ({result.get('asset_class')}), plant "
                f"{result.get('plant')}, criticality {result.get('criticality_code')}. Question: {question}")),
        ]
        narration, plan = "", []  # type: (str, List[str])
        for _ in range(REACT_MAX_STEPS):
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
                    on_step(name)  # report the tool MAX is running (UI shows a friendly label)
                fn = tool_map.get(name)
                out = fn.invoke(tc.get("args", {}) or {}) if fn else {"error": f"unknown tool {name}"}
                messages.append(ToolMessage(content=json.dumps(out, default=str), tool_call_id=tc.get("id")))

        # FENCE: guarantee the mandatory deterministic tools ran (run them if the AI skipped one).
        enforce_mandatory(agent, asset, state)
        for name in _MANDATORY:
            if name not in plan:
                plan.append(f"{name} (enforced)")
        return {"narration": (narration or "").strip(), "plan": plan, "mode": "llm_orchestrated"}
    except Exception:
        return None
