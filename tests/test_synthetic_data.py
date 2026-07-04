"""Sanity checks on the synthetic fleet (manufactured, clearly flagged)."""

from max_agent.synthetic_data import synthetic_fleet


def test_all_rotating_and_synthetic():
    for a in synthetic_fleet():
        assert a["equipment_category"] == "R"  # rotating-only, matches SOAR sample shape
        assert a["master_data"]["synthetic_data_flag"] is True


def test_covers_all_gate_statuses():
    expected = {a["expected_gate_status"] for a in synthetic_fleet()}
    assert {"PASS", "REVIEW_REQUIRED", "BLOCKED", "DRAFT_ONLY"}.issubset(expected)


def test_unique_ids():
    ids = [a["equipment_id"] for a in synthetic_fleet()]
    assert len(ids) == len(set(ids))


def test_no_labor_cost_claimed():
    # SOAR reality: labor cost is 0; synthetic mirrors that so no labor-savings claim is possible.
    for a in synthetic_fleet():
        assert a["cost"]["labor_cost"] == 0.0
