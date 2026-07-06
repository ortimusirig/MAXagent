"""Human-readable display labels for the internal governance codes.

The deterministic tools emit typed enum CODES (recommendation_type, gate_status, change_under_review_
type, review triggers). Those codes are the source of truth for the logic and the tests - but a raw
`IMPROVE_TASK_LIST` on screen means nothing to a reviewer. This module maps each code to a plain-
language label (and a one-line "what it means to execute"), used ONLY at render/narration time. It
never changes a decision; it renames it. Unknown codes fall back to a Title Case of the token, so a
new code degrades gracefully instead of showing raw ALL_CAPS.

Governance: this is presentation only. The code stays the addressable value everywhere in the pipeline,
the gate, and the tests. `IMPROVE_TASK_LIST` is still `IMPROVE_TASK_LIST` in the result dict.
"""

from __future__ import annotations

from typing import Tuple

# recommendation_type -> (label, what it means to execute in the Studio)
RECOMMENDATION_LABELS = {
    "IMPROVE_TASK_LIST": ("Improve the task list",
                          "Sharpen what the PM inspects and how findings are coded - keep coverage, do not reduce it."),
    "TASK_LIST_CLEANUP": ("Clean up the task list",
                          "Remove redundant or duplicate steps and tighten the task list without reducing coverage."),
    "DATA_REMEDIATION": ("Remediate the data",
                         "Close the data gaps (coding, actuals) so the PM can be scored on the next cycle."),
    "DATA_CLEANUP": ("Clean up the data",
                     "Fix or complete the source records so future analysis is defensible."),
    "RETAIN_PM": ("Keep the current PM",
                  "No change - retain the PM as-is; it is performing acceptably on the evidence."),
    "KEEP_OR_INCREASE": ("Keep or increase coverage",
                         "Maintain (or strengthen) the current PM coverage; do not reduce it."),
    "SHORTEN_INTERVAL": ("Shorten the PM interval",
                         "Run the PM more often (a trial/step change, gate-checked and human-approved)."),
    "EXTEND": ("Extend the PM interval",
               "Run the PM less often - only if the evidence and the gate allow it."),
    "ADD_CBM": ("Add condition monitoring",
                "Introduce condition-based checks alongside the time-based PM (needs real readings first)."),
    "CONVERT_TO_CBM": ("Convert to condition-based",
                       "Move from a time-based PM to condition-based (blocked until real CBM readings exist)."),
    "MEASUREMENT_READINESS_FIRST": ("Establish CBM readings first",
                                    "Stand up the measurement points/readings before any CBM conversion can be considered."),
    "ADD_COMPONENT": ("Add a missing component",
                      "Complete the task list's material/BOM so the work can be planned and executed."),
    "REDUCE_OR_RETIRE_CANDIDATE": ("Candidate to reduce or retire",
                                   "Evidence suggests the PM may be reducible or retirable - routes to governance review, never automatic."),
    "REQUEST_CRITICALITY_VALIDATION": ("Validate criticality first",
                                       "Confirm the asset's criticality with Oxy before any strategy change is scoped."),
    "NONE": ("No change proposed",
             "Nothing to draft - typically an out-of-scope or unscorable asset."),
    "BU_DISCRETION": ("Business-unit discretion",
                      "No governed rule forces a change; the BU decides."),
}

# gate_status -> plain label
GATE_LABELS = {
    "PASS": "Cleared to draft",
    "REVIEW_REQUIRED": "Needs governance review",
    "BLOCKED": "Blocked",
    "DRAFT_ONLY": "Draft only",
}

# change_under_review_type -> plain label
CHANGE_LABELS = {
    "PM_FREQUENCY_CHANGE": "PM frequency change",
    "RETAIN_PM": "Keep the current PM",
    "TASK_LIST_CLEANUP": "Task-list cleanup",
    "CBM_CONVERSION": "CBM conversion",
    "RTF_CONVERSION": "Run-to-failure conversion",
    "REDUCE_PM": "Reduce PM coverage",
}


def _fallback(code: str) -> str:
    return (code or "").replace("_", " ").capitalize() or "-"


def rec_label(code: str) -> str:
    """Human label for a recommendation_type code (e.g. IMPROVE_TASK_LIST -> 'Improve the task list')."""
    return RECOMMENDATION_LABELS.get(code, (_fallback(code), ""))[0]


def rec_meaning(code: str) -> str:
    """One-line 'what it means to execute in the Studio' for a recommendation_type code."""
    return RECOMMENDATION_LABELS.get(code, ("", ""))[1]


def rec_label_with_code(code: str) -> str:
    """Label with the code in parentheses for the governance trace / audit views (keeps traceability)."""
    return f"{rec_label(code)} ({code})" if code else "-"


def gate_label(code: str) -> str:
    return GATE_LABELS.get(code, _fallback(code))


def change_label(code: str) -> str:
    return CHANGE_LABELS.get(code, _fallback(code))


def reason_label(code: str) -> str:
    """Plain label for gate reason / review-trigger codes."""
    return _fallback(code)
