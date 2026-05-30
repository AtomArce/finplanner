"""Streamlit UI — views over the finplanner core (SPEC §0.3, §6).

Run:  streamlit run app/streamlit_app.py

Every number is read from the core (single source of truth); headline values can be expanded to
their full trace (formula + inputs + approximation notes). The not-advice disclaimer is shown on
every view.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finplanner import DISCLAIMER  # noqa: E402
from finplanner.allocate import (  # noqa: E402
    ALL_BUCKETS,
    contributions_from_schedule,
    suggest_allocation,
)
from finplanner.allocate import AllocationRow  # noqa: E402
from finplanner.config import PlannerConfig  # noqa: E402
from finplanner.flow import build_flow, to_dot  # noqa: E402
from finplanner.io import load_config  # noqa: E402
from finplanner.loan import amortize, optimal_payment  # noqa: E402
from finplanner.runway import build_ledger  # noqa: E402
from finplanner.scenarios import (  # noqa: E402
    long_run_growth_scenario,
    maximize_take_home_scenario,
    pay_loan_vs_invest_scenario,
)
from finplanner.summary import build_summary  # noqa: E402
from finplanner.trace import Traced  # noqa: E402

STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"


def _config_from_upload(raw: dict) -> PlannerConfig:
    """Parse a config dict from an uploaded JSON file (mirrors io._config_from_raw)."""
    data = {k: v for k, v in raw.items() if not k.startswith("_")}
    if "_meta" in raw:
        data["meta"] = raw["_meta"]
    picks = data.get("institution_picks")
    if isinstance(picks, dict):
        data["institution_picks"] = {k: v for k, v in picks.items() if not k.startswith("_")}
    return PlannerConfig.model_validate(data)


def _cfg_to_json(cfg: PlannerConfig) -> str:
    """Serialize current cfg for download."""
    out = cfg.model_dump(mode="json", exclude_none=False)
    out["_meta"] = out.pop("meta", {})
    return json.dumps(out, indent=2, default=str)


@st.cache_data
def _load() -> PlannerConfig:
    return load_config(STATE_PATH)


def money(x: float) -> str:
    return f"${x:,.0f}"


def md_safe(text: str) -> str:
    """Escape $ so Streamlit markdown doesn't interpret $...$ as LaTeX math."""
    return text.replace("$", "\\$")


def show_trace(tr: Traced) -> None:
    flag = " ⚠ approximation" if tr.method == "approximation" else ""
    with st.expander(f"{tr.label}: {tr.value:,.2f}{flag}"):
        st.code(tr.explain(), language="text")


def _load_into_session(loaded: PlannerConfig) -> None:
    """Push a loaded config into session_state so all sidebar widgets reset to saved values."""
    sd = loaded.severance.signing_date or date(2026, 7, 1)
    st.session_state["signing_date"] = sd
    st.session_state["w2_earned"] = float(loaded.income.w2_earned_ytd_2026)
    st.session_state["severance"] = float(loaded.severance.total_pretax)
    st.session_state["freelance_monthly"] = float(loaded.income.freelance_taxable_monthly)
    st.session_state["under_table_monthly"] = float(loaded.income.freelance_under_table_monthly)
    st.session_state["rent"] = float(loaded.expenses.rent_monthly)
    st.session_state["other"] = float(loaded.expenses.other_monthly)
    st.session_state["bizexp"] = float(loaded.expenses.business_expense_monthly_deductible)
    st.session_state["starting_cash"] = float(loaded.retirement_and_investing.starting_cash_excl_severance)
    st.session_state["sep_ira"] = float(loaded.retirement_and_investing.sep_ira_annual_pretax)
    st.session_state["roth_ira"] = float(loaded.retirement_and_investing.roth_ira_annual_posttax)
    st.session_state["sstb"] = loaded.retirement_and_investing.business_is_sstb
    st.session_state["invest_return"] = float(loaded.assumptions.investment_return_annual_percent)
    st.session_state["runway_months"] = st.session_state.get("runway_months", 12)


def sidebar(cfg: PlannerConfig) -> tuple[PlannerConfig, int]:
    st.sidebar.header("Inputs")

    # ── Upload saved config ──────────────────────────────────────────────────
    uploaded = st.sidebar.file_uploader(
        "📂 Load saved config", type=["json"], label_visibility="collapsed",
        help="Upload a previously saved finplanner_config.json to restore your inputs.",
    )
    if uploaded is not None:
        try:
            raw = json.load(uploaded)
            _load_into_session(_config_from_upload(raw))
            st.rerun()
        except Exception as exc:
            st.sidebar.error(f"Could not load config: {exc}")

    cfg.severance.signing_date = st.sidebar.slider(
        "Severance signing date",
        min_value=date(2026, 1, 1), max_value=date(2026, 12, 31),
        value=date(2026, 7, 1), format="YYYY-MM-DD",
        key="signing_date",
    )
    cfg.income.w2_earned_ytd_2026 = st.sidebar.number_input(
        "W-2 earned YTD", value=float(cfg.income.w2_earned_ytd_2026), step=1000.0,
        key="w2_earned")
    cfg.severance.total_pretax = st.sidebar.number_input(
        "Severance (pretax)", value=float(cfg.severance.total_pretax), step=1000.0,
        key="severance")
    cfg.income.freelance_taxable_monthly = st.sidebar.number_input(
        "Freelance taxable / mo", value=float(cfg.income.freelance_taxable_monthly), step=500.0,
        key="freelance_monthly")
    cfg.income.freelance_under_table_monthly = st.sidebar.number_input(
        "Under-the-table / mo (⚠ excluded from tax)", value=float(cfg.income.freelance_under_table_monthly), step=500.0,
        key="under_table_monthly")
    cfg.expenses.rent_monthly = st.sidebar.number_input(
        "Rent / mo", value=float(cfg.expenses.rent_monthly), step=100.0,
        key="rent")
    cfg.expenses.other_monthly = st.sidebar.number_input(
        "Other / mo", value=float(cfg.expenses.other_monthly), step=100.0,
        key="other")
    cfg.expenses.business_expense_monthly_deductible = st.sidebar.number_input(
        "Business expense / mo (lowers taxable income)", value=float(cfg.expenses.business_expense_monthly_deductible), step=100.0,
        key="bizexp")
    cfg.retirement_and_investing.starting_cash_excl_severance = st.sidebar.number_input(
        "Starting cash (excl. severance)", value=float(cfg.retirement_and_investing.starting_cash_excl_severance), step=1000.0,
        key="starting_cash")
    cfg.retirement_and_investing.sep_ira_annual_pretax = st.sidebar.number_input(
        "SEP IRA / yr (pretax, needs SE income)", value=float(cfg.retirement_and_investing.sep_ira_annual_pretax), step=500.0,
        key="sep_ira")
    cfg.retirement_and_investing.roth_ira_annual_posttax = st.sidebar.number_input(
        "Roth IRA / yr (post-tax)", value=float(cfg.retirement_and_investing.roth_ira_annual_posttax), step=500.0,
        key="roth_ira")
    cfg.retirement_and_investing.business_is_sstb = st.sidebar.checkbox(
        "Business is a specified-service trade (SSTB)", value=cfg.retirement_and_investing.business_is_sstb,
        key="sstb")
    cfg.assumptions.investment_return_annual_percent = st.sidebar.slider(
        "Assumed investment return %", 0.0, 12.0, float(cfg.assumptions.investment_return_annual_percent), 0.5,
        key="invest_return")
    months = st.sidebar.slider("Runway horizon (months)", 6, 36, 12, key="runway_months")

    # ── Download current config ──────────────────────────────────────────────
    st.sidebar.divider()
    st.sidebar.download_button(
        "💾 Save config",
        data=_cfg_to_json(cfg),
        file_name="finplanner_config.json",
        mime="application/json",
        help="Download your current inputs as a JSON file. Upload it next time to restore them.",
        use_container_width=True,
    )

    return cfg, months


def view_summary(s) -> None:
    st.subheader("Consolidated Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly expenses", money(s.total_monthly_expenses))
    c2.metric("Taxable income 2026", money(s.total_taxable_income_2026))
    c3.metric(f"Total tax due {s.tax_due_date}", money(s.total_tax_due))
    c1.metric("Set-aside ⚠ approx", money(s.set_aside))
    c2.metric("Ending cash", money(s.ending_cash_balance))
    runout = "Doesn't run out" if s.cash_runs_out_month is None else f"Month {s.cash_runs_out_month}"
    c3.metric("Cash runs out", runout)
    c1.metric("SEP contribution", money(s.sep_contribution))
    c2.metric("Roth contribution", money(s.roth_contribution))
    c3.metric("HYSA APY", f"{s.hysa_apy * 100:.2f}%")

    st.markdown("#### Show calculations")
    st.caption("Expand any value to see its formula, inputs, and approximation notes.")
    for tr in s.traces.values():
        show_trace(tr)

    if s.warnings:
        st.markdown("#### Eligibility warnings")
        for w in s.warnings:
            icon = {"error": "🛑", "warning": "⚠️", "info": "ℹ️"}.get(w.severity, "•")
            sv = "" if w.suggested_value is None else f" (suggested: {w.suggested_value:,.0f})"
            st.warning(md_safe(f"{icon} **{w.field}** — {w.message}{sv}"))
    else:
        st.success("No eligibility warnings.")


def view_tax(s) -> None:
    st.subheader("2026 Tax — every number is traceable")
    st.markdown(
        "We optimize for **maximum take-home cash**, not a \\$0 tax bill. "
        "Expand any line to see the formula, inputs, and approximation notes."
    )
    for tr in s.tax.all_traced():
        show_trace(tr)


def view_runway(s) -> None:
    st.subheader("Runway — month-by-month ledger")
    df = pd.DataFrame([{
        "month": r.label, "income": round(r.income_total), "expense": round(r.expense_total),
        "severance": round(r.severance_in), "freelance": round(r.freelance_taxable_in),
        "under_table": round(r.freelance_under_table_in), "hysa_interest": round(r.hysa_interest_in, 2),
        "balance": round(r.balance),
    } for r in s.ledger.rows])
    st.line_chart(df, x="month", y="balance")
    st.dataframe(df, width="stretch", hide_index=True)
    if any(r.freelance_under_table_in for r in s.ledger.rows):
        st.warning("⚠ Under-the-table income is spendable cash here but is excluded from all tax "
                   "math and carries legal/IRS risk. Modeled exactly as entered — not endorsed.")


def view_loan(cfg: PlannerConfig) -> None:
    st.subheader("Student Loan")
    sl = cfg.debt.student_loan
    if sl.balance <= 0:
        st.info("Enter your loan balance, monthly payment, and APR in the sidebar to see the payoff schedule.")
        return
    a = amortize(sl.balance, sl.apr_percent, sl.monthly_payment)
    if a.never_amortizes:
        st.error(md_safe(f"At {money(sl.monthly_payment)}/mo the balance never amortizes "
                         f"(monthly interest exceeds the payment)."))
    else:
        c1, c2 = st.columns(2)
        c1.metric("Months to payoff", a.months_to_payoff)
        c2.metric("Total interest", money(a.total_interest))
        ldf = pd.DataFrame([{"month": row["month"], "balance": round(row["balance"])} for row in a.schedule])
        if not ldf.empty:
            st.line_chart(ldf, x="month", y="balance")
    o = optimal_payment(sl.balance, sl.apr_percent,
                        cfg.assumptions.investment_return_annual_percent,
                        min_payment=sl.monthly_payment, max_affordable_payment=sl.monthly_payment + 600)
    st.markdown(md_safe(f"**Optimal payment ≈ {money(o.payment)}/mo**"))
    st.caption(md_safe(o.reasoning))


def view_scenarios(cfg: PlannerConfig) -> None:
    st.subheader("Scenarios — interactive")
    c1, c2, c3 = st.columns(3)
    extra = c1.slider("Extra loan payment / mo", 0, 2000, 400, 50)
    years = c2.slider("Horizon (years)", 1, 30, 10)
    monthly_invest = c3.slider("Monthly invest amount", 0, 3000, 500, 50)

    scenarios = [
        maximize_take_home_scenario(cfg),
        pay_loan_vs_invest_scenario(cfg, extra_monthly=extra, years=years),
        long_run_growth_scenario(cfg, monthly=monthly_invest),
    ]
    for sc in scenarios:
        st.markdown(f"#### {sc.title}")
        st.write(md_safe(sc.body))
        if sc.caveat:
            st.caption(md_safe(f"⚠ {sc.caveat}"))


def view_flow(cfg: PlannerConfig, s) -> None:
    st.subheader("Money Flow")
    st.caption("Annualized flow: income sources → cash pool → expenses / taxes / savings.")
    g = build_flow(cfg, s)
    st.graphviz_chart(to_dot(g))
    if any(e.flagged for e in g.edges):
        st.warning("⚠ Dashed red edge = under-the-table income: excluded from tax math, carries "
                   "legal/IRS risk, modeled as entered — not endorsed.")


def view_allocation(cfg: PlannerConfig, s, months: int) -> None:
    st.subheader("Monthly Fund Distribution")
    st.caption("Auto-suggested split of each month's surplus (priority: tax set-aside → emergency "
               "buffer → SEP → Roth → ETF/extra loan). Edit any cell to override.")
    remainder_to = st.radio("Send leftover surplus to:", ["etf", "extra_loan", "split"], horizontal=True)
    plan = suggest_allocation(cfg, s, remainder_to=remainder_to)
    for n in plan.notes:
        st.info(md_safe(n))

    base = pd.DataFrame([
        {"month": r.label, "surplus": round(r.surplus), **{b: round(r.buckets.get(b, 0.0)) for b in ALL_BUCKETS}}
        for r in plan.rows
    ])
    edited = st.data_editor(base, width="stretch", hide_index=True, key="alloc_editor")

    # Rebuild allocation rows from (possibly edited) table -> contributions -> runway impact.
    edited_rows = [
        AllocationRow(
            month_index=i, label=row["month"], surplus=row["surplus"],
            buckets={b: float(row[b]) for b in ALL_BUCKETS},
        )
        for i, row in edited.iterrows()
    ]
    contribs = contributions_from_schedule(edited_rows)
    led_with = build_ledger(cfg, months=months, start_date=cfg.severance.signing_date,
                            monthly_contributions=contribs)

    st.markdown("#### Annual totals (edited)")
    totals = {b: sum(r.buckets.get(b, 0.0) for r in edited_rows) for b in ALL_BUCKETS}
    cols = st.columns(len(ALL_BUCKETS))
    for col, b in zip(cols, ALL_BUCKETS):
        col.metric(b.replace("_", " ").title(), money(totals[b]))

    st.markdown("#### Runway impact of these contributions")
    c1, c2 = st.columns(2)
    c1.metric("Ending cash (with contributions)", money(led_with.ending_balance),
              delta=money(led_with.ending_balance - s.ending_cash_balance))
    runout = "Doesn't run out" if led_with.cash_runs_out_month is None else f"Month {led_with.cash_runs_out_month}"
    c2.metric("Cash runs out (with contributions)", runout)
    idf = pd.DataFrame([{"month": r.label, "balance": round(r.balance)} for r in led_with.rows])
    st.line_chart(idf, x="month", y="balance")


def main() -> None:
    st.set_page_config(page_title="Finance Transition Planner", layout="wide")
    st.title("Finance Transition Planner")
    cfg = _load().model_copy(deep=True)
    cfg, months = sidebar(cfg)
    s = build_summary(cfg, months=months, start_date=cfg.severance.signing_date or date.today())

    tabs = st.tabs(["Summary", "2026 Tax", "Runway", "Loan", "Scenarios", "Money Flow", "Allocation"])
    with tabs[0]:
        view_summary(s)
    with tabs[1]:
        view_tax(s)
    with tabs[2]:
        view_runway(s)
    with tabs[3]:
        view_loan(cfg)
    with tabs[4]:
        view_scenarios(cfg)
    with tabs[5]:
        view_flow(cfg, s)
    with tabs[6]:
        view_allocation(cfg, s, months)

    st.divider()
    st.caption(DISCLAIMER)


if __name__ == "__main__":
    main()
