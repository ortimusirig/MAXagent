"""BU profile loading.

The BU profile is *rule data, not code* (see 04 / 08). ``validate_scope``, ``oxy_gate_check``,
``pm_effectiveness_classifier``, and ``approval_workflow_state`` resolve the active profile
from context before making scope, gate, classifier, or approval decisions.

Ship one ``default_oxy`` profile. Other BUs are additional profiles that inherit from the
default anchor and declare explicit deltas (anchor-plus-delta) - never fork tool logic per BU.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict

import yaml

_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "config", "bu_profiles")

_CACHE: Dict[str, Dict[str, Any]] = {}


def profile_path(profile_id: str) -> str:
    return os.path.join(_PROFILE_DIR, f"{profile_id}.yaml")


def load_bu_profile(profile_id: str = "default_oxy") -> Dict[str, Any]:
    """Load a BU profile by id from ``max_agent/config/bu_profiles/<id>.yaml``.

    Returns a deep copy so callers can never mutate the cached profile in place.
    """
    if profile_id not in _CACHE:
        path = profile_path(profile_id)
        if not os.path.exists(path):
            raise FileNotFoundError(f"BU profile not found: {profile_id} ({path})")
        with open(path, "r", encoding="utf-8") as fh:
            _CACHE[profile_id] = yaml.safe_load(fh) or {}
    return copy.deepcopy(_CACHE[profile_id])


def classifier_thresholds_are_set(bu_profile: Dict[str, Any]) -> bool:
    """True only when Oxy has confirmed the classifier numeric cut-offs.

    Until then the classifier operates in describe-and-flag mode and must not assert
    ``Effective`` / ``Ineffective`` (see 09). A threshold block counts as "set" only if the
    status no longer reads BU_DEFINED and every numeric cut-off the label needs is non-null.
    """
    thresholds = bu_profile.get("classifier_thresholds") or {}
    status = str(thresholds.get("status", "")).upper()
    if "BU_DEFINED" in status or status in ("", "UNSET", "NULL"):
        return False
    # Any null numeric cut-off means we cannot pass final judgment on that dimension.
    numeric_keys = [
        "failure_after_pm_rate_max",
        "mtbf_improvement_min",
        "repeat_failure_rate_max",
        "finding_rate_effective_min",
        "finding_rate_low_floor",
        "planned_vs_actual_variance_max",
    ]
    return all(thresholds.get(k) is not None for k in numeric_keys)
