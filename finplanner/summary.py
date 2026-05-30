"""Consolidated metric rollup (SPEC §1C wishlist + §6 acceptance criterion 5).

One place that lists: total monthly expenses, HYSA/Roth/SEP/ETF balances & contributions,
total taxable income 2026, total tax due April 2027, set-aside, and runway runout.

Composes tax + runway + severance + eligibility — the single source of truth so views don't
recompute (SPEC §1A).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .config import PlannerConfig
from .eligibility import Warning_, qbi_sstb, roth_limit, sep_limit
from .rates import rates_for
from .runway import Ledger, build_ledger
from .severance import estimate_set_aside
from .tax import TaxInputs, TaxResult, compute_tax
from .trace import Traced


def tax_inputs_from_config(cfg: PlannerConfig, taxable_interest: float) -> TaxInputs:
    """Map PlannerConfig + modeled HYSA interest into TaxInputs (single source of truth)."""
    sev = cfg.severance.total_pretax
    return TaxInputs(
        w2_wages=cfg.income.w2_earned_ytd_2026,
        severance_wages=sev / 3.0,  # installment 1 = W-2 wages
        severance_damages=2.0 * sev / 3.0,  # installments 2 & 3 = damages
        freelance_taxable_annual=cfg.freelance_taxable_annual,
        bizexp_annual=cfg.bizexp_annual,
        taxable_interest=taxable_interest,
        sep_contrib=cfg.retirement_and_investing.sep_ira_annual_pretax,
        roth_contrib=cfg.retirement_and_investing.roth_ira_annual_posttax,
        business_is_sstb=cfg.retirement_and_investing.business_is_sstb,
    )


@dataclass
class Summary:
    total_monthly_expenses: float
    annual_expenses: float
    hysa_apy: float
    hysa_ending_balance: float
    roth_contribution: float
    sep_contribution: float
    etf_contribution: float
    total_taxable_income_2026: float
    total_tax_due: float
    ubt: float
    severance_withheld: float
    balance_due_or_refund: float
    set_aside: float
    cash_runs_out_month: int | None
    ending_cash_balance: float
    tax: TaxResult
    ledger: Ledger
    warnings: list[Warning_] = field(default_factory=list)
    traces: dict[str, Traced] = field(default_factory=dict)
    tax_due_date: str = "2027-04-15"


def build_summary(cfg: PlannerConfig, months: int = 12, start_date: date | None = None) -> Summary:
    r = rates_for(cfg.meta.tax_year)
    ledger = build_ledger(cfg, months=months, start_date=start_date)
    inp = tax_inputs_from_config(cfg, ledger.taxable_interest_annual)
    tax = compute_tax(inp, r)
    set_aside = estimate_set_aside(inp, r)

    total_monthly = (
        cfg.expenses.rent_monthly
        + cfg.expenses.other_monthly
        + cfg.debt.student_loan.monthly_payment
        + cfg.expenses.business_expense_monthly_deductible
        + cfg.card_annual_fee / 12.0
    )

    # taxable income 2026 = ordinary + business result + taxable interest (under-the-table EXCLUDED).
    # A business loss reduces this (capped by §461(l)), consistent with AGI.
    business_for_income = max(inp.business_net, -r.ebl_cap_single)
    taxable_income = (
        inp.w2_wages + inp.severance_total + business_for_income + inp.taxable_interest
    )

    traces: dict[str, Traced] = {
        "monthly_expenses": Traced(
            value=total_monthly,
            label="Total monthly expenses",
            formula="rent + other + loan + bizexp + card_fee_monthly",
            inputs={
                "rent": cfg.expenses.rent_monthly, "other": cfg.expenses.other_monthly,
                "loan": cfg.debt.student_loan.monthly_payment,
                "bizexp": cfg.expenses.business_expense_monthly_deductible,
                "card_fee_monthly": cfg.card_annual_fee / 12.0,
            },
        ),
        "taxable_income_2026": Traced(
            value=taxable_income,
            label="Taxable income 2026",
            formula="w2 + severance_total + business_net + taxable_interest",
            inputs={
                "w2": inp.w2_wages, "severance_total": inp.severance_total,
                "business_net": business_for_income, "taxable_interest": inp.taxable_interest,
            },
            note=("Under-the-table income is excluded. Severance modeled as 1/3 W-2 wages + "
                  "2/3 non-wage damages per the agreement. A business loss reduces this via AGI."),
        ),
        "total_tax": tax.total_tax,
        "ubt": tax.ubt,
        "balance_due_or_refund": tax.balance_due_or_refund,
        "severance_withheld": tax.severance_withheld,
        "set_aside": set_aside,
        "sep_contribution": Traced(
            value=inp.sep_contrib,
            label="SEP IRA contribution",
            formula="sep_ira_annual_pretax",
            inputs={"sep_ira_annual_pretax": inp.sep_contrib},
            note="As entered in the sidebar (annual, pre-tax). Lowers AGI; the Allocation tab can drive this.",
        ),
        "roth_contribution": Traced(
            value=inp.roth_contrib,
            label="Roth IRA contribution",
            formula="roth_ira_annual_posttax",
            inputs={"roth_ira_annual_posttax": inp.roth_contrib},
            note="As entered in the sidebar (annual, post-tax). Does not change your tax.",
        ),
        "etf_contribution": Traced(
            value=cfg.retirement_and_investing.taxable_brokerage_etf_annual,
            label="Taxable ETF contribution",
            formula="taxable_brokerage_etf_annual",
            inputs={"taxable_brokerage_etf_annual": cfg.retirement_and_investing.taxable_brokerage_etf_annual},
            note="As entered in the sidebar (annual). Post-tax brokerage investing.",
        ),
        "hysa": Traced(
            value=ledger.taxable_interest_annual,
            label="HYSA interest (modeled)",
            formula="apy * average cash balance over the runway (compounded monthly)",
            inputs={"apy": cfg.hysa_apy, "ending_balance": ledger.ending_balance},
            method="approximation",
            note="Interest accrues on the modeled cash balance each month — see the Runway tab.",
        ),
        "cash_runs_out": Traced(
            value=float(ledger.cash_runs_out_month if ledger.cash_runs_out_month is not None else -1),
            label="Cash runs out (month index)",
            formula="first month index where the running cash balance goes negative",
            inputs={"starting_cash": ledger.starting_balance},
            method="approximation",
            note=("-1 means cash does not run out within the horizon. "
                  "See the Runway tab for the month-by-month balance."),
        ),
        "ending_cash": Traced(
            value=ledger.ending_balance,
            label="Ending cash balance",
            formula="starting_cash + sum(monthly net) over the runway horizon",
            inputs={"starting_cash": ledger.starting_balance},
            method="approximation",
            note="final-month balance from the runway ledger (see the Runway tab for the rows)",
        ),
    }

    warnings: list[Warning_] = []
    warnings += roth_limit(
        inp.roth_contrib, tax.agi.value,
        cfg.retirement_and_investing.age_50_or_older, r,
    )
    warnings += sep_limit(inp.sep_contrib, inp.se_net, r)
    warnings += qbi_sstb(
        max(0.0, tax.agi.value - r.federal_std_deduction_single),
        inp.business_is_sstb, r,
    )

    return Summary(
        total_monthly_expenses=total_monthly,
        annual_expenses=total_monthly * 12,
        hysa_apy=cfg.hysa_apy,
        hysa_ending_balance=ledger.ending_balance,
        roth_contribution=inp.roth_contrib,
        sep_contribution=inp.sep_contrib,
        etf_contribution=cfg.retirement_and_investing.taxable_brokerage_etf_annual,
        total_taxable_income_2026=taxable_income,
        total_tax_due=tax.total_tax.value,
        ubt=tax.ubt.value,
        severance_withheld=tax.severance_withheld.value,
        balance_due_or_refund=tax.balance_due_or_refund.value,
        set_aside=set_aside.value,
        cash_runs_out_month=ledger.cash_runs_out_month,
        ending_cash_balance=ledger.ending_balance,
        tax=tax,
        ledger=ledger,
        warnings=warnings,
        traces=traces,
    )
