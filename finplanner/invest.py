"""Growth projections, loan-vs-invest, distribution matrix (SPEC §4.8).

VOLATILITY CAVEAT (PROCESS_LOG decision 3): every comparison that leans on an assumed market
return ALSO returns the caveat that the return is uncertain and can be negative. The "lean
invest" verdict is an expected-value statement, not a recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .loan import amortize

VOLATILITY_CAVEAT = (
    "Market returns are assumed and volatile — they can be negative in any given period. "
    "Debt paydown is a guaranteed return equal to the loan APR. This is an expected-value "
    "comparison, not a recommendation."
)


def grow(principal: float, monthly_contrib: float, annual_rate_percent: float, years: int) -> float:
    """Month-by-month compounding of a starting principal plus a monthly contribution."""
    rate = annual_rate_percent / 100.0 / 12.0
    bal = principal
    for _ in range(years * 12):
        bal = bal * (1 + rate) + monthly_contrib
    return bal


@dataclass
class LoanVsInvest:
    extra_monthly: float
    years: int
    interest_saved_by_paying: float  # guaranteed
    expected_investment_value: float  # assumed/volatile
    lean: str  # "pay_loan" | "invest"
    caveat: str


def loan_vs_invest(
    balance: float,
    apr_percent: float,
    base_payment: float,
    extra_monthly: float,
    invest_return_annual_percent: float,
    years: int,
) -> LoanVsInvest:
    """Compare paying `extra_monthly` toward the loan vs investing the same dollars."""
    base = amortize(balance, apr_percent, base_payment)
    faster = amortize(balance, apr_percent, base_payment + extra_monthly)
    base_int = base.total_interest if not base.never_amortizes else float("inf")
    faster_int = faster.total_interest if not faster.never_amortizes else float("inf")
    interest_saved = base_int - faster_int

    expected_value = grow(0.0, extra_monthly, invest_return_annual_percent, years)

    lean = "invest" if expected_value > interest_saved else "pay_loan"
    return LoanVsInvest(
        extra_monthly=extra_monthly,
        years=years,
        interest_saved_by_paying=interest_saved,
        expected_investment_value=expected_value,
        lean=lean,
        caveat=VOLATILITY_CAVEAT,
    )


@dataclass
class MatrixCell:
    loan_payment: float
    monthly_invest: float
    loan_total_interest: float
    loan_months: int | None
    invest_5yr: float
    invest_30yr: float


def distribution_matrix(
    balance: float,
    apr_percent: float,
    loan_payments: list[float],
    invest_amounts: list[float],
    invest_return_annual_percent: float,
) -> list[MatrixCell]:
    """Grid over {loan payment levels} × {monthly invest amounts} -> 5yr/30yr balances + interest."""
    cells: list[MatrixCell] = []
    for lp in loan_payments:
        amort = amortize(balance, apr_percent, lp)
        for inv in invest_amounts:
            cells.append(MatrixCell(
                loan_payment=lp,
                monthly_invest=inv,
                loan_total_interest=amort.total_interest,
                loan_months=amort.months_to_payoff,
                invest_5yr=grow(0.0, inv, invest_return_annual_percent, 5),
                invest_30yr=grow(0.0, inv, invest_return_annual_percent, 30),
            ))
    return cells
