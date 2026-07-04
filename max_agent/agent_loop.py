"""LangGraph LLM tool-calling orchestration for the MAX Agent chat path.

Sonnet SELECTS and SEQUENCES the real deterministic tools to answer the question (the finance-agent
`create_react_agent` pattern), with the GOVERNANCE FENCE the finance agent lacks:

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
        import langgraph  # noqa: F401
        import databricks_langchain  # noqa: F401
        import langchain_core  # noqa: F401
    except Exception:
        return False
    return True


def run_agentic_answer(agent, result: Dict[str, Any], question: str,
                       thread_id: str = "default") -> Optional[Dict[str, Any]]:
    """Answer `question` about the already-governed `result` via a LangGraph react agent.

    Returns {"narration", "plan", "mode"} or None when the agentic stack / endpoint is unavailable
    (the caller then keeps the deterministic summary). Any failure degrades to None, never raises.
    """
    if not agentic_available(agent.client):
        return None
    try:
        from langgraph.prebuilt import create_react_agent
        from langgraph.checkpoint.memory import MemorySaver
        from databricks_langchain import ChatDatabricks
        from langchain_core.messages import HumanMessage, SystemMessage

        from .agent_tools import make_orchestration_tools, enforce_mandatory

        asset = agent._fleet_index.get(result.get("equipment_id"))
        if asset is None:
            return None
        state: Dict[str, Any] = {"time_window": result.get("time_window", "LAST_24_MONTHS")}
        tools = make_orchestration_tools(agent, asset, state)
        llm = ChatDatabricks(endpoint=agent.client.llm_endpoint, max_tokens=800)
        graph = create_react_agent(llm, tools, checkpointer=MemorySaver())

        messages = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Asset {result.get('equipment_id')} ({result.get('asset_class')}), plant "
                f"{result.get('plant')}, criticality {result.get('criticality_code')}. Question: {question}")),
        ]
        graph_state = graph.invoke(
            {"messages": messages},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": REACT_MAX_STEPS * 2},
        )

        narration, plan = "", []  # type: (str, List[str])
        for m in graph_state.get("messages", []):
            tcs = getattr(m, "tool_calls", None) or []
            for tc in tcs:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if name:
                    plan.append(name)
            content = getattr(m, "content", None)
            if content and not tcs and isinstance(content, str):
                narration = content

        # FENCE: guarantee the mandatory deterministic tools ran (run them if the AI skipped one).
        enforce_mandatory(agent, asset, state)
        for name in _MANDATORY:
            if name not in plan:
                plan.append(f"{name} (enforced)")
        return {"narration": narration.strip(), "plan": plan, "mode": "llm_orchestrated"}
    except Exception:
        return None
