from datetime import date

from finplanner.rates import rates_for
from finplanner.severance import (
    damages_total,
    estimate_set_aside,
    schedule,
    wages_total,
)
from finplanner.tax import TaxInputs


def test_schedule_split_and_dates():
    insts = schedule(72_875, date(2026, 6, 1), [45, 105, 135])
    assert len(insts) == 3
    assert insts[0].kind == "w2_wages" and insts[0].withheld
    assert insts[1].kind == "damages_non_wage" and not insts[1].withheld
    assert insts[2].kind == "damages_non_wage" and not insts[2].withheld
    assert insts[0].pay_date == date(2026, 7, 16)
    assert abs(wages_total(insts) - 72_875 / 3) < 0.01
    assert abs(damages_total(insts) - 2 * 72_875 / 3) < 0.01


def test_schedule_tbd_signing_date():
    insts = schedule(72_875, None, [45, 105, 135])
    assert all(i.pay_date is None for i in insts)


def test_set_aside_is_approximation_and_positive():
    inp = TaxInputs(w2_wages=25_000, severance_wages=24_291.67, severance_damages=48_583.33)
    sa = estimate_set_aside(inp, rates_for(2026))
    assert sa.method == "approximation"
    assert sa.value > 0
    assert "CPA" in sa.note
