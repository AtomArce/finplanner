"""`python -m finplanner` CLI. Loads state.json and renders the views as text.

Every command prints the not-advice disclaimer (SPEC §6 criterion 7).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import DISCLAIMER
from .io import load_config
from .scenarios import all_scenarios
from .summary import build_summary

DEFAULT_STATE = "state.json"


def _money(x: float) -> str:
    return f"${x:,.2f}"


def cmd_summary(args) -> None:
    cfg = load_config(args.state)
    s = build_summary(cfg, months=args.months)
    print("=== Consolidated Summary ===")
    print(f"Total monthly expenses:   {_money(s.total_monthly_expenses)}")
    print(f"Annual expenses:          {_money(s.annual_expenses)}")
    print(f"Taxable income 2026:      {_money(s.total_taxable_income_2026)}")
    print(f"Total tax due {s.tax_due_date}: {_money(s.total_tax_due)}  (full liability, pre-withholding)")
    print(f"  incl. NYC UBT:          {_money(s.ubt)}")
    print(f"Severance withheld:       {_money(s.severance_withheld)}")
    bal = s.balance_due_or_refund
    label = "Balance due at filing" if bal >= 0 else "Estimated REFUND"
    print(f"{label+':':<26}{_money(abs(bal))}")
    print(f"Recommended set-aside:    {_money(s.set_aside)}  (approximation)")
    print(f"Roth / SEP / ETF contrib: {_money(s.roth_contribution)} / {_money(s.sep_contribution)} / {_money(s.etf_contribution)}")
    print(f"HYSA APY:                 {s.hysa_apy * 100:.2f}%")
    print(f"Ending cash balance:      {_money(s.ending_cash_balance)}")
    runout = "does not run out" if s.cash_runs_out_month is None else f"month {s.cash_runs_out_month}"
    print(f"Cash runs out:            {runout}")
    if s.warnings:
        print("\n--- Eligibility warnings ---")
        for w in s.warnings:
            sv = "" if w.suggested_value is None else f"  (suggested: {w.suggested_value:,.2f})"
            print(f"  [{w.severity}] {w.field}: {w.message}{sv}")
    print(f"\n{DISCLAIMER}")


def cmd_tax(args) -> None:
    cfg = load_config(args.state)
    s = build_summary(cfg, months=args.months)
    print(s.tax.explain())
    print(f"\n{DISCLAIMER}")


def cmd_ledger(args) -> None:
    cfg = load_config(args.state)
    s = build_summary(cfg, months=args.months)
    hdr = f"{'month':<8}{'income':>12}{'expense':>12}{'interest':>12}{'balance':>14}"
    print(hdr)
    print("-" * len(hdr))
    for r in s.ledger.rows:
        print(f"{r.label:<8}{r.income_total:>12,.0f}{r.expense_total:>12,.0f}"
              f"{r.hysa_interest_in:>12,.2f}{r.balance:>14,.0f}")
    print(f"\n{DISCLAIMER}")


def cmd_scenarios(args) -> None:
    cfg = load_config(args.state)
    for sc in all_scenarios(cfg):
        print(f"\n## {sc.title}\n{sc.body}")
        if sc.caveat:
            print(f"  ⚠ {sc.caveat}")
    print(f"\n{DISCLAIMER}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="finplanner", description="Traceable finance transition planner")
    p.add_argument("--state", default=DEFAULT_STATE, type=Path, help="path to state.json")
    p.add_argument("--months", default=12, type=int, help="runway horizon in months")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("summary").set_defaults(func=cmd_summary)
    sub.add_parser("tax").set_defaults(func=cmd_tax)
    sub.add_parser("ledger").set_defaults(func=cmd_ledger)
    sub.add_parser("scenarios").set_defaults(func=cmd_scenarios)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
