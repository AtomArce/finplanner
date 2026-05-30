from datetime import date

from finplanner.flow import CASH_POOL, build_flow, to_dot
from finplanner.summary import build_summary


def test_flow_has_sources_and_sinks(base_cfg):
    base_cfg.income.w2_earned_ytd_2026 = 25_000
    base_cfg.severance.total_pretax = 72_875
    base_cfg.income.freelance_taxable_monthly = 5_000
    base_cfg.expenses.rent_monthly = 2_200
    base_cfg.retirement_and_investing.taxable_brokerage_etf_annual = 6_000
    s = build_summary(base_cfg, months=12, start_date=date(2026, 7, 1))
    g = build_flow(base_cfg, s)
    assert "W-2 wages" in g.sources
    assert "Severance" in g.sources
    assert "Rent" in g.sinks
    assert "Taxes (2026)" in g.sinks
    # every edge touches the central cash pool
    assert all(e.src == CASH_POOL or e.dst == CASH_POOL for e in g.edges)


def test_under_the_table_edge_is_flagged(base_cfg):
    base_cfg.income.freelance_under_table_monthly = 2_000
    s = build_summary(base_cfg, months=12, start_date=date(2026, 7, 1))
    g = build_flow(base_cfg, s)
    e = g.edge("Under-the-table", CASH_POOL)
    assert e is not None and e.flagged
    assert "risk" in e.note.lower()


def test_amounts_match_config(base_cfg):
    base_cfg.expenses.rent_monthly = 2_200
    base_cfg.severance.total_pretax = 72_875
    s = build_summary(base_cfg, months=12, start_date=date(2026, 7, 1))
    g = build_flow(base_cfg, s)
    rent_edge = g.edge(CASH_POOL, "Rent")
    assert rent_edge.amount == base_cfg.expenses.rent_monthly * 12
    sev_edge = g.edge("Severance", CASH_POOL)
    assert sev_edge.amount == base_cfg.severance.total_pretax


def test_to_dot_renders(base_cfg):
    s = build_summary(base_cfg, months=12, start_date=date(2026, 7, 1))
    dot = to_dot(build_flow(base_cfg, s))
    assert dot.startswith("digraph money {")
    assert "rankdir=LR" in dot
