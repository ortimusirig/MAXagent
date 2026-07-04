"""Light unit tests for resolve_context (context locking)."""

from max_agent.tools.context import resolve_context


def test_resolve_context_locks_fields():
    result = resolve_context(equipment_id="PUMP-1", plant="HOUSTON", bu_profile_id="default_oxy")
    ctx = result["data"]["context"]
    assert ctx["equipment_id"] == "PUMP-1"
    assert ctx["plant"] == "HOUSTON"
    assert ctx["bu_profile_id"] == "default_oxy"
    assert ctx["time_window"] == "LAST_24_MONTHS"  # default window
    assert result["scope_validated"] is True


def test_resolve_context_defaults_bu_profile():
    result = resolve_context(equipment_id="PUMP-2")
    assert result["data"]["context"]["bu_profile_id"] == "default_oxy"
