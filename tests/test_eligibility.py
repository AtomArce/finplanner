from finplanner.eligibility import qbi_sstb, roth_limit, sep_limit
from finplanner.rates import rates_for

R = rates_for(2026)


def test_roth_over_cap_errors():
    w = roth_limit(10_000, magi=50_000, age_50_or_older=False, r=R)
    assert any(x.severity == "error" for x in w)
    assert w[0].suggested_value == R.roth_ira_limit


def test_roth_catchup_raises_cap():
    # 8000 is over the 7500 base cap but under 7500+1100 catch-up.
    under = roth_limit(8_000, magi=50_000, age_50_or_older=True, r=R)
    assert under == []  # within catch-up cap, MAGI below phase-out


def test_roth_magi_phaseout_blocks_above_ceiling():
    w = roth_limit(7_500, magi=200_000, age_50_or_older=False, r=R)
    assert any("backdoor" in x.message.lower() for x in w)
    assert any(x.suggested_value == 0.0 for x in w)


def test_roth_magi_partial_phaseout_warns():
    midpoint = (R.roth_phaseout_start_single + R.roth_phaseout_end_single) / 2
    w = roth_limit(7_500, magi=midpoint, age_50_or_older=False, r=R)
    assert any(x.severity == "warning" for x in w)
    assert 0 < w[0].suggested_value < R.roth_ira_limit


def test_sep_over_limit_warns():
    # net SE 40k -> max SEP ~ 20% of adjusted net (~$8k); 20k contribution is over.
    w = sep_limit(20_000, se_net=40_000, r=R)
    assert any(x.severity == "warning" for x in w)
    assert w[0].suggested_value < 20_000
    assert "business expense" in w[0].message.lower()


def test_sep_zero_se_explains_distinction():
    w = sep_limit(30_000, se_net=0, r=R)
    assert w and w[0].suggested_value == 0.0
    msg = w[0].message.lower()
    assert "retirement" in msg and "business" in msg


def test_qbi_sstb_phaseout_warns_above_ceiling():
    end = R.qbi_threshold_single + R.qbi_phaseout_width_single
    w = qbi_sstb(end + 1_000, is_sstb=True, r=R)
    assert w and w[0].suggested_value == 0.0


def test_qbi_non_sstb_no_warning():
    assert qbi_sstb(500_000, is_sstb=False, r=R) == []
