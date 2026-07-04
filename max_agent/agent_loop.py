"""LangGraph LLM tool-calling orchestration for the MAX Agent chat path.

Models the finance agent's `create_react_agent` pattern (LangGraph ReAct + per-thread memory), but
adds the GOVERNANCE FENCE the finance agent lacks:

- The deterministic safety spine (scope -> classifier -> gate -> package) has ALREADY run and is
  AUTHORITATIVE. This layer only plans read-only tool calls to answer the user's question and
  narrates; it never decides, skips, or overrides the gate/label (they are not in its writable
  control - see agent_tools: the only tools are read-only).
- Scope is locked into the tools, so the LLM cannot run unscoped SQL; any evidence() call still goes
  through genie_query_scoped + the SELECT-only sql_guard.
- The LLM cannot invent an Oxy value (the prompt forbids it and every number comes from a
  deterministic tool result).

When langgraph / databricks_langchain / a serving endpoint are absent, `run_agentic_answer` returns
None and the orchestrator keeps the deterministic summary (the sanctioned deterministic-only mode).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

REACT_MAX_STEPS = 8

AGENT_SYSTEM_PROMPT = """You are MAX, a governed preventive-maintenance strategy copilot for Oxy.

A deterministic governance engine has ALREADY decided this asset's gate status, effectiveness label,
and recommendation. That decision is AUTHORITATIVE and final. Call governed_decision to read it. You
must NEVER contradict, re-decide, or soften it, and you must NEVER state a different gate or label.

Your job: answer the user's specific question using the read-only tools, then explain clearly.
- evidence(question): data questions (work orders, cost, findings) about this asset.
- like_equipment_comparison(): standardization / like-equipment questions.
- execution_readiness(): task-list / materials / CBM / readiness questions.
- portfolio_health(): fleet or review-queue level questions.
Call only the tools you need; do not chain tools you were not asked about.

HARD RULES:
- Never invent an Oxy value (thresholds, MOC %, approvers, cost, mandatory tags). If a number is not
  in a tool result, say it is not available.
- Wave 1 is draft-only: MAX never writes SAP. Do not imply an action was taken.
- Keep the answer to 3-6 plain-text sentences. No tables, no markdown, no emoji.
"""


def agentic_available(client) -> bool:
    """True only if a serving endpoint is bound AND the react stack is importable.

    The endpoint check comes FIRST so deterministic-only mode (no endpoint) never pays the cost of
    importing the LangGraph/LangChain stack - the heavy import only happens when the LLM path is
    actually configured.
    """
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

        from .agent_tools import make_agent_tools

        llm = ChatDatabricks(endpoint=agent.client.llm_endpoint, max_tokens=700)
        tools = make_agent_tools(agent, result)
        graph = create_react_agent(llm, tools, checkpointer=MemorySaver())

        governed = (
            f"Governed decision (authoritative): gate={result.get('gate_status')}, "
            f"label={result.get('classifier_label')}, recommendation={result.get('recommendation_type')}, "
            f"reason={result.get('gate_reason') or result.get('gate_review_trigger')}."
        )
        messages = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT + "\n\n" + governed),
            HumanMessage(content=f"Asset {result.get('equipment_id')}. Question: {question}"),
        ]
        state = graph.invoke(
            {"messages": messages},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": REACT_MAX_STEPS * 2},
        )

        narration, plan = "", []  # type: (str, List[str])
        for m in state.get("messages", []):
            tcs = getattr(m, "tool_calls", None) or []
            for tc in tcs:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if name:
                    plan.append(name)
            content = getattr(m, "content", None)
            if content and not tcs and isinstance(content, str):
                narration = content
        return {"narration": narration.strip(), "plan": plan, "mode": "llm_orchestrated"}
    except Exception:
        return None
