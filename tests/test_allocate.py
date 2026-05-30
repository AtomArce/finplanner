from datetime import date

from finplanner.allocate import (
    INVEST_BUCKETS,
    contributions_from_schedule,
    suggest_allocation,
)
from finplanner.summary import build_summary


def _summary_with_income(base_cfg, freelance_monthly=8_000, start=160_000):
    base_cfg.income.freelance_taxable_monthly = freelance_monthly
    base_cfg.retirement_and_investing.starting_cash_excl_severance = start
    return build_summary(base_cfg, months=12, start_date=date(2026, 7, 1))


def test_set_aside_funded_before_investing(base_cfg):
    s = _summary_with_income(base_cfg)
    plan = suggest_allocation(base_cfg, s)
    # In the first surplus month, set-aside is funded before any invest bucket if surplus is tight.
    first = next(r for r in plan.rows if r.surplus > 0)
    assert first.buckets["tax_set_aside"] > 0


def test_sep_never_exceeds_cap(base_cfg):
    s = _summary_with_income(base_cfg)
    plan = suggest_allocation(base_cfg, s)
    assert plan.annual_totals["sep_ira"] <= plan.caps["sep_ira"] + 1


def test_roth_never_exceeds_cap(base_cfg):
    s = _summary_with_income(base_cfg)
    plan = suggest_allocation(base_cfg, s)
    assert plan.annual_totals["roth_ira"] <= plan.caps["roth_ira"] + 1


def test_monthly_buckets_never_exceed_surplus(base_cfg):
    s = _summary_with_income(base_cfg)
    plan = suggest_allocation(base_cfg, s)
    for row in plan.rows:
        assert sum(row.buckets.values()) <= row.surplus + 0.01


def test_zero_se_puts_nothing_in_sep(base_cfg):
    # no freelance income -> SEP cap is 0
    base_cfg.income.freelance_taxable_monthly = 0
    base_cfg.retirement_and_investing.starting_cash_excl_severance = 100_000
    s = build_summary(base_cfg, months=12, start_date=date(2026, 7, 1))
    plan = suggest_allocation(base_cfg, s)
    assert plan.caps["sep_ira"] == 0
    assert plan.annual_totals["sep_ira"] == 0


def test_contributions_exclude_cash_buckets(base_cfg):
    s = _summary_with_income(base_cfg)
    plan = suggest_allocation(base_cfg, s)
    contribs = contributions_from_schedule(plan.rows)
    for row in plan.rows:
        expected = sum(row.buckets.get(b, 0.0) for b in INVEST_BUCKETS)
        assert abs(contribs[row.month_index] - expected) < 0.01
    # cash-retained buckets are not in the drawdown
    assert plan.annual_totals["tax_set_aside"] > 0


def test_remainder_split_option(base_cfg):
    s = _summary_with_income(base_cfg)
    plan = suggest_allocation(base_cfg, s, remainder_to="split")
    # when there's leftover, split puts equal into etf and extra_loan
    assert abs(plan.annual_totals["etf"] - plan.annual_totals["extra_loan"]) < 1.0
