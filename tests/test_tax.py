"""Reference tax cases (SPEC §5). Expected values hand-derived; tolerance ±$1.

Severance in cases b–e uses even thirds of $72,875: installment 1 (wages) = 24,291.67,
installments 2+3 (damages) = 48,583.33.
"""

import math

import pytest

from finplanner.rates import rates_for, tax_from_brackets
from finplanner.tax import TaxInputs, compute_tax

R = rates_for(2026)
TOL = 1.0

SEV_WAGES = 24_291.67
SEV_DAMAGES = 48_583.33


def approx(a, b, tol=TOL):
    assert abs(a - b) <= tol, f"{a:,.2f} != {b:,.2f} (±{tol})"


def test_case_a_w2_only():
    # W-2 $120k. fed_ti = 120000 - 16100 = 103900.
    # fed = .10*11925 + .12*36550 + .22*54875 + .24*550 = 1192.5+4386+12072.5+132 = 17783.
    # NY ti = 112000: 686 + 290.25 + 225.75 + 4919.85 = 6121.85.
    # NYC ti = 112000: 369.36 + 489.06 + 954.75 + 2403.12 = 4216.29.
    t = compute_tax(TaxInputs(w2_wages=120_000), R)
    approx(t.se_tax.value, 0)
    approx(t.federal_income_tax.value, 17_783.00)
    approx(t.ny_tax.value, 6_121.85)
    approx(t.nyc_tax.value, 4_216.29)
    approx(t.total_tax.value, 28_121.14)


def test_case_b_w2_plus_severance():
    # W-2 25k + severance 72,875 (all ordinary income). No SE.
    t = compute_tax(
        TaxInputs(w2_wages=25_000, severance_wages=SEV_WAGES, severance_damages=SEV_DAMAGES), R
    )
    approx(t.se_tax.value, 0)
    approx(t.agi.value, 97_875.00)
    approx(t.federal_income_tax.value, 12_904.50)
    approx(t.total_tax.value, 21_090.76)


def test_case_c_freelance_and_bizexp():
    # + freelance 60k gross, bizexp 12k -> se_net 48k.
    # se_base = 48000*0.9235 = 44328; SE = 44328*(.124+.029) = 6782.18 (under SS cap).
    t = compute_tax(
        TaxInputs(
            w2_wages=25_000, severance_wages=SEV_WAGES, severance_damages=SEV_DAMAGES,
            freelance_taxable_annual=60_000, bizexp_annual=12_000, business_is_sstb=True,
        ),
        R,
    )
    approx(t.se_tax.value, 6_782.18)
    approx(t.half_se.value, 3_391.09)
    approx(t.qbi_deduction.value, 9_600.00)  # 20% of se_net, below SSTB threshold
    approx(t.agi.value, 142_483.91)
    approx(t.total_tax.value, 40_182.25)


def test_case_d_sep_lowers_income_tax_not_se():
    base = TaxInputs(
        w2_wages=25_000, severance_wages=SEV_WAGES, severance_damages=SEV_DAMAGES,
        freelance_taxable_annual=60_000, bizexp_annual=12_000, business_is_sstb=True,
    )
    no_sep = compute_tax(base, R)
    with_sep = compute_tax(
        TaxInputs(**{**base.__dict__, "sep_contrib": 10_000}), R
    )
    # SE tax unchanged; AGI drops by exactly the contribution.
    approx(with_sep.se_tax.value, no_sep.se_tax.value)
    approx(with_sep.agi.value, no_sep.agi.value - 10_000)
    # Federal tax drops by ~10k * 24% marginal = 2400.
    approx(no_sep.federal_income_tax.value - with_sep.federal_income_tax.value, 2_400.00)
    assert with_sep.total_tax.value < no_sep.total_tax.value


def test_case_e_roth_changes_nothing():
    base = dict(
        w2_wages=25_000, severance_wages=SEV_WAGES, severance_damages=SEV_DAMAGES,
        freelance_taxable_annual=60_000, bizexp_annual=12_000, sep_contrib=10_000,
        business_is_sstb=True,
    )
    without = compute_tax(TaxInputs(**base), R)
    with_roth = compute_tax(TaxInputs(**base, roth_contrib=7_000), R)
    approx(with_roth.total_tax.value, without.total_tax.value, tol=0.001)
    approx(with_roth.agi.value, without.agi.value, tol=0.001)


def test_case_f_high_income_ss_cap_niit_addl_medicare():
    # W-2 150k + freelance 200k (bizexp 20k -> se_net 180k) + 30k interest, non-SSTB.
    # SS cap: ss_room = 184500 - 150000 = 34500; SS = 34500*.124 = 4278.
    # Medicare = 166230*.029 = 4820.67; SE = 9098.67.
    # addl Medicare: (150000 + 166230 - 200000)*0.009 = 116230*.009 = 1046.07.
    # NIIT: min(30000, AGI-200000)*0.038 = 30000*.038 = 1140.
    t = compute_tax(
        TaxInputs(
            w2_wages=150_000, freelance_taxable_annual=200_000, bizexp_annual=20_000,
            taxable_interest=30_000, business_is_sstb=False,
        ),
        R,
    )
    approx(t.se_tax.value, 9_098.67)  # SS portion capped
    approx(t.addl_medicare.value, 1_046.07)
    approx(t.niit.value, 1_140.00)
    approx(t.total_tax.value, 121_131.90)


def test_qbi_sstb_phaseout_zero_above_band():
    # SSTB with taxable income well above threshold+width -> QBI fully phased out.
    t = compute_tax(
        TaxInputs(w2_wages=300_000, freelance_taxable_annual=100_000, business_is_sstb=True), R
    )
    approx(t.qbi_deduction.value, 0.0)


def test_brackets_zero_and_negative():
    assert tax_from_brackets(0, R.federal_brackets) == 0
    assert tax_from_brackets(-500, R.federal_brackets) == 0


def test_trace_equals_computation():
    """Property: every verifiable Traced.value equals re-evaluating its formula (SPEC §5)."""
    t = compute_tax(
        TaxInputs(
            w2_wages=25_000, severance_wages=SEV_WAGES, severance_damages=SEV_DAMAGES,
            freelance_taxable_annual=60_000, bizexp_annual=12_000, sep_contrib=10_000,
            business_is_sstb=True,
        ),
        R,
    )

    def walk(tr):
        if tr.verifiable():
            assert math.isclose(tr.value, tr.recompute(), abs_tol=0.01), (
                f"{tr.label}: stored {tr.value} != recomputed {tr.recompute()}"
            )
        for c in tr.children:
            walk(c)

    for top in t.all_traced():
        walk(top)
