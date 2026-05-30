"""Severance installment schedule + withheld/unwithheld split + set-aside (SPEC §4.1, §4.5).

User-specified treatment (PROCESS_LOG decision 4): installment 1 = W-2 wages (withheld);
installments 2 & 3 = non-wage damages (taxable for fed/NY/NYC, NO withholding). This is why
the set-aside is large. Exact treatment depends on settlement language — confirm with a CPA.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .rates import YearRates
from .tax import TaxInputs, compute_tax
from .trace import Traced

SUPPLEMENTAL_WAGE_RATE = 0.22  # typical federal withholding on supplemental wages


@dataclass
class Installment:
    index: int  # 1-based
    pay_date: date | None  # None if signing_date unknown ("TBD")
    amount: float
    kind: str  # "w2_wages" | "damages_non_wage"
    withheld: bool


def schedule(
    total: float,
    signing_date: date | None,
    offsets_days: list[int],
    withheld_flags: list[bool] | None = None,
) -> list[Installment]:
    """3 even installments (total/3) at signing_date + offsets. Installment 1 = wages."""
    n = len(offsets_days)
    each = total / n
    if withheld_flags is None:
        withheld_flags = [i == 0 for i in range(n)]  # only first installment withheld
    out = []
    for i, off in enumerate(offsets_days):
        out.append(
            Installment(
                index=i + 1,
                pay_date=(signing_date + timedelta(days=off)) if signing_date else None,
                amount=each,
                kind="w2_wages" if i == 0 else "damages_non_wage",
                withheld=withheld_flags[i],
            )
        )
    return out


def wages_total(installments: list[Installment]) -> float:
    return sum(i.amount for i in installments if i.kind == "w2_wages")


def damages_total(installments: list[Installment]) -> float:
    return sum(i.amount for i in installments if i.kind == "damages_non_wage")


def estimate_set_aside(
    inp: TaxInputs,
    r: YearRates,
    w2_withholding_estimate: float = 0.0,
) -> Traced:
    """Cash to set aside for the unwithheld tax bill (SPEC §4.5, improved method).

    set_aside = total_tax - estimated_withholding, where withholding =
    W-2 withholding (caller-supplied, default 0) + 22% supplemental rate on installment-1 wages.
    Approximation: real withholding depends on the W-4 and actual paystubs.
    """
    total_tax = compute_tax(inp, r).total_tax.value
    inst1_withholding = inp.severance_wages * SUPPLEMENTAL_WAGE_RATE
    withholding = w2_withholding_estimate + inst1_withholding
    set_aside = max(0.0, total_tax - withholding)
    return Traced(
        value=set_aside,
        label="Recommended tax set-aside",
        formula="max(0, total_tax - (w2_withholding + 0.22 * severance_wages))",
        inputs={
            "total_tax": total_tax,
            "w2_withholding": w2_withholding_estimate,
            "severance_wages": inp.severance_wages,
        },
        method="approximation",
        note=("withholding estimated as W-2 withholding + 22% supplemental rate on installment 1; "
              "damages installments 2 & 3 have NO withholding. Confirm with a CPA. Quarterly "
              "estimated payments likely required."),
    )
