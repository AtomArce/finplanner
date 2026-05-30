from finplanner.loan import amortize, optimal_payment


def test_known_amortization_26k():
    # $26,000 @ 6.5% APR, $600/mo -> 50 months, ~$3,713 interest.
    a = amortize(26_000, 6.5, 600)
    assert a.months_to_payoff == 50
    assert abs(a.total_interest - 3_713.17) < 1.0
    assert not a.never_amortizes
    assert a.schedule[-1]["balance"] == 0.0


def test_never_amortizes_when_payment_below_interest():
    # First month interest on $26k @ 6.5% is ~$140.83; a $100 payment never amortizes.
    a = amortize(26_000, 6.5, 100)
    assert a.never_amortizes
    assert a.months_to_payoff is None
    assert a.total_interest == float("inf")


def test_optimal_pays_minimum_when_return_beats_apr():
    o = optimal_payment(26_000, 6.5, invest_return_annual_percent=7.0,
                         min_payment=200, max_affordable_payment=1_000)
    assert o.payment < 1_000  # invest the rest
    assert "uncertain" in o.reasoning.lower()


def test_optimal_pays_max_when_apr_beats_return():
    o = optimal_payment(26_000, 6.5, invest_return_annual_percent=4.0,
                        min_payment=200, max_affordable_payment=1_000)
    assert o.payment == 1_000  # guaranteed return wins
    assert o.months_to_payoff is not None
