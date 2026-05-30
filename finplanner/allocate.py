"""Monthly fund-distribution suggester (SPEC §1C backlog).

Auto-suggests how to split each month's surplus across buckets, in priority order:

  1. Tax set-aside      — kept as cash for the 2027 tax bill (NOT invested, NOT a runway drawdown)
  2. Emergency buffer   — kept as cash up to emergency_buffer_months × monthly_expenses
  3. SEP IRA            — up to ~20% of net SE earnings (eligibility.sep_max)
  4. Roth IRA           — up to the cap after MAGI phase-out (eligibility.roth_allowed)
  5. Taxable ETF / extra loan paydown — the remainder

The result is a 12-month schedule the UI shows and lets the user override. Buckets 3–6 are real
cash outflows (money leaves spendable cash) — `contributions_from_schedule()` extracts them so the
runway ledger can draw them down and keep `ending_cash` / `cash_runs_out_month` honest.

Not advice — a planning suggestion. Investing carries risk; see the loan-vs-invest caveat.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import PlannerConfig
from .eligibility import roth_allowed, sep_max
from .rates import rates_for

# Buckets that are real cash outflows (invested / paid out), vs cash retained.
INVEST_BUCKETS = ("sep_ira", "roth_ira", "etf", "extra_loan")
CASH_BUCKETS = ("tax_set_aside", "emergency_buffer")
ALL_BUCKETS = CASH_BUCKETS + INVEST_BUCKETS


@dataclass
class AllocationRow:
    month_index: int
    label: str
    surplus: float
    buckets: dict[str, float] = field(default_factory=dict)

    @property
    def invested(self) -> float:
        return sum(self.buckets.get(b, 0.0) for b in INVEST_BUCKETS)


@dataclass
class AllocationPlan:
    rows: list[AllocationRow]
    annual_totals: dict[str, float]
    caps: dict[str, float]  # {"sep_ira": ..., "roth_ira": ...}
    notes: list[str] = field(default_factory=list)

    def contributions_by_month(self) -> dict[int, float]:
        return contributions_from_schedule(self.rows)


def contributions_from_schedule(rows: list[AllocationRow]) -> dict[int, float]:
    """Per-month cash drawdown = sum of the invest/payout buckets (excludes cash-retained buckets)."""
    return {r.month_index: sum(r.buckets.get(b, 0.0) for b in INVEST_BUCKETS) for r in rows}


def suggest_allocation(
    cfg: PlannerConfig,
    summary,
    remainder_to: str = "etf",  # "etf" | "extra_loan" | "split"
) -> AllocationPlan:
    """Greedy priority allocation across the runway months from each month's positive surplus."""
    r = rates_for(cfg.meta.tax_year)
    rows_in = summary.ledger.rows
    months = len(rows_in)

    se_net = max(0.0, cfg.freelance_taxable_annual - cfg.bizexp_annual)
    sep_cap = sep_max(se_net, r)
    roth_cap = roth_allowed(summary.tax.agi.value, cfg.retirement_and_investing.age_50_or_older, r)

    set_aside_slice = summary.set_aside / months if months else 0.0
    buffer_target = cfg.assumptions.emergency_buffer_months * summary.total_monthly_expenses
    sep_slice = sep_cap / months if months else 0.0
    roth_slice = roth_cap / months if months else 0.0

    buffer_funded = 0.0
    sep_funded = 0.0
    roth_funded = 0.0
    rows: list[AllocationRow] = []

    for led in rows_in:
        surplus = max(0.0, led.net)
        remaining = surplus
        b: dict[str, float] = {k: 0.0 for k in ALL_BUCKETS}

        # 1. tax set-aside (cash retained)
        sa = min(set_aside_slice, remaining)
        b["tax_set_aside"] = sa
        remaining -= sa

        # 2. emergency buffer (cash retained, up to target)
        buf = min(max(0.0, buffer_target - buffer_funded), remaining)
        b["emergency_buffer"] = buf
        buffer_funded += buf
        remaining -= buf

        # 3. SEP IRA (spread, capped)
        sep = min(sep_slice, max(0.0, sep_cap - sep_funded), remaining)
        b["sep_ira"] = sep
        sep_funded += sep
        remaining -= sep

        # 4. Roth IRA (spread, capped)
        roth = min(roth_slice, max(0.0, roth_cap - roth_funded), remaining)
        b["roth_ira"] = roth
        roth_funded += roth
        remaining -= roth

        # 5. remainder -> ETF and/or extra loan paydown
        if remaining > 0:
            if remainder_to == "extra_loan":
                b["extra_loan"] = remaining
            elif remainder_to == "split":
                b["etf"] = remaining / 2.0
                b["extra_loan"] = remaining / 2.0
            else:
                b["etf"] = remaining

        rows.append(AllocationRow(led.month_index, led.label, surplus, b))

    annual_totals = {k: sum(row.buckets.get(k, 0.0) for row in rows) for k in ALL_BUCKETS}

    notes: list[str] = []
    if sep_cap <= 0:
        notes.append("SEP room is $0 (no net self-employment income) — SEP gets $0.")
    if annual_totals["sep_ira"] < sep_cap - 1:
        notes.append(f"SEP funded {annual_totals['sep_ira']:,.0f} of the {sep_cap:,.0f} cap "
                     f"(limited by available surplus).")
    if annual_totals["roth_ira"] < roth_cap - 1:
        notes.append(f"Roth funded {annual_totals['roth_ira']:,.0f} of the {roth_cap:,.0f} cap "
                     f"(limited by available surplus).")

    return AllocationPlan(
        rows=rows,
        annual_totals=annual_totals,
        caps={"sep_ira": sep_cap, "roth_ira": roth_cap},
        notes=notes,
    )
