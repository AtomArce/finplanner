from datetime import date

from finplanner.config import HysaPick
from finplanner.runway import build_ledger


def test_severance_lands_in_correct_months(base_cfg):
    # signing 2026-06-01; offsets [45,105,135] -> 2026-07-16, 2026-09-14, 2026-10-14
    # month offsets from 2026-06 start: 1, 3, 4. Each installment = 72875/3 = 24291.67.
    base_cfg.severance.total_pretax = 72_875
    led = build_ledger(base_cfg, months=12, start_date=date(2026, 6, 1))
    each = 72_875 / 3
    by_month = {r.month_index: r.severance_in for r in led.rows}
    assert abs(by_month[1] - each) < 0.01
    assert abs(by_month[3] - each) < 0.01
    assert abs(by_month[4] - each) < 0.01
    assert by_month[0] == 0.0
    assert by_month[2] == 0.0


def test_hysa_interest_compounds(base_cfg):
    base_cfg.retirement_and_investing.starting_cash_excl_severance = 100_000
    base_cfg.institution_picks.hysa = HysaPick(name="Test", apy=4.0)
    # zero out flows so balance only grows by interest
    base_cfg.expenses.rent_monthly = 0
    base_cfg.expenses.other_monthly = 0
    base_cfg.debt.student_loan.monthly_payment = 0
    base_cfg.severance.total_pretax = 0
    led = build_ledger(base_cfg, months=3, start_date=date(2026, 6, 1))
    i0, i1 = led.rows[0].hysa_interest_in, led.rows[1].hysa_interest_in
    assert i0 > 0
    assert i1 > i0  # compounding: month 1 interest on a larger balance
    assert led.taxable_interest_annual > 0


def test_cash_runs_out(base_cfg):
    base_cfg.retirement_and_investing.starting_cash_excl_severance = 3_000
    base_cfg.severance.total_pretax = 0  # no rescue
    base_cfg.income.freelance_taxable_monthly = 0
    base_cfg.income.freelance_under_table_monthly = 0
    base_cfg.expenses.rent_monthly = 2_200
    base_cfg.expenses.other_monthly = 1_800
    base_cfg.debt.student_loan.monthly_payment = 600
    # rent 2200 + other 1800 + loan 600 = 4600/mo outflow, 3000 start -> negative month 0
    led = build_ledger(base_cfg, months=6, start_date=date(2026, 6, 1))
    assert led.cash_runs_out_month == 0


def test_ledger_is_full_data(base_cfg):
    led = build_ledger(base_cfg, months=12, start_date=date(2026, 6, 1))
    assert len(led.rows) == 12
    r = led.rows[0]
    # every row exposes income-by-source and expense-by-category
    assert hasattr(r, "rent_out") and hasattr(r, "freelance_taxable_in")
    assert r.label == "2026-06"
