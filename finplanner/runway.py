"""Month-by-month runway ledger (SPEC §4.6).

Returns the FULL ledger as data — every row has income by source, expense by category,
HYSA interest, and the running balance — so the UI can chart OR table it (fixes the
prototype's "no inspectable per-month rows" gap, SPEC §1A).

Under-the-table freelance income is spendable cash here but is NOT taxable interest and is
NOT part of any tax math (PROCESS_LOG decision 1). It is kept exactly as entered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .config import PlannerConfig
from .severance import Installment, schedule


@dataclass
class MonthRow:
    month_index: int
    label: str  # "YYYY-MM" if dated, else "M+n"
    # income by source
    severance_in: float = 0.0
    freelance_taxable_in: float = 0.0
    freelance_under_table_in: float = 0.0
    hysa_interest_in: float = 0.0
    card_rewards_in: float = 0.0
    # expense by category (positive numbers = outflow)
    rent_out: float = 0.0
    other_out: float = 0.0
    bizexp_out: float = 0.0
    loan_out: float = 0.0
    card_fee_out: float = 0.0
    contributions_out: float = 0.0  # planned SEP/Roth/ETF/extra-loan etc. drawn from cash
    # rollup
    balance: float = 0.0

    @property
    def income_total(self) -> float:
        return (self.severance_in + self.freelance_taxable_in + self.freelance_under_table_in
                + self.hysa_interest_in + self.card_rewards_in)

    @property
    def expense_total(self) -> float:
        return (self.rent_out + self.other_out + self.bizexp_out + self.loan_out
                + self.card_fee_out + self.contributions_out)

    @property
    def net(self) -> float:
        return self.income_total - self.expense_total


@dataclass
class Ledger:
    rows: list[MonthRow]
    cash_runs_out_month: int | None  # first month_index with balance < 0, else None
    taxable_interest_annual: float  # HYSA interest accrued (feeds the tax model)
    starting_balance: float
    ending_balance: float
    installments: list[Installment] = field(default_factory=list)

    def balance_series(self) -> list[float]:
        return [r.balance for r in self.rows]


def _month_offset(start: date, d: date) -> int:
    return (d.year - start.year) * 12 + (d.month - start.month)


def build_ledger(
    cfg: PlannerConfig,
    months: int = 12,
    start_date: date | None = None,
    monthly_contributions: dict[int, float] | None = None,
) -> Ledger:
    """`monthly_contributions` maps month_index -> planned savings/contribution outflow for
    that month (SEP/Roth/ETF/extra loan). When provided, those amounts draw down cash so the
    ending balance and runout month stay honest. Default None preserves prior behavior."""
    start = start_date or cfg.severance.signing_date or date.today()

    insts = schedule(
        cfg.severance.total_pretax,
        cfg.severance.signing_date or start,
        cfg.severance.installment_offsets_days,
    )
    sev_by_month: dict[int, float] = {}
    for inst in insts:
        if inst.pay_date is not None:
            m = _month_offset(start, inst.pay_date)
            if 0 <= m < months:
                sev_by_month[m] = sev_by_month.get(m, 0.0) + inst.amount

    apy = cfg.hysa_apy
    rent = cfg.expenses.rent_monthly
    other = cfg.expenses.other_monthly
    bizexp_monthly = cfg.expenses.business_expense_monthly_deductible
    bizexp_months = cfg.expenses.business_expense_applies_months
    loan_payment = cfg.debt.student_loan.monthly_payment
    card_fee_monthly = cfg.card_annual_fee / 12.0
    card_rewards_monthly = cfg.card_rewards_pct / 100.0 * other  # proxy: % of "other" spend
    free_months = cfg.free_months
    fl_taxable = cfg.income.freelance_taxable_monthly
    fl_under = cfg.income.freelance_under_table_monthly

    balance = cfg.retirement_and_investing.starting_cash_excl_severance
    rows: list[MonthRow] = []
    taxable_interest = 0.0
    runs_out: int | None = None

    for m in range(months):
        if cfg.severance.signing_date:
            y = start.year + (start.month - 1 + m) // 12
            mo = (start.month - 1 + m) % 12 + 1
            label = f"{y:04d}-{mo:02d}"
        else:
            label = f"M+{m}"
        row = MonthRow(month_index=m, label=label)

        # interest accrues on positive balance at start of month, compounds into balance
        interest = balance * apy / 12.0 if balance > 0 else 0.0
        row.hysa_interest_in = interest
        taxable_interest += interest

        row.severance_in = sev_by_month.get(m, 0.0)
        if m < free_months:
            row.freelance_taxable_in = fl_taxable
            row.freelance_under_table_in = fl_under
        row.card_rewards_in = card_rewards_monthly

        row.rent_out = rent
        row.other_out = other
        row.bizexp_out = bizexp_monthly if m < bizexp_months else 0.0
        row.loan_out = loan_payment
        row.card_fee_out = card_fee_monthly
        if monthly_contributions:
            row.contributions_out = monthly_contributions.get(m, 0.0)

        balance = balance + row.net
        row.balance = balance
        if balance < 0 and runs_out is None:
            runs_out = m
        rows.append(row)

    return Ledger(
        rows=rows,
        cash_runs_out_month=runs_out,
        taxable_interest_annual=taxable_interest,
        starting_balance=cfg.retirement_and_investing.starting_cash_excl_severance,
        ending_balance=balance,
        installments=insts,
    )
