"""Two books: the shop revolver, and one loan per building."""

from __future__ import annotations

from open_late.ai.constants import BUILD_TERM_WEEKS, BUILD_WEEKLY_RATE
from open_late.ai.models import BuildLoan, RivalChain
from open_late.ai_bridge import shop_weekly_rate


def loan_service(loan: BuildLoan) -> tuple[int, int]:
    """Interest and level principal due this week."""
    if loan.principal <= 0:
        return 0, 0
    interest = int(round(loan.principal * loan.rate_bps / 10_000 / 52))
    step = max(1, loan.original // max(1, loan.term_weeks))
    principal = min(loan.principal, step)
    return interest, principal


def weekly_debt_service(
    chain: RivalChain,
    *,
    extra_loan: int = 0,
    extra_revolver: int = 0,
) -> int:
    """Cash that leaves for interest and build principal this week."""
    revolver = max(0, chain.revolver_debt + extra_revolver)
    cost = int(round(revolver * shop_weekly_rate()))
    for loan in chain.build_loans:
        interest, principal = loan_service(loan)
        cost += interest + principal
    if extra_loan > 0:
        interest = int(round(extra_loan * BUILD_WEEKLY_RATE))
        principal = max(1, extra_loan // BUILD_TERM_WEEKS)
        cost += interest + principal
    return cost


def apply_debt_service(chain: RivalChain) -> int:
    """Charge the week and shrink the build loans. Returns the cash taken."""
    taken = int(round(max(0, chain.revolver_debt) * shop_weekly_rate()))
    for loan in chain.build_loans:
        interest, principal = loan_service(loan)
        loan.principal -= principal
        taken += interest + principal
    chain.build_loans = [loan for loan in chain.build_loans if loan.principal > 0]
    chain.cash -= taken
    chain.refresh_debt()
    return taken


def trailing_ebitda(chain: RivalChain) -> int:
    """Yearly operating profit from the last quarter of real books.

    The opening weeks stay in the history, but they are not the run-rate a
    healthy chain is borrowing against once a quarter has been earned.
    """
    trail = [int(value) for value in chain.ebitda_trail if value is not None]
    if not trail:
        return max(0, chain.last_pnl.net) * 52
    window = trail[-13:]
    return int(sum(window) * 52 / len(window))
