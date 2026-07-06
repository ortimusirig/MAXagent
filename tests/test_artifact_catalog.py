"""Model-selected artifact catalog (ui/artifact_catalog.py): the Artifacts tab renders exactly the
artifacts the model chose, with a deterministic default set as the fail-closed floor."""

from __future__ import annotations

from max_agent.entities import ARTIFACT_CHOICES
from max_agent.orchestrator import MaxAgent
from max_agent.ui.artifact_catalog import default_artifacts, render_artifacts


def _result():
    return MaxAgent().run("PUMP-4102")


def test_catalog_and_renderers_in_lockstep():
    # importing the module runs the assert; this makes the invariant explicit for the reader
    from max_agent.ui import artifact_catalog
    assert set(artifact_catalog._RENDERERS) == set(ARTIFACT_CHOICES)


def test_default_floor_when_nothing_selected():
    r = _result()
    out = render_artifacts(r, None)
    assert len(out.children) == len(default_artifacts(r))  # falls back to the deterministic set


def test_renders_only_selected():
    r = _result()
    assert len(render_artifacts(r, ["cost"]).children) == 1
    assert len(render_artifacts(r, ["comparison", "cost"]).children) == 2


def test_invalid_selection_falls_back_to_default():
    r = _result()
    out = render_artifacts(r, ["not_a_real_artifact"])
    assert len(out.children) == len(default_artifacts(r))
