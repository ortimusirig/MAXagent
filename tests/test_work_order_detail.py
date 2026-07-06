"""Level 2 - row-level work-order + notification detail records (the Artifacts detail tables).

The detail is deterministically EXPANDED from each asset's aggregates, so it reconciles to the Level-1
summary; it is retrieved scope-locked + row-capped on the in-scope path only (out-of-scope assets never
expose line items); and the honest blanks (absent labor actuals, uncoded notifications) are preserved -
the emptiness is the evidence signal.
"""

from __future__ import annotations

from max_agent.orchestrator import MaxAgent
from max_agent.synthetic_data import _notification_detail_records, _work_order_detail_records, fleet_index
from max_agent.ui.artifact_catalog import _notification_detail, _work_order_detail


def _pump4110():
    return MaxAgent().run("PUMP-4110")


def test_work_order_detail_reconciles_to_the_mix():
    r = _pump4110()
    wo = r["evidence"]["work_order_detail"]
    assert len(wo) == 14  # 10 + 3 + 1, the same total as the aggregate work-order mix
    by_type = {t: sum(1 for x in wo if x["order_type"] == t) for t in ("preventive", "corrective", "reactive")}
    assert by_type == {"preventive": 10, "corrective": 3, "reactive": 1}


def test_labor_actuals_are_honestly_blank():
    wo = _pump4110()["evidence"]["work_order_detail"]
    # SOAR posts no labor actuals -> the columns stay empty (the gap IS the signal, not a bug)
    assert all(row["actual_labor_hours"] is None for row in wo)
    assert all(row["labor_cost"] == 0.0 for row in wo)


def test_notification_detail_reconciles_to_coding_pct():
    r = _pump4110()
    nt = r["evidence"]["notification_detail"]
    assert len(nt) == 14
    damage = sum(1 for x in nt if x["damage_code"])
    cause = sum(1 for x in nt if x["cause_code"])
    # findings are 0.56 / 0.51 -> round(0.56*14)=8, round(0.51*14)=7 (the coding gap, per row)
    assert damage == 8 and cause == 7
    assert any(x["damage_code"] is None for x in nt)  # uncoded rows exist and stay blank


def test_detail_is_deterministic():
    a = fleet_index()["PUMP-4110"]
    assert _work_order_detail_records(a) == _work_order_detail_records(a)
    assert _notification_detail_records(a) == _notification_detail_records(a)


def test_out_of_scope_asset_exposes_no_detail():
    # Scope stays authoritative: the in-scope-only enrichment is skipped, so no line items leak.
    r = MaxAgent().run("PUMP-4130")  # non-operated / JV -> out of analysis scope
    assert r["scope"]["in_scope"] is False
    assert not (r.get("evidence") or {}).get("work_order_detail")
    assert not (r.get("evidence") or {}).get("notification_detail")
    # the renderer degrades gracefully rather than erroring
    assert "out of analysis scope" in str(_work_order_detail(r))


def test_row_cap_is_enforced():
    from max_agent.sql_templates import local_synthetic_executor
    ex = local_synthetic_executor(fleet_index())
    rows = ex("work_order_detail", {"equipment_id": "PUMP-4110", "time_window": "LAST_24_MONTHS", "row_cap": 5})
    assert len(rows) == 5  # capped at query time


def test_renderers_show_the_honesty_notes():
    r = _pump4110()
    assert "the empty column IS the evidence gap" in str(_work_order_detail(r))
    assert "coding gap" in str(_notification_detail(r))


def test_detail_tables_have_filter_inputs_and_download():
    s = str(_work_order_detail(_pump4110()))
    assert "detail-filter" in s and "detail-store" in s and "Download CSV" in s


def test_column_filter_is_case_insensitive_substring_and():
    from max_agent.ui.artifact_catalog import _filter_rows
    wo = _pump4110()["evidence"]["work_order_detail"]
    assert len(_filter_rows(wo, {"order_type": "CORRECTIVE"})) == 3   # case-insensitive
    assert len(_filter_rows(wo, {"order_type": "prev"})) == 10        # substring
    # AND across columns: corrective rows whose type also contains 'x' -> none
    assert len(_filter_rows(wo, {"order_type": "corrective", "status": "zzz"})) == 0
    assert len(_filter_rows(wo, {})) == len(wo)                       # no filter -> all rows


def test_csv_export_uses_labels_and_blanks_empty_cells():
    from max_agent.ui.artifact_catalog import _detail_csv
    wo = _pump4110()["evidence"]["work_order_detail"]
    csv = _detail_csv(["wo_number", "actual_labor_hours"], {"wo_number": "WO #", "actual_labor_hours": "Actual labor hrs"}, wo[:1])
    lines = csv.splitlines()
    assert lines[0] == "WO #,Actual labor hrs"          # human labels as header
    assert lines[1].endswith(",")                        # None -> empty cell (honest blank)
