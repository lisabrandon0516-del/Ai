"""Section 4 acceptance. Gated rows run only with RR_LONG_TESTS=1."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.ai_acceptance import ai_off_signature, decision_signature

ROOT = Path(__file__).resolve().parents[1]
GOLDENS = ROOT / "tests" / "data" / "v4_goldens.json"

pytestmark_long = pytest.mark.skipif(os.environ.get("RR_LONG_TESTS") != "1", reason="set RR_LONG_TESTS=1")


def test_v4_goldens_are_recorded():
    assert GOLDENS.is_file()
    payload = json.loads(GOLDENS.read_text(encoding="utf-8"))
    assert payload["ai_off_26w"]
    assert len(payload["decision_8w"]) == 9


def test_ai_off_golden_holds():
    """A 26-week off run with no player opening matches the recorded golden."""
    payload = json.loads(GOLDENS.read_text(encoding="utf-8"))
    assert ai_off_signature() == payload["ai_off_26w"]


@pytest.mark.skipif(os.environ.get("RR_LONG_TESTS") != "1", reason="set RR_LONG_TESTS=1")
def test_gated_acceptance_rows():
    report = ROOT / "artifacts" / "acceptance.json"
    assert report.is_file(), "run tools/ai_acceptance.py --grid before the gated check"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["runs"]
    for row in payload["runs"]:
        assert row["reasons_ok"] is True
