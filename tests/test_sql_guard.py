"""Generated-SQL safety guard (70/05): SELECT-only, view allowlist, scope-filter, fail-closed."""

from __future__ import annotations

from max_agent.tools.sql_guard import validate_generated_sql

_ALLOW = ["v_work_order_history", "oxy_pm.max.v_pm_plan_current"]
_SCOPE = {"equipment_id": "PUMP-4110", "time_window": "LAST_24_MONTHS"}


def _ok_sql():
    return "SELECT order_type, posting_date FROM v_work_order_history WHERE equipment_id = :equipment_id AND posting_date >= :time_window"


def test_clean_scoped_allowlisted_select_passes():
    v = validate_generated_sql(_ok_sql(), _ALLOW, _SCOPE)
    assert v["status"] == "PASSED"
    assert v["select_only"] and v["allowlisted"] and v["scope_filter_present"]
    assert v["referenced_relations"] == ["v_work_order_history"]


def test_catalog_qualified_view_matches_allowlist_by_leaf():
    sql = "SELECT * FROM oxy_pm.max.v_pm_plan_current WHERE equipment_id = :equipment_id AND created_on > :time_window"
    v = validate_generated_sql(sql, _ALLOW, _SCOPE)
    assert v["allowlisted"] is True
    assert v["status"] == "PASSED"


def test_delete_is_rejected():
    v = validate_generated_sql("DELETE FROM v_work_order_history WHERE equipment_id = :equipment_id", _ALLOW, _SCOPE)
    assert v["status"] == "REJECTED"
    assert any(r.startswith("BANNED_KEYWORD") for r in v["reasons"])


def test_update_is_rejected_but_update_time_column_is_ok():
    # `update_time` must NOT trip the UPDATE guard (word-boundary safety).
    ok = validate_generated_sql("SELECT update_time FROM v_work_order_history WHERE equipment_id = :equipment_id AND posting_date > :time_window", _ALLOW, _SCOPE)
    assert ok["select_only"] is True
    bad = validate_generated_sql("UPDATE v_work_order_history SET x = 1", _ALLOW, _SCOPE)
    assert bad["status"] == "REJECTED"


def test_multiple_statements_rejected():
    v = validate_generated_sql("SELECT 1 FROM v_work_order_history; DROP TABLE t", _ALLOW, _SCOPE)
    assert v["status"] == "REJECTED"
    assert "MULTIPLE_STATEMENTS" in v["reasons"]


def test_non_allowlisted_relation_is_not_passed():
    sql = "SELECT * FROM secret_table WHERE equipment_id = :equipment_id AND posting_date > :time_window"
    v = validate_generated_sql(sql, _ALLOW, _SCOPE)
    assert v["status"] == "WARN"  # readable SELECT but reads a disallowed relation -> not executed
    assert "secret_table" in v["disallowed_relations"]
    assert "RELATION_NOT_ALLOWLISTED" in v["reasons"]


def test_missing_scope_filter_is_not_passed():
    sql = "SELECT * FROM v_work_order_history"  # no equipment_id / time predicate
    v = validate_generated_sql(sql, _ALLOW, _SCOPE)
    assert v["status"] == "WARN"
    assert "SCOPE_FILTER_NOT_BOUND" in v["reasons"]


def test_column_present_but_not_value_bound_is_rejected():
    # The exact bypass the review found: columns appear but are NOT bound to PUMP-4110 / the window.
    sql = ("SELECT order_type FROM v_work_order_history "
           "WHERE equipment_id IS NOT NULL AND posting_date >= date_sub(current_date(), 30)")
    v = validate_generated_sql(sql, _ALLOW, _SCOPE)
    assert v["status"] != "PASSED"
    assert v["scope_filter_present"] is False
    assert "SCOPE_FILTER_NOT_BOUND" in v["reasons"]
    assert set(v.get("missing_scope_predicates", [])) == {"equipment_id", "time_window"}


def test_equality_to_wrong_value_is_not_bound():
    sql = ("SELECT order_type FROM v_work_order_history "
           "WHERE equipment_id = 'PUMP-9999' AND posting_date >= :time_window")
    v = validate_generated_sql(sql, _ALLOW, _SCOPE)  # scope asset is PUMP-4110
    assert v["status"] != "PASSED"
    assert "equipment_id" in v.get("missing_scope_predicates", [])


def test_banned_keyword_hidden_in_string_literal_does_not_trip():
    sql = "SELECT order_type FROM v_work_order_history WHERE equipment_id = :equipment_id AND note = 'please DELETE later' AND posting_date > :time_window"
    v = validate_generated_sql(sql, _ALLOW, _SCOPE)
    assert v["select_only"] is True
    assert v["status"] == "PASSED"


def test_empty_sql_is_rejected():
    v = validate_generated_sql("", _ALLOW, _SCOPE)
    assert v["status"] == "REJECTED"
    assert "NO_SQL" in v["reasons"]


def test_no_scope_predicates_is_not_passed():
    v = validate_generated_sql(_ok_sql(), _ALLOW, {})
    assert v["status"] != "PASSED"
    assert "NO_SCOPE_PREDICATES" in v["reasons"]
