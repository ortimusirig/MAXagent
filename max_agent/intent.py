"""Deterministic free-text intent resolution for the chat entry path.

The designed interaction (60/01, 60/07) lets a user EITHER pick a population/asset OR ask in chat;
`resolve_context` then converts free-form intent into a locked context. This module does the
deterministic first hop: map the typed question to an in-scope equipment_id, with NO LLM and NO
guessing of Oxy values. If nothing matches, it returns equipment_id=None so the UI asks the user to
pick - it never fabricates a target. (When an LLM endpoint is bound, richer intent parsing can layer
on top; the deterministic resolver remains the fail-closed floor.)
"""

from __future__ import annotations

import re
from typing import Any, Dict

# Everyday word -> asset_class token, so "why does this pump keep failing" resolves to a pump.
_KEYWORD_CLASS = {
    "pump": "PUMP", "compressor": "COMPRESSOR", "valve": "VALVE", "motor": "MOTOR",
    "fan": "FAN", "exchanger": "EXCHANGER", "heat exchanger": "EXCHANGER",
}


def resolve_asset_from_text(text: str, fleet_index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Resolve a free-text question to an in-scope equipment_id (deterministic, fail-open-to-ask)."""
    t = (text or "").strip().lower()
    if not t:
        return {"equipment_id": None, "matched_on": None, "candidates": []}

    # 1. An explicit equipment id in the text wins (exact substring, case-insensitive).
    for eid in fleet_index:
        if eid.lower() in t:
            return {"equipment_id": eid, "matched_on": "equipment_id", "candidates": [eid]}

    # 2. Asset-class tokens mentioned in the text (e.g. "centrifugal", "compressor").
    class_hits = []
    for eid, a in fleet_index.items():
        cls = str(a.get("asset_class", "")).lower()
        tokens = [tok for tok in re.split(r"[^a-z]+", cls) if len(tok) > 2]
        if cls and (cls.replace("_", " ") in t or any(tok in t for tok in tokens)):
            class_hits.append(eid)
    if class_hits:
        return {"equipment_id": class_hits[0], "matched_on": "asset_class",
                "candidates": class_hits}

    # 3. Everyday keyword -> class family.
    for kw, fam in _KEYWORD_CLASS.items():
        if kw in t:
            hits = [eid for eid, a in fleet_index.items() if fam in str(a.get("asset_class", "")).upper()]
            if hits:
                return {"equipment_id": hits[0], "matched_on": f"keyword:{kw}", "candidates": hits}

    # 4. Plant mention, if it narrows to something.
    for eid, a in fleet_index.items():
        if str(a.get("plant", "")).lower() in t and a.get("plant"):
            return {"equipment_id": eid, "matched_on": "plant", "candidates": [eid]}

    # Nothing matched -> ask the user to pick (never fabricate a target).
    return {"equipment_id": None, "matched_on": None, "candidates": []}
