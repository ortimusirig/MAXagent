"""Lightweight session state for the MAX Agent app.

The Dash callbacks are stateless (each selection recomputes deterministically), so state here is
minimal: the selected asset, the last agent result, and a per-session run counter for the Tool
Trace / audit. No secrets are stored; nothing here decides an Oxy value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SessionState:
    selected_equipment_id: Optional[str] = None
    last_result: Optional[Dict[str, Any]] = None
    run_count: int = 0
    actor: Dict[str, Any] = field(default_factory=lambda: {"user_id": "local", "roles": []})

    def record(self, equipment_id: str, result: Dict[str, Any]) -> None:
        self.selected_equipment_id = equipment_id
        self.last_result = result
        self.run_count += 1
