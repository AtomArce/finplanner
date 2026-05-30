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


def _render_trace_body(tr: Traced, depth: int = 0) -> None:
    """Readable trace: formula, formula-with-numbers, an inputs table, the note, then children."""
    from finplanner.trace import _substitute

    if tr.formula and tr.formula != "0":
        st.markdown(md_safe(f"**Formula:** `{tr.label}` = {tr.formula}"))
        substituted = _substitute(tr.formula, tr.inputs)
        if substituted != tr.formula:
            st.markdown(md_safe(f"**With your numbers:** = {substituted} → **{tr.value:,.2f}**"))
    if tr.inputs:
        idf = pd.DataFrame(
            [{"input": k, "value": f"{v:,.2f}"} for k, v in tr.inputs.items()]
        )
        st.table(idf)
    if tr.note:
        flag = "⚠ " if tr.method == "approximation" else ""
        st.caption(md_safe(f"{flag}{tr.note}"))
    for child in tr.children:
        st.markdown(md_safe(f"**↳ {child.label}: {child.value:,.2f}**"))
        _render_trace_body(child, depth + 1)


def show_trace(tr: Traced) -> None:
    flag = " ⚠ approximation" if tr.method == "approximation" else ""
    with st.expander(f"{tr.label}: {tr.value:,.2f}{flag}"):
        _render_trace_body(tr)


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


def metric_with_trace(col, s, label: str, value_str: str, trace_key: str) -> None:
    """Render a metric and, directly beneath it, the 'where this comes from' trace expander."""
    col.metric(label, value_str)
    tr = s.traces.get(trace_key)
    if tr is not None:
        with col:
            show_trace(tr)


def view_summary(s) -> None:
    st.subheader("Consolidated Summary")
    st.caption("Each number shows **where it comes from** — expand the panel beneath it for the "
               "formula, your inputs, and any approximation notes.")

    # Refund vs. balance-due headline (the honest reframing of "tax due").
    bal = s.balance_due_or_refund
    if bal < 0:
        st.success(md_safe(f"Estimated **refund ≈ {money(-bal)}** at filing "
                           f"(severance withheld ≈ {money(s.severance_withheld)} vs. total tax "
                           f"{money(s.total_tax_due)})."))
    else:
        st.info(md_safe(f"Estimated **balance due ≈ {money(bal)}** at filing "
                        f"(total tax {money(s.total_tax_due)} − severance withheld "
                        f"{money(s.severance_withheld)}). Regular W-2 withholding not modeled."))

    c1, c2, c3 = st.columns(3)
    metric_with_trace(c1, s, "Monthly expenses", money(s.total_monthly_expenses), "monthly_expenses")
    metric_with_trace(c2, s, "Taxable income 2026", money(s.total_taxable_income_2026), "taxable_income_2026")
    metric_with_trace(c3, s, f"Total tax due {s.tax_due_date}", money(s.total_tax_due), "total_tax")
    metric_with_trace(c1, s, "NYC UBT", money(s.ubt), "ubt")
    metric_with_trace(c2, s, "Balance due / refund", money(s.balance_due_or_refund), "balance_due_or_refund")
    metric_with_trace(c3, s, "Set-aside ⚠ approx", money(s.set_aside), "set_aside")
    metric_with_trace(c1, s, "SEP contribution", money(s.sep_contribution), "sep_contribution")
    metric_with_trace(c2, s, "Roth contribution", money(s.roth_contribution), "roth_contribution")
    metric_with_trace(c3, s, "ETF contribution", money(s.etf_contribution), "etf_contribution")
    metric_with_trace(c1, s, "Ending cash", money(s.ending_cash_balance), "ending_cash")
    runout = "Doesn't run out" if s.cash_runs_out_month is None else f"Month {s.cash_runs_out_month}"
    metric_with_trace(c2, s, "Cash runs out", runout, "cash_runs_out")
    metric_with_trace(c3, s, "HYSA APY", f"{s.hysa_apy * 100:.2f}%", "hysa")

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

    with st.expander("⚠ Assumptions & approximations (read me)", expanded=False):
        st.markdown(md_safe(
            "- **\"Total tax due\" is the full liability on this income, not the balance after "
            "withholding.** The separate *balance due / refund* line subtracts severance "
            "withholding; your regular W-2-job withholding is **not** modeled, so your real "
            "balance due is lower.\n"
            "- **Severance** is modeled as **1/3 W-2 wages** (FICA + supplemental withholding) + "
            "**2/3 non-wage damages** (no withholding), per the documented agreement. Change this "
            "in code if your split differs.\n"
            "- **QBI** above ~$191,950 taxable income assumes **$0 W-2 wages paid by your business** "
            "(sole proprietor / no employees), so the deduction is wage-limited and phases to $0.\n"
            "- **NYC UBT** is a flat 4% on LLC net profit; the **resident credit** (offsets 23–100%) "
            "and the **NYC-202 loss-year NOL carryforward** are not modeled — real UBT is likely lower.\n"
            "- **Business losses** offset ordinary income (NY/NYC follow federal AGI), capped by the "
            "**§461(l)** excess-business-loss limit ($256,000 single, 2026).\n"
            "- **NY/NYC** start from federal AGI; NY-specific additions/subtractions and NYC credits "
            "are not modeled. The $200k NIIT / additional-Medicare thresholds are statutory (not indexed)."
        ))

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


def _alloc_column_config(plan):
    """Read-only month/surplus; editable, formatted, capped bucket columns with help text."""
    help_text = {
        "tax_set_aside": "Cash kept for the 2027 tax bill (NOT invested, not a runway drawdown).",
        "emergency_buffer": "Cash kept as your emergency buffer (not invested).",
        "sep_ira": f"Pre-tax retirement. Annual cap ≈ {money(plan.caps['sep_ira'])} (≈20% of net SE).",
        "roth_ira": f"Post-tax retirement. Annual cap ≈ {money(plan.caps['roth_ira'])} after MAGI phase-out.",
        "etf": "Taxable brokerage investing (post-tax).",
        "extra_loan": "Extra student-loan principal paydown.",
    }
    cfg_cols = {
        "month": st.column_config.TextColumn("month", disabled=True),
        "surplus": st.column_config.NumberColumn("surplus", disabled=True, format="$%d"),
    }
    for b in ALL_BUCKETS:
        cfg_cols[b] = st.column_config.NumberColumn(
            b.replace("_", " ").title(), min_value=0, format="$%d", help=help_text.get(b, ""),
        )
    return cfg_cols


def view_allocation(cfg: PlannerConfig, s, months: int) -> None:
    st.subheader("Monthly Fund Distribution")
    st.caption("Auto-suggested split of each month's surplus (priority: tax set-aside → emergency "
               "buffer → SEP → Roth → ETF/extra loan). Edit any cell to override; month & surplus "
               "are read-only.")

    top = st.columns([3, 1])
    with top[0]:
        remainder_to = st.radio("Send leftover surplus to:", ["etf", "extra_loan", "split"],
                                horizontal=True, key="alloc_remainder")
    with top[1]:
        if st.button("↺ Reset to suggestion", use_container_width=True):
            st.session_state.pop("alloc_editor", None)
            st.rerun()

    plan = suggest_allocation(cfg, s, remainder_to=remainder_to)
    for n in plan.notes:
        st.info(md_safe(n))

    base = pd.DataFrame([
        {"month": r.label, "surplus": round(r.surplus), **{b: round(r.buckets.get(b, 0.0)) for b in ALL_BUCKETS}}
        for r in plan.rows
    ])
    edited = st.data_editor(
        base, width="stretch", hide_index=True, key="alloc_editor",
        column_config=_alloc_column_config(plan),
    )

    edited_rows = [
        AllocationRow(
            month_index=i, label=row["month"], surplus=row["surplus"],
            buckets={b: float(row[b]) for b in ALL_BUCKETS},
        )
        for i, row in edited.iterrows()
    ]
    totals = {b: sum(r.buckets.get(b, 0.0) for r in edited_rows) for b in ALL_BUCKETS}

    # ── Validation: per-bucket caps + per-month surplus overflow ──────────────
    if totals["sep_ira"] > plan.caps["sep_ira"] + 1:
        st.error(md_safe(f"SEP IRA total {money(totals['sep_ira'])} exceeds the annual cap "
                         f"{money(plan.caps['sep_ira'])}."))
    if totals["roth_ira"] > plan.caps["roth_ira"] + 1:
        st.error(md_safe(f"Roth IRA total {money(totals['roth_ira'])} exceeds the annual cap "
                         f"{money(plan.caps['roth_ira'])}."))
    over_months = [r.label for r in edited_rows if sum(r.buckets.values()) > r.surplus + 0.5]
    if over_months:
        st.warning(md_safe(f"These months allocate more than their surplus: {', '.join(over_months)}. "
                           "You'd be drawing down existing cash in those months."))

    # ── Cap usage ─────────────────────────────────────────────────────────────
    st.markdown("#### Contribution caps")
    cc1, cc2 = st.columns(2)
    sep_pct = (totals["sep_ira"] / plan.caps["sep_ira"] * 100) if plan.caps["sep_ira"] > 0 else 0
    roth_pct = (totals["roth_ira"] / plan.caps["roth_ira"] * 100) if plan.caps["roth_ira"] > 0 else 0
    cc1.metric("SEP IRA used", f"{money(totals['sep_ira'])} / {money(plan.caps['sep_ira'])}",
               delta=f"{sep_pct:.0f}% of cap", delta_color="off")
    cc2.metric("Roth IRA used", f"{money(totals['roth_ira'])} / {money(plan.caps['roth_ira'])}",
               delta=f"{roth_pct:.0f}% of cap", delta_color="off")

    st.markdown("#### Annual totals (edited)")
    cols = st.columns(len(ALL_BUCKETS))
    for col, b in zip(cols, ALL_BUCKETS):
        col.metric(b.replace("_", " ").title(), money(totals[b]))

    # ── SEP → tax feedback: recompute the bill with the chosen SEP/Roth ──────
    cfg2 = cfg.model_copy(deep=True)
    cfg2.retirement_and_investing.sep_ira_annual_pretax = totals["sep_ira"]
    cfg2.retirement_and_investing.roth_ira_annual_posttax = totals["roth_ira"]
    s2 = build_summary(cfg2, months=months, start_date=cfg.severance.signing_date or date.today())

    st.markdown("#### Tax impact of these contributions")
    st.caption("SEP IRA is pre-tax, so a higher SEP lowers your tax bill and set-aside. "
               "Roth is post-tax and doesn't change your tax.")
    t1, t2, t3 = st.columns(3)
    t1.metric("Total tax due", money(s2.total_tax_due),
              delta=money(s2.total_tax_due - s.total_tax_due), delta_color="inverse")
    t2.metric("Balance due / refund", money(s2.balance_due_or_refund),
              delta=money(s2.balance_due_or_refund - s.balance_due_or_refund), delta_color="inverse")
    t3.metric("Set-aside ⚠ approx", money(s2.set_aside),
              delta=money(s2.set_aside - s.set_aside), delta_color="inverse")

    # ── Runway impact: contributions are cash outflows ────────────────────────
    contribs = contributions_from_schedule(edited_rows)
    led_with = build_ledger(cfg2, months=months, start_date=cfg.severance.signing_date,
                            monthly_contributions=contribs)
    st.markdown("#### Runway impact of these contributions")
    r1, r2 = st.columns(2)
    r1.metric("Ending cash (with contributions)", money(led_with.ending_balance),
              delta=money(led_with.ending_balance - s.ending_cash_balance))
    runout = "Doesn't run out" if led_with.cash_runs_out_month is None else f"Month {led_with.cash_runs_out_month}"
    r2.metric("Cash runs out (with contributions)", runout)
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
