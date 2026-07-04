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
        f"Classifier label: {d.get('classifier_label')} (provenance {d.get('provenance')}).",
        f"MAX recommendation: {d.get('recommendation_type')} - {d.get('recommendation_rationale')}.",
        f"Change under consideration: {d.get('proposed_summary')}.",
        f"Gate status: {d.get('gate_status')}; reason: {d.get('gate_reason')}.",
        f"Required approvers: {', '.join(d.get('required_approvers') or []) or 'none'}.",
        f"Do-not-optimize: {d.get('do_not_optimize')}.",
        "Explain this result. Draft-only in Wave 1; humans approve; MDC/BPDO or the official Oxy "
        "process updates SAP.",
    ]
    return "\n".join(lines)


def deterministic_summary(result: Dict[str, Any]) -> str:
    """Plain-language summary built directly from the deterministic tool results."""
    gate = result.get("gate_status")
    reason = result.get("gate_reason")
    label = result.get("classifier_label")
    rec_type = result.get("recommendation_type")
    rationale = result.get("recommendation_rationale")
    approvers = result.get("required_approvers") or []
    synthetic = result.get("provenance") == "SYNTHETIC"

    verdict = {
        "PASS": "This change has enough evidence, data readiness, and risk support to move to a governed draft package for human review.",
        "REVIEW_REQUIRED": "This change is plausible but must go to human review before any action.",
        "BLOCKED": "This change is blocked by an Oxy business rule and should not proceed as asked.",
        "DRAFT_ONLY": "This can be documented as a draft only; it cannot enter the approval/submit path yet.",
    }.get(gate, "Gate result unavailable.")

    parts = [
        "Overview",
        f"- Asset {result.get('equipment_id')} ({result.get('asset_class')}). "
        + ("Data is SYNTHETIC (demo); no real Oxy recommendation is implied. " if synthetic else ""),
        f"- Effectiveness label: {label}."
        + (" Thresholds are not yet set by Oxy, so MAX describes and flags rather than scoring." if label == "Missing Evidence" else "")
        + (" This is a do-not-optimize (mandatory / criticality-mandated) PM." if result.get("do_not_optimize") else ""),
        "",
        "Key Findings",
        f"- Gate status: {gate} ({reason}). {verdict}",
        f"- Required approvers: {', '.join(approvers) if approvers else 'none named yet'}.",
        "",
        "Recommendation",
        f"- MAX proposes: {rec_type}. {rationale}",
        "- MAX drafts governed recommendations; humans approve; MDC/BPDO or the official Oxy process updates SAP. No direct SAP write-back in Wave 1.",
    ]
    return "\n".join(parts)
