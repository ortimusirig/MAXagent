"""Human-readable display labels for the internal governance codes (labels.py). Presentation only -
the codes stay the source of truth; these just rename them for the user-facing surfaces."""

from __future__ import annotations

from max_agent.labels import change_label, gate_label, rec_label, rec_meaning
from max_agent.orchestrator import MaxAgent


def test_known_codes_get_plain_labels():
    assert rec_label("IMPROVE_TASK_LIST") == "Improve the task list"
    assert "keep coverage" in rec_meaning("IMPROVE_TASK_LIST")
    assert gate_label("REVIEW_REQUIRED") == "Needs governance review"
    assert change_label("PM_FREQUENCY_CHANGE") == "PM frequency change"


def test_unknown_code_falls_back_gracefully():
    # a new/unmapped code degrades to Title Case, never raw ALL_CAPS
    assert rec_label("SOME_NEW_CODE") == "Some new code"
    assert rec_meaning("SOME_NEW_CODE") == ""       # no invented meaning for unknown codes


def test_every_recommendation_type_in_the_fleet_has_a_label_without_the_raw_code():
    a = MaxAgent()
    for eid in a._fleet_index:
        r = a.run(eid)
        code = r.get("recommendation_type")
        if code and code != "NONE":
            label = rec_label(code)
            assert label and label != code                 # a real rename happened
            assert code not in label                        # the ALL_CAPS token is gone from the label
