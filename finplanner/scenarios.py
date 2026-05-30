"""Narrative if-this-then-that comparisons (SPEC §4 / PROCESS_LOG v8).

Composes tax / loan / invest into structured text. Preserves the two non-negotiable reframes:

  - MAXIMIZE TAKE-HOME, never "zero out tax" (decision 2). Bringing income tax to $0 means
    spending ~$1 to save ~30–40¢ — a net loss. We never present a spend-to-zero target as advice.
  - LOAN-VS-INVEST is expected-value, with the volatility caveat always attached (decision 3).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import PlannerConfig
from .invest import VOLATILITY_CAVEAT, grow, loan_vs_invest
from .rates import rates_for
from .summary import tax_inputs_from_config
from .tax import TaxInputs, compute_tax


@dataclass
class Scenario:
    title: str
    body: str
    caveat: str = ""


def pay_loan_vs_invest_scenario(cfg: PlannerConfig, extra_monthly: float = 400, years: int = 10) -> Scenario:
    sl = cfg.debt.student_loan
    cmp = loan_vs_invest(
        sl.balance, sl.apr_percent, sl.monthly_payment, extra_monthly,
        cfg.assumptions.investment_return_annual_percent, years,
    )
    lean_txt = ("leans toward investing" if cmp.lean == "invest"
                else "leans toward paying the loan down faster")
    body = (
        f"Putting an extra ${extra_monthly:,.0f}/mo toward the {sl.apr_percent:.1f}% student loan "
        f"would save ~${cmp.interest_saved_by_paying:,.0f} in guaranteed interest. Investing the "
        f"same ${extra_monthly:,.0f}/mo for {years} years at an assumed "
        f"{cfg.assumptions.investment_return_annual_percent:.1f}% would grow to "
        f"~${cmp.expected_investment_value:,.0f}. On expected value this {lean_txt}."
    )
    return Scenario("Pay loan vs. invest", body, caveat=cmp.caveat)


def maximize_take_home_scenario(cfg: PlannerConfig) -> Scenario:
    """Honest framing: more deductible spending lowers tax but lowers take-home (decision 2)."""
    r = rates_for(cfg.meta.tax_year)
    inp = tax_inputs_from_config(cfg, taxable_interest=0.0)
    base_tax = compute_tax(inp, r).total_tax.value

    bump = 10_000  # extra deductible business spend
    bumped = TaxInputs(**{**inp.__dict__, "bizexp_annual": inp.bizexp_annual + bump})
    bumped_tax = compute_tax(bumped, r).total_tax.value
    tax_saved = base_tax - bumped_tax

    body = (
        f"Spending an extra ${bump:,.0f} on deductible business expenses would lower total tax by "
        f"only ~${tax_saved:,.0f} — you spend ${bump:,.0f} to save ${tax_saved:,.0f}, a net "
        f"reduction in take-home of ~${bump - tax_saved:,.0f}. Chasing a $0 tax bill is a losing "
        f"trade. The right goal is MAXIMUM TAKE-HOME CASH, with tax as one input — only spend on "
        f"things you'd buy anyway."
    )
    return Scenario("Maximize take-home (not zero-out tax)", body)


def long_run_growth_scenario(cfg: PlannerConfig, monthly: float = 500) -> Scenario:
    rate = cfg.assumptions.investment_return_annual_percent
    body = (
        f"Investing ${monthly:,.0f}/mo at an assumed {rate:.1f}%: "
        f"~${grow(0, monthly, rate, 5):,.0f} in 5 years, "
        f"~${grow(0, monthly, rate, 10):,.0f} in 10 years, "
        f"~${grow(0, monthly, rate, 30):,.0f} in 30 years."
    )
    return Scenario("Long-run growth", body, caveat=VOLATILITY_CAVEAT)


def all_scenarios(cfg: PlannerConfig) -> list[Scenario]:
    return [
        maximize_take_home_scenario(cfg),
        pay_loan_vs_invest_scenario(cfg),
        long_run_growth_scenario(cfg),
    ]
