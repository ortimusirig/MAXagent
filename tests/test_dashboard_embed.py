"""Tests for the AI/BI dashboard embed seam and the Lakeview dashboard asset."""

import json
import os

from dash import html

from max_agent.ui.dashboard_embed import render_aibi_dashboard

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LVDASH = os.path.join(ROOT, "dashboards", "pm_health.lvdash.json")


def _has_iframe(comp) -> bool:
    if isinstance(comp, html.Iframe):
        return True
    ch = getattr(comp, "children", None)
    if ch is None:
        return False
    if not isinstance(ch, (list, tuple)):
        ch = [ch]
    return any(_has_iframe(c) for c in ch)


def test_lvdash_json_is_valid_and_shaped():
    with open(LVDASH, encoding="utf-8") as f:
        d = json.load(f)
    names = {ds["name"] for ds in d["datasets"]}
    assert names == {"ds_pm_health", "ds_kpis"}
    layout = d["pages"][0]["layout"]
    assert len(layout) == 10  # 6 counters + 3 bars + 1 table
    # every widget query references a defined dataset (no dangling datasetName)
    for w in layout:
        for q in w["widget"]["queries"]:
            assert q["query"]["datasetName"] in names
    # the backing table name is consistent across both datasets
    joined = " ".join("".join(ds["queryLines"]) for ds in d["datasets"])
    assert "supplychain.max_agent.pm_health" in joined


def test_embed_renders_iframe_when_url_set(monkeypatch):
    monkeypatch.setenv("AIBI_DASHBOARD_EMBED_URL", "https://example.cloud.databricks.com/embed/dashboardsv3/abc123")
    out = render_aibi_dashboard(None)
    assert isinstance(out, html.Div)
    assert _has_iframe(out)


def test_fallback_has_no_iframe_when_url_unset(monkeypatch):
    monkeypatch.delenv("AIBI_DASHBOARD_EMBED_URL", raising=False)
    out = render_aibi_dashboard(None)
    assert isinstance(out, html.Div)
    assert not _has_iframe(out)
