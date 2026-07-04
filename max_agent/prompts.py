"""Narration prompts and a deterministic fallback summary.

The LLM (when a serving endpoint is bound) EXPLAINS the deterministic result in plain language.
It must never invent or override a gate status, a classifier label, or an Oxy value. When no LLM
endpoint is bound, `deterministic_summary` produces the same shape from the tool results directly,
so the app always has a chat answer.

Both paths are evidence-first: they cite the analysis MAX already ran (work-order counts, failure
coding, cost basis) and, when the data is not enough to conclude, name the SPECIFIC Oxy SAP data
still needed (from `evidence.py`, grounded in the Project Soar extract).
"""

from __future__ import annotations

from typing import Any, Dict, List

NARRATION_SYSTEM = (
    "You are MAX, a governed preventive-maintenance strategy copilot for Oxy. Explain the "
    "DETERMINISTIC result you are given in plain language for a planner or reliability engineer, as "
    "short bulleted findings. Always show your reasoning: cite the specific evidence you are given "
    "(work-order counts, failure-coding %, cost basis) - the data behind the recommendation. You must "
    "NOT change the classifier label, the gate status, the required approvers, or any Oxy value; only "
    "explain them. Cite ONLY numbers you are given; never invent a rate, a cost, or a threshold. Never "
    "claim realized savings, real CBM readiness, or a direct SAP write-back. When the data is not "
    "enough to conclude, say so plainly and list the specific SAP data still needed. Keep it to "
    "Overview, What the data shows, and Recommendation, each a few bullets."
)


def _evidence_block(result: Dict[str, Any]) -> str:
    digest = result.get("evidence_digest") or {}
    lines = digest.get("lines") or []
    return "\n".join(f"- {l}" for l in lines) or "- (no scoped evidence records returned)"


def _needs_block(result: Dict[str, Any]) -> str:
    needs = result.get("data_needs") or []
    if not needs:
        return ""
    rows = "\n".join(f"- {n['need']} (SAP source: {n['sap_source']})" for n in needs)
    return "\nData still needed before MAX can SCORE effectiveness (state these plainly, do not invent others):\n" + rows


def narration_prompt(result: Dict[str, Any]) -> str:
    d = result
    lines = [
        f"Asset: {d.get('equipment_id')} ({d.get('asset_class')}), plant {d.get('plant')}.",
        f"User question: {d.get('user_question')}.",
        f"Classifier label: {d.get('classifier_label')} (data readiness {d.get('data_readiness_rag')}, provenance {d.get('provenance')}).",
        f"Change under review: {d.get('change_under_review_type')} - gate {d.get('gate_status')}, reason {d.get('gate_reason')}.",
        f"MAX recommendation: {d.get('recommendation_type')} - gate {d.get('recommendation_gate_status')} - {d.get('recommendation_rationale')}.",
        f"Recommendation differs from the change under review: {d.get('recommendation_diverges')}.",
        f"Required approvers: {', '.join(d.get('required_approvers') or []) or 'none'}.",
        "",
        "Evidence MAX already retrieved (cite these exact numbers; do not invent others):",
        _evidence_block(result),
        _needs_block(result),
        "",
        "Answer the user's question directly using ONLY these facts, as short bulleted findings under "
        "Overview / What the data shows / Recommendation. Explain the data behind the recommendation. "
        "Do not contradict the gate or the label. Draft-only in Wave 1; humans approve; MDC/BPDO or the "
        "official Oxy process updates SAP.",
    ]
    return "\n".join(l for l in lines if l is not None)


def _question_opener(result: Dict[str, Any]) -> str:
    """A question-aware lead line so asking different things surfaces different content (no LLM)."""
    q = (result.get("user_question") or "").lower()
    if any(w in q for w in ("compare", "like equipment", "standardi", "other pump", "cohort")):
        cmp = result.get("comparison_result") or {}
        n = len(cmp.get("cohort", []))
        return f"You asked about comparison: {n} like-equipment match(es) - see the Comparison tab."
    if any(w in q for w in ("cost", "saving", "value", "hours")):
        return f"You asked about cost/value: cost view is {result.get('cost_view')} - no labor-savings claim is defensible in Wave 1."
    if any(w in q for w in ("block", "why", "reason", "allowed", "can we", "can i")):
        return f"You asked why: the change under review is {result.get('gate_status')} - {result.get('gate_reason')}."
    if any(w in q for w in ("readiness", "task list", "materials", "cbm", "execute", "ready")):
        return "You asked about readiness: see the execution-readiness checks on the Evidence tab."
    if any(w in q for w in ("effective", "effectiveness", "working", "should anything change", "change")):
        return f"You asked about effectiveness: label is {result.get('classifier_label')}; MAX recommends {result.get('recommendation_type')}."
    return f"MAX assessed asset {result.get('equipment_id')}."


def _classifier_read(result: Dict[str, Any]) -> str:
    """The plain-language link between the evidence and the classifier's read (the 'why')."""
    label = result.get("classifier_label")
    dims = result.get("dimension_results") or {}
    reason = result.get("classifier_reason")
    if label == "Missing Evidence":
        if reason == "THRESHOLDS_UNSET":
            return ("MAX describes and flags only: Oxy has not confirmed the classifier scoring "
                    "thresholds yet, so MAX will not assert Effective or Ineffective.")
        return "MAX cannot score this PM on the evidence available; it describes and flags."
    if label == "Governance Review Required":
        basis = result.get("protection_basis") or "mandatory/criticality mandate"
        return f"This is a do-not-optimize PM ({basis}); it routes to governance review, not a reduce/retire."
    if dims:
        fails = [k.replace("_", " ") for k, v in dims.items() if v in ("FAIL", "SOFT_FAIL")]
        if fails:
            return f"Effectiveness dimensions falling short: {', '.join(fails)}."
        return "The effectiveness dimensions pass at or above the confirmed thresholds."
    return ""


def deterministic_summary(result: Dict[str, Any]) -> str:
    """Plain-language, evidence-first summary built directly from the deterministic tool results.

    Structure (bulleted, matches the LLM narration shape): Overview -> What the data shows (the
    evidence + the classifier's read) -> [Not enough data to conclude, when applicable] ->
    Recommendation. Coherent by construction: the gate verdict is about the CHANGE UNDER REVIEW, and
    MAX's recommendation (with its own gate outcome) is stated separately.
    """
    gate = result.get("gate_status")
    reason = result.get("gate_reason")
    change = result.get("change_under_review_type")
    rec_type = result.get("recommendation_type")
    rec_gate = result.get("recommendation_gate_status")
    rationale = result.get("recommendation_rationale")
    next_action = result.get("recommendation_next_action")
    diverges = result.get("recommendation_diverges")
    approvers = result.get("required_approvers") or []
    synthetic = result.get("provenance") == "SYNTHETIC"
    digest = result.get("evidence_digest") or {}
    needs = result.get("data_needs") or []

    verdict = {
        "PASS": f"The change under review ({change}) clears the Oxy gate and can move to a governed draft package for human review.",
        "REVIEW_REQUIRED": f"The change under review ({change}) is plausible but must go to human review before any action.",
        "BLOCKED": f"The change under review ({change}) is blocked by an Oxy business rule and should not proceed as asked.",
        "DRAFT_ONLY": f"The change under review ({change}) can be documented as a draft only; it cannot enter the approval/submit path yet.",
    }.get(gate, "Gate result unavailable.")

    parts: List[str] = [
        "**Overview**",
        f"- {_question_opener(result)}"
        + (" Data is SYNTHETIC (demo); no real Oxy recommendation is implied." if synthetic else ""),
    ]

    # What the data shows: the evidence MAX ran + how it reads.
    parts += ["", "**What the data shows**"]
    for line in digest.get("lines", []):
        parts.append(f"- {line}")
    read = _classifier_read(result)
    if read:
        parts.append(f"- {read}")
    # The 'low finding rate is not waste' note - only when the read above did not already cover the mandate.
    if result.get("do_not_optimize") and result.get("classifier_label") != "Governance Review Required":
        parts.append("- This is a do-not-optimize (mandatory / criticality-mandated) PM; a low finding rate is not treated as waste.")

    # Not enough data to conclude: name the specific SAP data needed.
    if needs:
        parts += ["", "**Not enough data to conclude**",
                  "- MAX is not asserting an Effective/Ineffective score for this PM; it describes and flags what the data shows."]
        for n in needs:
            parts.append(f"- Needs {n['need']} - SAP source: {n['sap_source']}.")

    # Recommendation + the gate on the change under review.
    parts += ["", "**Recommendation**",
              f"- MAX recommends {rec_type} (gate {rec_gate}). {rationale}"]
    if diverges:
        parts.append(
            f"- Note: MAX recommends {rec_type}, not the change under review ({change}); the SAP package "
            f"drafts MAX's recommendation and is gate-checked separately."
        )
    parts.append(f"- Change under review: {verdict}" + (f" Reason: {reason}." if reason else ""))
    parts.append(f"- Next action: {next_action}. Required approvers: {', '.join(approvers) if approvers else 'none named yet'}.")
    parts.append("- Draft-only in Wave 1; humans approve; MDC/BPDO or the official Oxy process updates SAP.")
    return "\n".join(parts)
