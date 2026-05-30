"""Loan amortization + optimal-payment solver (SPEC §4.7).

"Optimal" is defined explicitly and user-facing: it depends on the assumed investment return
vs the loan APR (a guaranteed return). The reasoning is returned alongside the number so the
user sees WHY, not just a figure. The investment side is uncertain — see invest.loan_vs_invest.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AmortResult:
    months_to_payoff: int | None  # None == "never amortizes"
    total_interest: float
    total_paid: float
    schedule: list[dict]  # per-month {month, interest, principal, balance}
    never_amortizes: bool


def amortize(balance: float, apr_percent: float, monthly_payment: float, cap_months: int = 1200) -> AmortResult:
    """Standard amortization loop. If payment <= first month's interest, never amortizes."""
    apr = apr_percent / 100.0
    monthly_rate = apr / 12.0
    first_interest = balance * monthly_rate
    if monthly_payment <= first_interest and balance > 0:
        return AmortResult(None, float("inf"), float("inf"), [], never_amortizes=True)

    bal = balance
    total_interest = 0.0
    sched = []
    m = 0
    while bal > 0 and m < cap_months:
        m += 1
        interest = bal * monthly_rate
        pay = min(monthly_payment, bal + interest)
        principal = pay - interest
        bal = bal + interest - pay
        total_interest += interest
        sched.append({"month": m, "interest": interest, "principal": principal, "balance": max(0.0, bal)})

    return AmortResult(
        months_to_payoff=m,
        total_interest=total_interest,
        total_paid=balance + total_interest,
        schedule=sched,
        never_amortizes=False,
    )


@dataclass
class OptimalPayment:
    payment: float
    reasoning: str
    months_to_payoff: int | None
    total_interest: float


def optimal_payment(
    balance: float,
    apr_percent: float,
    invest_return_annual_percent: float,
    min_payment: float,
    max_affordable_payment: float,
) -> OptimalPayment:
    """If expected investment return > loan APR, pay the minimum (invest the rest).
    If APR > expected return, pay as much as the emergency buffer allows.

    This is an expected-value framing, NOT a recommendation — the investment return is
    assumed and volatile (PROCESS_LOG decision 3).
    """
    if invest_return_annual_percent > apr_percent:
        payment = max(min_payment, balance * (apr_percent / 100.0) / 12.0 + 0.01)
        amort = amortize(balance, apr_percent, payment)
        reasoning = (
            f"Assumed investment return ({invest_return_annual_percent:.1f}%) exceeds the loan "
            f"APR ({apr_percent:.1f}%), so on an expected-value basis the minimum viable payment "
            f"frees the most cash to invest. NOTE: investment returns are uncertain and can be "
            f"negative; debt paydown is a guaranteed {apr_percent:.1f}% return."
        )
    else:
        payment = max_affordable_payment
        amort = amortize(balance, apr_percent, payment)
        reasoning = (
            f"Loan APR ({apr_percent:.1f}%) meets or exceeds the assumed investment return "
            f"({invest_return_annual_percent:.1f}%), so paying down debt is the better guaranteed "
            f"return. Pay as much as the {min_payment:,.0f}+ buffer allows ({payment:,.0f}/mo)."
        )
    return OptimalPayment(
        payment=payment,
        reasoning=reasoning,
        months_to_payoff=amort.months_to_payoff,
        total_interest=amort.total_interest,
    )
