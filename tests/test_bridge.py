"""The public bridge is the only game import the minds are allowed."""

from __future__ import annotations

import ast
from pathlib import Path

from open_late.ai_bridge import (
    LABOR_CAP,
    RENT_CAP,
    SALES_CAP,
    cap_mult,
    factor_key,
    market_table,
    starting_factors,
)
from open_late.corporate import MARKETS
from open_late.economy import SALES_CAP as ENGINE_SALES_CAP
from open_late.economy import _cap_mult, _key, _starting_values
from open_late.economy_e3 import LABOR_CAP as ENGINE_LABOR_CAP
from open_late.economy_e3 import RENT_CAP as ENGINE_RENT_CAP

ROOT = Path(__file__).resolve().parents[1]


def test_ai_imports_only_the_bridge():
    root = ROOT / "retail_rivals" / "open_late" / "ai"
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("open_late."):
                top = node.module.split(".")
                assert top[1] in {"ai", "ai_bridge"}, f"{path} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("open_late."):
                        top = alias.name.split(".")
                        assert top[1] in {"ai", "ai_bridge"}, f"{path} imports {alias.name}"


def test_bridge_matches_engine():
    assert SALES_CAP == ENGINE_SALES_CAP
    assert LABOR_CAP == ENGINE_LABOR_CAP
    assert RENT_CAP == ENGINE_RENT_CAP
    assert starting_factors() == _starting_values()
    for fid, city in ((14, "seattle"), (95, None), (17, "houston"), (1, None)):
        assert factor_key(fid, city) == _key(fid, city)
    assert cap_mult(112.0, RENT_CAP) == _cap_mult(112.0, RENT_CAP)
    table = market_table()
    for key, market in MARKETS.items():
        row = table[key]
        assert row.rent_weekly == market.rent_weekly
        assert row.build_cost == market.opening_cost
        assert row.min_cash_after == market.min_cash_after
        assert row.build_days == market.build_days
        assert row.sales_tax_bps == market.sales_tax_bps
