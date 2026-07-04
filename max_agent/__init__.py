"""MAX Agent - governed preventive-maintenance strategy copilot for Oxy.

This package holds the deterministic tool core. The tools in ``max_agent.tools`` are
pure Python and Databricks-free so they can be unit tested in isolation, per
``70 - MAX Agent Build/02 - App Repository Scaffold`` ("Development Rule").

Hard rules that govern this code (see AGENT.md and the folder-70 specs):
- Draft-only. No direct SAP write-back in Wave 1.
- One MAX Agent, one 24-tool library. Canonical tool names only.
- Safety-critical decisions are deterministic, not free-form LLM judgment.
- BU and threshold values are PROPOSED / BU_DEFINED placeholders until Oxy confirms them.
"""

__all__ = ["schemas", "config", "tools"]
