"""Narration prompts and a deterministic fallback summary.

The LLM (when a serving endpoint is bound) EXPLAINS the deterministic result in plain language.
It must never invent or override a gate status, a classifier label, or an Oxy value. When no LLM
endpoint is bound, `deterministic_summary` produces the same shape from the tool results directly,
so the app always has a chat answer.
"""

from __future__ import annotations

from typing import Any, Dict

NARRATION_SYSTEM = (
    "You are MAX, a governed preventive-maintenance strategy copilot for Oxy. Explain the "
    "DETERMINISTIC result you are given in plain language for a planner or reliability engineer. "
    "You must NOT change the classifier label, the gate status, the required approvers, or any Oxy "
    "value; only explain them. Never claim realized savings, real CBM readiness, or a direct SAP "
    "write-back. If a value is unknown/fail-closed, say so. Keep it to Overview, Key Findings, and "
    "Recommendation, each brief."
)


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
        "Answer the user's question directly using ONLY these facts. Do not contradict the gate or the "
        "label. Draft-only in Wave 1; humans approve; MDC/BPDO or the official Oxy process updates SAP.",
    ]
    return "\n".join(lines)


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


def deterministic_summary(result: Dict[str, Any]) -> str:
    """Plain-language, question-aware summary built directly from the deterministic tool results.

    Coherent by construction: the gate verdict is about the CHANGE UNDER REVIEW, and MAX's
    recommendation (with its own gate outcome) is stated separately - so a Missing-Evidence PM never
    reads as 'enough evidence'.
    """
    gate = result.get("gate_status")
    reason = result.get("gate_reason")
    label = result.get("classifier_label")
    change = result.get("change_under_review_type")
    rec_type = result.get("recommendation_type")
    rec_gate = result.get("recommendation_gate_status")
    rationale = result.get("recommendation_rationale")
    next_action = result.get("recommendation_next_action")
    diverges = result.get("recommendation_diverges")
    approvers = result.get("required_approvers") or []
    synthetic = result.get("provenance") == "SYNTHETIC"
    readiness = result.get("data_readiness_rag")

    verdict = {
        "PASS": f"The change under review ({change}) clears the Oxy gate and can move to a governed draft package for human review.",
        "REVIEW_REQUIRED": f"The change under review ({change}) is plausible but must go to human review before any action.",
        "BLOCKED": f"The change under review ({change}) is blocked by an Oxy business rule and should not proceed as asked.",
        "DRAFT_ONLY": f"The change under review ({change}) can be documented as a draft only; it cannot enter the approval/submit path yet.",
    }.get(gate, "Gate result unavailable.")

    parts = [
        "Overview",
        f"- {_question_opener(result)}"
        + (" Data is SYNTHETIC (demo); no real Oxy recommendation is implied." if synthetic else ""),
        f"- Effectiveness label: {label} (data readiness {readiness})."
        + (" Thresholds are not set by Oxy, so MAX describes and flags rather than scoring." if label == "Missing Evidence" else "")
        + (" This is a do-not-optimize (mandatory / criticality-mandated) PM." if result.get("do_not_optimize") else ""),
        "",
        "Key Findings",
        f"- {verdict}" + (f" Reason: {reason}." if reason else ""),
        f"- MAX recommendation: {rec_type} (gate {rec_gate}). {rationale}",
    ]
    if diverges:
        parts.append(
            f"- Note: MAX recommends {rec_type}, not the change under review ({change}); the SAP package "
            f"drafts the change under review and the recommendation is gate-checked separately."
        )
    parts += [
        f"- Required approvers: {', '.join(approvers) if approvers else 'none named yet'}.",
        "",
        "Recommendation",
        f"- Next action: {next_action}.",
        "- MAX drafts governed recommendations; humans approve; MDC/BPDO or the official Oxy process updates SAP. No direct SAP write-back in Wave 1.",
    ]
    return "\n".join(parts)
