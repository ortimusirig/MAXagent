"""Tool-augmented FREE-FLOW loop for the MAX Agent chat path.

The GOVERNED lane is deterministic + a single guarded narration (no LLM tool-loop). FREE-FLOW - a
follow-up / explanatory turn - keeps a genuine agentic loop, but on the READ-ONLY tools only:

- The bound model may SELECT and RUN the read-only tools (make_agent_tools) to fetch or read facts
  before answering: read the frozen governed decision, pull scoped evidence, reliability, like-equipment
  comparison, execution readiness, spare-parts/BOM completeness, portfolio health.
- It NEVER re-runs oxy_gate_check and never re-decides: there is no decide-tool in this set, so free-flow
  can explore and explain but cannot mint a new gate / label / recommendation. A fresh decision must go
  through the governed lane.
- The tool outputs are deterministic (the model can't invent them). The final answer is still routed
  through MaxAgent._narrate_guarded, so it can never affirm a non-PASS gate.

Manual `bind_tools` loop (no langgraph, whose version fragility crashed the stack on Databricks). When
the serving endpoint / langchain stack is absent, `run_free_flow_agent` returns None and the caller
falls back to a single conversational call, then to a deterministic glossary answer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

REACT_MAX_STEPS = 8


def free_flow_tools_available(client) -> bool:
    """True when the tool-augmented free-flow loop is usable: a serving endpoint is bound AND the
    langchain stack is importable. No env flag - the read-only free-flow loop is a first-class
    capability, on whenever the model + stack are present (offline / unbound just falls back)."""
    if not bool(getattr(client, "llm_bound", lambda: False)()):
        return False
    try:
        import databricks_langchain  # noqa: F401
        import langchain_core  # noqa: F401
    except Exception:
        return False
    return True


FREE_FLOW_TOOL_SYSTEM = """You are MAX, a governed preventive-maintenance copilot for Oxy, answering a
FOLLOW-UP / explanatory question conversationally.

You MAY CALL these READ-ONLY tools to ground your answer in real values before replying: governed_decision
(the authoritative gate / effectiveness label / recommendation for the last analysed asset - cite it,
NEVER contradict it), evidence (scoped work orders / cost / findings), like_equipment_comparison,
execution_readiness, reliability, parts_bom, reliability_drift (SAP failure-interval / reactive-mix /
cohort-outlier drift signals), cost_distribution (own P10/P50/P90 cost bands, material/services only),
portfolio_health. Call the few you need, read them, and
answer with those EXACT values. NEVER invent a gate status, effectiveness label, recommendation,
threshold, cost, or approver - if a value is not in a tool result, say it is not available.

You do NOT re-decide anything: there is no tool here that runs the gate, the classifier, or a
recommendation, and none that writes SAP, drafts a change package, or records an approval. A fresh
decision or a different asset must go through the governed Work Strategy Studio. Draft-only in Wave 1.
Do not affirm a change the gate did not pass - you may explain a non-PASS gate, never approve it. Explain
governed terms in plain language. No emoji. Be concise and genuinely helpful."""


def run_free_flow_agent(agent, question: str, messages, last_result: Optional[Dict[str, Any]],
                        extra_tools=None, system: Optional[str] = None, on_step=None) -> Optional[str]:
    """Tool-augmented FREE-FLOW on the READ-ONLY tools. The model may SELECT and RUN make_agent_tools
    (read the frozen last decision + fetch scoped evidence / reliability / comparison / readiness / BOM /
    portfolio) to ground its answer, then reply conversationally. It NEVER re-runs the AUTHORITATIVE gate
    and cannot mint a new gate / label / recommendation (no decide-tool is exposed). `extra_tools` may add
    read-only advisory tools for a sub-intent (e.g. the GATE_CHECK branch adds preview_gate_check, which
    runs the deterministic gate READ-ONLY on a hypothetical and returns an advisory verdict); `system`
    overrides the system prompt for that sub-intent. Returns the answer, or None when there is no prior
    result / the stack is unavailable (caller falls back)."""
    if not last_result or not last_result.get("equipment_id") or not free_flow_tools_available(agent.client):
        return None
    try:
        import json

        from databricks_langchain import ChatDatabricks
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        from .agent_tools import make_agent_tools
        from .prompts import _glossary_block, _last_result_block, _transcript_block

        tools = make_agent_tools(agent, last_result) + list(extra_tools or [])  # READ-ONLY, never re-decides
        tool_map = {t.name: t for t in tools}
        llm = ChatDatabricks(endpoint=agent.client.llm_endpoint, max_tokens=1500).bind_tools(tools)
        ctx = (f"{_glossary_block()}\n\nLAST GOVERNED RESULT (reference it; do not re-decide):\n"
               f"{_last_result_block(last_result)}\n\nConversation so far:\n{_transcript_block(messages)}")
        msgs: List[Any] = [SystemMessage(content=system or FREE_FLOW_TOOL_SYSTEM),
                           HumanMessage(content=f"{ctx}\n\nUser: {question}")]
        answer = ""
        for _ in range(REACT_MAX_STEPS):
            resp = llm.invoke(msgs)
            msgs.append(resp)
            tcs = getattr(resp, "tool_calls", None) or []
            if not tcs:
                answer = resp.content if isinstance(resp.content, str) else answer
                break
            # DISPLAY-ONLY progress: one 'planning' group header per LLM turn that selects tools, then one
            # row per tool AS IT RESOLVES. A single turn can fan out to 2-3 tools -> 2-3 rows. on_step never
            # affects the loop or the answer; the final answer still passes through the narration gate.
            if on_step:
                on_step("planning")
            for tc in tcs:
                fn = tool_map.get(tc.get("name"))
                out = fn.invoke(tc.get("args", {}) or {}) if fn else {"error": f"unknown tool {tc.get('name')}"}
                if on_step and tc.get("name"):
                    on_step(tc.get("name"))
                msgs.append(ToolMessage(content=json.dumps(out, default=str), tool_call_id=tc.get("id")))
        return (answer or "").strip() or None
    except Exception:
        return None
