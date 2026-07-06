"""Parts / BOM-completeness EVIDENCE (Wave-B extension, tool 28).

Grounds the Oxy "spares" ask the right way. In the Oxy documentation, "spare parts" is not a
Croston demand-forecasting problem - it is BOM COMPLETENESS: "add spares / components to the PM task
lists - most have none today" (SAP Components / v_bom). This tool reads THIS PM's linked components
and compares them to what LIKE equipment (same class) carry on their PM task lists, then flags the
components this asset is missing. A gap FEEDS the deterministic ``ADD_COMPONENT`` recommendation.

EVIDENCE-ONLY, like the reliability tools (25-27):

- It reports coverage and the missing-component list; it never changes the classifier label or the
  gate, and it emits no RAG colour and no Oxy policy threshold.
- ``min_prevalence`` is a STRUCTURAL majority parameter (a component most peers carry is the class
  "expected" set) - it is not an Oxy-defined value, so nothing is invented.
- Fails closed: with too few comparable peers it returns NOT_COMPARABLE + the SAP data still needed,
  never a fabricated gap.

Real cutover reads ``v_bom`` (Components: Material_Group / Object_Part / Cost_Element); the row shape
is identical, so nothing downstream changes.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from ..schemas import STATUS_SUCCESS, STATUS_WARNING, tool_envelope

# A class is comparable only with at least this many like-equipment peers that expose linked
# components; below it, the "expected" BOM cannot be established and the tool fails closed.
_MIN_COHORT = 3
# A component carried by at least this fraction of the cohort is part of the class "expected" BOM.
_MIN_PREVALENCE = 0.5


def _linked_codes(bom_rows: Optional[List[Dict[str, Any]]]) -> List[str]:
    """The component codes THIS PM task list actually links (on_pm_task_list truthy)."""
    return [str(r.get("component_code")) for r in (bom_rows or [])
            if r.get("component_code") and r.get("on_pm_task_list")]


def pm_bom_completeness(
    target_bom: Optional[List[Dict[str, Any]]],
    cohort_boms: Optional[List[Dict[str, Any]]],
    asset_class: Optional[str] = None,
    min_cohort: int = _MIN_COHORT,
    min_prevalence: float = _MIN_PREVALENCE,
) -> Dict[str, Any]:
    """Compare THIS PM's linked components against the like-equipment "expected" BOM.

    Args:
        target_bom: this asset's v_bom rows ({component_code, description, on_pm_task_list, ...}).
        cohort_boms: like-equipment rows [{equipment_id, linked: [component_code, ...]}].
        asset_class: for the interpretation text only.
    Returns the standard tool envelope; ``data`` carries the completeness status, the missing list,
    a coverage fraction, and ``component_gap`` (the boolean that feeds ADD_COMPONENT).
    """
    target_linked = sorted(set(_linked_codes(target_bom)))
    peers = [sorted(set(str(c) for c in (p.get("linked") or [])))
             for p in (cohort_boms or []) if p.get("linked") is not None]
    n_peers = len(peers)
    cls = asset_class or "like"

    # Fail closed: not enough comparable peers -> report own components + the data still needed.
    if n_peers < min_cohort:
        return tool_envelope(
            tool="pm_bom_completeness", status=STATUS_WARNING,
            summary=f"BOM completeness not comparable ({n_peers} like-equipment peers with components).",
            data={
                "computable": False, "bom_completeness": "NOT_COMPARABLE",
                "components_linked": target_linked, "components_expected": [], "components_missing": [],
                "coverage_pct": None, "component_gap": False, "cohort_size": n_peers,
                "min_prevalence": min_prevalence, "synthetic_flag": True,
                "data_needed": "linked components (BOM) on like equipment - SAP Components / v_bom",
                "sap_source": "v_bom (Components: Material_Group / Object_Part / Cost_Element)",
                "interpretation": (
                    f"Spare parts / BOM: too few comparable {cls} equipment expose linked components "
                    f"({n_peers} peers) to establish an expected BOM; reporting this PM's "
                    f"{len(target_linked)} linked components only. Source: v_bom (synthetic)."),
            },
            confidence="low",
        )

    counts = Counter()
    for s in peers:
        counts.update(s)
    threshold = min_prevalence * n_peers
    expected = sorted(code for code, k in counts.items() if k >= threshold)
    present = sorted(set(target_linked) & set(expected))
    missing = sorted(set(expected) - set(target_linked))
    coverage = round(len(present) / len(expected), 3) if expected else None
    # A gap only counts when the class actually has a non-trivial expected BOM (>= 2 components).
    component_gap = bool(missing) and len(expected) >= 2
    status_str = "COMPLETE" if not missing else "GAPS"

    if status_str == "COMPLETE":
        interp = (f"Spare parts / BOM: this PM links all {len(expected)} spare components that like {cls} "
                  f"equipment carry - no missing-component gap. Source: v_bom (synthetic).")
    else:
        interp = (f"Spare parts / BOM: this PM links {len(present)} of {len(expected)} spare components "
                  f"that most like {cls} equipment carry; missing {', '.join(missing)}. Adding them to the "
                  f"task list is a keep-coverage improvement (ADD_COMPONENT), gated for review. "
                  f"Source: v_bom (synthetic).")

    return tool_envelope(
        tool="pm_bom_completeness",
        status=STATUS_WARNING if component_gap else STATUS_SUCCESS,
        summary=f"BOM completeness {status_str}: {len(present)}/{len(expected)} expected components linked.",
        data={
            "computable": True, "bom_completeness": status_str,
            "components_linked": target_linked, "components_expected": expected,
            "components_missing": missing, "coverage_pct": coverage,
            "component_gap": component_gap, "cohort_size": n_peers,
            "min_prevalence": min_prevalence, "synthetic_flag": True,
            "sap_source": "v_bom (Components: Material_Group / Object_Part / Cost_Element)",
            "interpretation": interp,
        },
        confidence="medium",
    )
