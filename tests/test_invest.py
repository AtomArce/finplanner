from finplanner.invest import distribution_matrix, grow, loan_vs_invest


def test_grow_zero_rate_is_just_contributions():
    assert abs(grow(0, 100, 0.0, 1) - 1_200) < 1e-6


def test_grow_compounds_above_contributions():
    # 7% should beat the raw $6,000 contributed over 5 years on $100/mo.
    assert grow(0, 100, 7.0, 5) > 6_000


def test_loan_vs_invest_always_returns_caveat():
    cmp = loan_vs_invest(26_000, 6.5, 600, 400, 7.0, 10)
    assert cmp.caveat
    assert "volatile" in cmp.caveat.lower()
    assert cmp.lean in ("invest", "pay_loan")


def test_distribution_matrix_shape():
    cells = distribution_matrix(26_000, 6.5, [600, 1000], [200, 500], 7.0)
    assert len(cells) == 4
    for c in cells:
        assert c.invest_30yr > c.invest_5yr
