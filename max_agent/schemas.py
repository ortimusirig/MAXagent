"""Standard tool-result envelope.

Every MAX tool returns the same envelope, defined in
``70 - MAX Agent Build/04 - MAX Tool Library Implementation Plan`` ("Standard Tool Result
Contract"). Tool-specific fields live under ``data``. Keeping one envelope means the
orchestrator never needs one-off per-tool result parsing.

    {
      "status": "success | warning | blocked | error",
      "tool": "tool_name",
      "summary": "short human-readable summary",
      "data": {},
      "evidence": [],
      "params_used": {},
      "confidence": "high | medium | low",
      "scope_validated": true,
      "blocked_reason": null
    }
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Coarse envelope status values.
STATUS_SUCCESS = "success"
STATUS_WARNING = "warning"
STATUS_BLOCKED = "blocked"
STATUS_ERROR = "error"

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"


def tool_envelope(
    tool: str,
    status: str,
    summary: str,
    data: Optional[Dict[str, Any]] = None,
    evidence: Optional[List[Any]] = None,
    params_used: Optional[Dict[str, Any]] = None,
    confidence: str = CONFIDENCE_MEDIUM,
    scope_validated: bool = True,
    blocked_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the standard tool-result envelope.

    ``data`` carries all tool-specific fields. ``blocked_reason`` is surfaced at the top
    level so the orchestrator and Tool Trace can read it without inspecting ``data``.
    """
    return {
        "status": status,
        "tool": tool,
        "summary": summary,
        "data": data or {},
        "evidence": evidence or [],
        "params_used": params_used or {},
        "confidence": confidence,
        "scope_validated": scope_validated,
        "blocked_reason": blocked_reason,
    }
