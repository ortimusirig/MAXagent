"""LLM entity extraction for the Ask MAX chat (Finance-agent-style), with the deterministic resolver
as the fail-closed FLOOR.

The Finance app lets the model function-call typed entities straight into every tool. MAX wants the
same capability - the model reads the chat and proposes typed entities that scope every tool - but
keeps governance: the model PROPOSES, the deterministic layer VALIDATES. An entity that is not in the
known fleet / closed vocabulary is rejected (never fabricated), and `validate_scope` still fail-closes
on operated/JV/exempt downstream. When no LLM endpoint is bound, extraction degrades to the
deterministic resolver alone, so the app behaves identically offline.

The extracted entities become the run's single validated scope for the turn (one governed decision per
turn), and are injected into the pipeline (equipment_id + time_window + review_type today; plant /
class / criticality extend comparison and portfolio filters next).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from .intent import resolve_asset_from_text

TIME_WINDOWS = {"LAST_12_MONTHS", "LAST_24_MONTHS", "LAST_36_MONTHS"}
REVIEW_TYPES = {
    "PM effectiveness and strategy review",
    "Frequency change review",
    "CBM conversion review",
    "Task list cleanup review",
    "Retire / run-to-failure review",
}
CRITICALITY = {"0", "1", "2", "3", "4", "N"}

# The closed catalog of VISUAL artifacts the model may select for the Ask MAX Artifacts tab
# (name -> when it applies). The renderers live in ui/artifact_catalog.py.
ARTIFACT_CHOICES = {
    "work_order_mix": "PM vs corrective/reactive work-order mix chart",
    "data_readiness": "data-readiness RAG and the SAP data still needed",
    "cost": "honest cost view (material vs labor basis)",
    "comparison": "like-equipment comparison and standardization candidates",
    "evidence_table": "work-order evidence with a Summary/Detailed toggle (breakdown + failure coding, "
                      "and the individual per-order and per-notification records)",
    "reliability": "reliability evidence - MTBF/MTTR/availability, the Weibull failure-hazard shape and "
                   "RUL, and the top failure modes (evidence, not a decision)",
    "drift_anomaly": "SAP-transactional anomaly / drift evidence - failure-interval drift and trend, "
                     "reactive-work-mix trend, cohort bad-actor outlier, and the material/services cost "
                     "bands (evidence that flags a candidate change; not a decision)",
}

ENTITY_SYSTEM = (
    "You are MAX's entity extractor for Oxy preventive-maintenance questions. Read the user's question "
    "and return ONLY a JSON object of the entities you can identify, using the fields and CLOSED "
    "vocabularies below. Omit a field if it is not present; NEVER invent a value not in the provided "
    "lists.\n"
    "- equipment_id: exactly one id from the provided known-equipment list.\n"
    "- asset_class: one value from the provided known-asset-classes list.\n"
    "- plant: one value from the provided known-plants list.\n"
    "- criticality: one of 0, 1, 2, 3, 4, N.\n"
    "- pm_id: a PM id only if the user names one.\n"
    "- time_window: one of LAST_12_MONTHS, LAST_24_MONTHS, LAST_36_MONTHS "
    "(map 'last year'->LAST_12_MONTHS, '2 years'->LAST_24_MONTHS, '3 years'->LAST_36_MONTHS).\n"
    "- review_type: one of 'PM effectiveness and strategy review', 'Frequency change review', "
    "'CBM conversion review', 'Task list cleanup review', 'Retire / run-to-failure review'.\n"
    "- artifacts: a JSON list naming ONLY the visual artifacts this answer needs, chosen from: "
    "work_order_mix, data_readiness, cost, comparison, evidence_table, reliability, drift_anomaly. Pick the "
    "few that fit the question (e.g. a frequency question needs comparison + work_order_mix + reliability; a "
    "cost question needs cost; a 'why blocked' question needs data_readiness). For a reliability / failure-rate "
    "/ MTBF / RUL / 'why does it keep failing' question, select reliability. For an 'is it getting worse / "
    "trending / accelerating / a bad actor vs peers / cost outlier' question, select drift_anomaly. For anything about work "
    "orders / the breakdown / individual records / 'all work orders' / 'list them' / details, select "
    "evidence_table (it has a Summary/Detailed toggle - the individual per-order and per-notification "
    "records live under its Detailed tab); add work_order_mix for the chart if a visual helps. (The "
    "deterministic tool trace + SQL are NOT an artifact - they render automatically in the Governance "
    "Trace tab.)\n"
    "Return strictly JSON with only the fields you found. No prose, no code fences."
)


def _known(fleet: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "equipment_ids": list(fleet),
        "asset_classes": sorted({a.get("asset_class") for a in fleet.values() if a.get("asset_class")}),
        "plants": sorted({a.get("plant") for a in fleet.values() if a.get("plant")}),
    }


def _extract_llm(client, question: str, fleet: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """One LLM call that proposes entities as JSON. Returns {} on any failure (never raises)."""
    known = _known(fleet)
    prompt = (
        f"Known equipment ids: {known['equipment_ids']}\n"
        f"Known asset classes: {known['asset_classes']}\n"
        f"Known plants: {known['plants']}\n\n"
        f"Question: {question}\n\nReturn the entity JSON."
    )
    raw = None
    try:
        raw = client.llm_complete(prompt, ENTITY_SYSTEM)
    except Exception:
        return {}
    if not raw:
        return {}
    m = re.search(r"\{.*\}", raw, re.S)  # first JSON object in the reply
    if not m:
        return {}
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _valid(value: Any, allowed: set) -> Optional[Any]:
    return value if value in allowed else None


def extract_entities(client, question: str, fleet: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Return validated typed entities from the chat. The deterministic resolver is the fail-closed
    floor: an LLM-proposed equipment_id that is not a real fleet id is rejected in favour of the
    deterministic match, and every other field must be in its closed vocabulary or it is dropped."""
    det = resolve_asset_from_text(question or "", fleet)
    llm_bound = bool(getattr(client, "llm_bound", lambda: False)())
    llm = _extract_llm(client, question or "", fleet) if llm_bound else {}
    known = _known(fleet)

    # equipment_id: a VALIDATED llm id (must be a real fleet id) wins; else the deterministic match.
    eid = llm.get("equipment_id")
    if eid not in fleet:  # governance floor - never accept a fabricated / out-of-fleet id
        eid = det.get("equipment_id")

    crit = llm.get("criticality")
    crit = str(crit) if crit is not None else None

    arts = llm.get("artifacts")
    artifacts = [a for a in arts if a in ARTIFACT_CHOICES] if isinstance(arts, list) else []

    return {
        "equipment_id": eid,
        "asset_class": _valid(llm.get("asset_class"), set(known["asset_classes"])),
        "plant": _valid(llm.get("plant"), set(known["plants"])),
        "criticality": _valid(crit, CRITICALITY),
        "pm_id": llm.get("pm_id") or None,
        "time_window": _valid(llm.get("time_window"), TIME_WINDOWS) or "LAST_24_MONTHS",
        "review_type": _valid(llm.get("review_type"), REVIEW_TYPES),
        "artifacts": artifacts,  # model-selected visual artifacts (validated to the closed catalog)
        "provenance": "llm+deterministic" if llm else "deterministic",
        "matched_on": det.get("matched_on"),
        "candidates": det.get("candidates", []),
    }
