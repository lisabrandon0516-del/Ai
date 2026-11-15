"""The books. Cash, inventory, tax, fixtures, and what the quarter actually earned."""

from __future__ import annotations

from open_late.finance import income_tax_due, pretax_profit
from open_late.models import GameState, LedgerLine, MonthClose
from open_late.text import money

SALES_TAX_PERCENT = 8
TERMS_RELATIONSHIP = 55


def tax_on(amount: int, state=None, store_id: str | None = None) -> int:
    """Sales tax on a sale or refund. Optional state applies 104; off stays identical."""
    if amount <= 0:
        return 0
    tax = (amount * SALES_TAX_PERCENT) // 100
    if state is None:
        return tax
    from open_late.economy import economy_difficulty

    if economy_difficulty(state) == "off":
        return tax
    # (amount * 8 * index) // 10000 equals (amount * 8) // 100 when index is 100.
    from open_late.economy_e4 import sales_tax_index

    index = sales_tax_index(state, store_id)
    return (amount * SALES_TAX_PERCENT * index) // 10000


def _stock_value(stock: dict, products: dict) -> int:
    total = 0
    for product_id, line in stock.items():
        product = products.get(product_id)
        if product is None:
            continue
        total += product.cost * line.on_hand
    return total


def inventory_on_hand(state: GameState) -> int:
    total = _stock_value(state.stock, state.products)
    for door in state.doors:
        total += _stock_value(door.stock, state.products)
    return total


def inventory_on_order(state: GameState) -> int:
    total = 0
    for product_id, line in state.stock.items():
        product = state.products.get(product_id)
        if product is None:
            continue
        total += product.cost * line.on_order
    return total


def fixtures_net(state: GameState) -> int:
    return max(0, state.fixtures - state.accumulated_depreciation)


def payables(state: GameState) -> int:
    return sum(account.payable for account in state.supplier_accounts)


def assets(state: GameState) -> int:
    return state.cash + inventory_on_hand(state) + inventory_on_order(state) + fixtures_net(state)


def liabilities(state: GameState) -> int:
    return state.credit_used + state.tax_held + payables(state)


def equity(state: GameState) -> int:
    return assets(state) - liabilities(state)


def hours_open(state: GameState) -> int:
    return max(0, state.close_hour - state.open_hour)


def gross_margin(sales: int, refunds: int, cogs: int) -> int | None:
    net = sales - refunds
    if net <= 0:
        return None
    return int(round(100 * (net - cogs) / net))


def runway_days(state: GameState) -> int:
    from open_late.finance import weekly_obligations

    daily = max(1, weekly_obligations(state) // 7)
    return state.cash // daily


def post(state: GameState, kind: str, amount: int, note: str) -> None:
    state.ledger.append(LedgerLine(day=state.day, kind=kind, amount=amount, note=note))
    if len(state.ledger) > 160:
        state.ledger = state.ledger[-160:]


def quarter_net(state: GameState) -> int:
    return pretax_profit(state) - income_tax_due(state)


def close_quarter(state: GameState, note: str) -> MonthClose:
    statement = MonthClose(
        day=state.day,
        sales=state.quarter_sales,
        cogs=state.quarter_cogs,
        refunds=state.quarter_refunds,
        gross_profit=state.quarter_sales - state.quarter_refunds - state.quarter_cogs,
        operating=state.quarter_opex,
        tax=state.quarter_tax,
        depreciation=state.quarter_depreciation,
        income_tax=income_tax_due(state),
        net=quarter_net(state),
        cash=state.cash,
        inventory=inventory_on_hand(state),
        note=note,
    )
    state.months.append(statement)
    state.months = state.months[-12:]
    state.quarter_sales = 0
    state.quarter_cogs = 0
    state.quarter_refunds = 0
    state.quarter_opex = 0
    state.quarter_tax = 0
    state.quarter_depreciation = 0
    return statement


def income_lines(state: GameState) -> list[tuple[str, int]]:
    gross = state.quarter_sales - state.quarter_refunds - state.quarter_cogs
    return [
        ("Sales", state.quarter_sales),
        ("Refunds", -state.quarter_refunds),
        ("Cost of goods sold", -state.quarter_cogs),
        ("Gross profit", gross),
        ("Operating costs", -state.quarter_opex),
        ("Depreciation", -state.quarter_depreciation),
        ("Income tax, 21%", -income_tax_due(state)),
        ("Quarter net", quarter_net(state)),
    ]


def balance_lines(state: GameState) -> list[tuple[str, int]]:
    return [
        ("Cash", state.cash),
        ("Inventory", inventory_on_hand(state)),
        ("Prepaid orders", inventory_on_order(state)),
        ("Fixtures, net", fixtures_net(state)),
        ("Assets", assets(state)),
        ("Credit line", state.credit_used),
        ("Sales tax held", state.tax_held),
        ("Accounts payable", payables(state)),
        ("Liabilities", liabilities(state)),
        ("Equity", equity(state)),
    ]


def oldest_stock(state: GameState, limit: int = 6) -> list[tuple[str, int, int, int]]:
    rows = []
    for product_id, line in state.stock.items():
        if line.on_hand <= 0:
            continue
        product = state.products[product_id]
        rows.append((product.name, line.on_hand, line.age_days, product.cost * line.on_hand))
    rows.sort(key=lambda row: row[2], reverse=True)
    return rows[:limit]


def format_margin(sales: int, refunds: int, cogs: int) -> str:
    margin = gross_margin(sales, refunds, cogs)
    if margin is None:
        return "no sales yet"
    return f"{margin}%"


def describe_runway(state: GameState) -> str:
    days = runway_days(state)
    return f"About {days} days of Sunday bills sit in the drawer ({money(state.cash)})."
