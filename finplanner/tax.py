"""Tax engine: SE tax, federal income tax, QBI, NY, NYC, NIIT, additional Medicare.

Every output is a Traced value (SPEC §2). Fixes the prototype's gaps (SPEC §1B / §4):
two-tier SE tax with the SS wage cap, QBI SSTB phase-out, NIIT, additional Medicare,
real NY/NYC brackets.

NOT advice — see finplanner.DISCLAIMER. Simplifications are flagged inline as
`method="approximation"` in the trace.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rates import YearRates, tax_from_brackets
from .trace import Traced


@dataclass
class TaxInputs:
    """All amounts annual, USD. Single filer, NY/NYC resident (v1 scope)."""

    w2_wages: float = 0.0  # W-2 box-1 wages YTD (subject to SS/Medicare)
    severance_wages: float = 0.0  # installment 1 — W-2 wages (SS/Medicare apply)
    severance_damages: float = 0.0  # installments 2 & 3 — taxable income, NOT wages
    freelance_taxable_annual: float = 0.0  # gross freelance "over the table"
    bizexp_annual: float = 0.0  # deductible business expense
    taxable_interest: float = 0.0  # HYSA etc. (investment income for NIIT)
    sep_contrib: float = 0.0  # pre-tax SEP IRA (reduces AGI, NOT SE tax)
    roth_contrib: float = 0.0  # post-tax — affects NOTHING here (kept for clarity)
    business_is_sstb: bool = True

    @property
    def severance_total(self) -> float:
        return self.severance_wages + self.severance_damages

    @property
    def se_net(self) -> float:
        """Net self-employment profit (Schedule C): gross freelance minus business expense."""
        return max(0.0, self.freelance_taxable_annual - self.bizexp_annual)


@dataclass
class TaxResult:
    se_tax: Traced
    half_se: Traced
    agi: Traced
    qbi_deduction: Traced
    federal_taxable_income: Traced
    federal_income_tax: Traced
    addl_medicare: Traced
    niit: Traced
    ny_tax: Traced
    nyc_tax: Traced
    total_tax: Traced

    def all_traced(self) -> list[Traced]:
        return [
            self.se_tax, self.half_se, self.agi, self.qbi_deduction,
            self.federal_taxable_income, self.federal_income_tax,
            self.addl_medicare, self.niit, self.ny_tax, self.nyc_tax, self.total_tax,
        ]

    def explain(self) -> str:
        return "\n".join(t.explain() for t in self.all_traced())


def _se_tax(inp: TaxInputs, r: YearRates) -> Traced:
    """Two-tier SE tax with SS wage-base cap (SPEC §4.2 fix)."""
    se_base = inp.se_net * r.se_taxable_factor
    other_ss_wages = inp.w2_wages + inp.severance_wages  # already consumed SS base
    ss_room = max(0.0, r.ss_wage_base - other_ss_wages)
    ss_taxed = min(se_base, ss_room)
    ss_part = ss_taxed * r.ss_rate
    medi_part = se_base * r.medicare_rate

    ss = Traced(
        value=ss_part,
        label="SE Social Security portion",
        formula="min(se_base, ss_room) * ss_rate",
        inputs={"se_base": se_base, "ss_room": ss_room, "ss_rate": r.ss_rate},
        note=f"SS wage base {r.ss_wage_base:,.0f} less {other_ss_wages:,.0f} W-2/wage income already taxed",
    )
    medi = Traced(
        value=medi_part,
        label="SE Medicare portion",
        formula="se_base * medicare_rate",
        inputs={"se_base": se_base, "medicare_rate": r.medicare_rate},
    )
    return Traced(
        value=ss_part + medi_part,
        label="Self-employment tax",
        formula="ss_part + medi_part",
        inputs={"ss_part": ss_part, "medi_part": medi_part},
        children=[ss, medi],
    )


def _qbi(inp: TaxInputs, pre_qbi_ti: float, r: YearRates) -> Traced:
    """QBI (§199A) with SSTB phase-out (SPEC §1B / §4.3 fix)."""
    base = min(r.qbi_rate * inp.se_net, r.qbi_rate * pre_qbi_ti)
    threshold = r.qbi_threshold_single
    width = r.qbi_phaseout_width_single

    if inp.se_net <= 0:
        return Traced(0.0, "QBI deduction", "0", {}, note="no qualified business income")

    if not inp.business_is_sstb:
        # Non-SSTB above the threshold is limited by W-2 wages/UBIA, which we don't model.
        return Traced(
            value=base,
            label="QBI deduction",
            formula="min(qbi_rate * se_net, qbi_rate * pre_qbi_ti)",
            inputs={"qbi_rate": r.qbi_rate, "se_net": inp.se_net, "pre_qbi_ti": pre_qbi_ti},
            method="approximation" if pre_qbi_ti > threshold else "exact",
            note=("non-SSTB above threshold: W-2 wage/UBIA limit not modeled, full 20% assumed"
                  if pre_qbi_ti > threshold else ""),
        )

    # SSTB: full below threshold, linear phase-out across the band, zero above.
    if pre_qbi_ti <= threshold:
        return Traced(
            value=base,
            label="QBI deduction",
            formula="min(qbi_rate * se_net, qbi_rate * pre_qbi_ti)",
            inputs={"qbi_rate": r.qbi_rate, "se_net": inp.se_net, "pre_qbi_ti": pre_qbi_ti},
        )
    if pre_qbi_ti >= threshold + width:
        return Traced(
            value=0.0,
            label="QBI deduction",
            formula="0",
            inputs={},
            note=f"SSTB fully phased out above taxable income {threshold + width:,.0f}",
        )
    allowed = 1.0 - (pre_qbi_ti - threshold) / width
    return Traced(
        value=base * allowed,
        label="QBI deduction",
        formula="base * (1 - (pre_qbi_ti - threshold) / width)",
        inputs={"base": base, "pre_qbi_ti": pre_qbi_ti, "threshold": threshold, "width": width},
        note="SSTB partial phase-out",
    )


def compute_tax(inp: TaxInputs, r: YearRates) -> TaxResult:
    se = _se_tax(inp, r)
    half_se = Traced(
        value=se.value / 2.0,
        label="½ SE tax (above-the-line deduction)",
        formula="se_tax / 2",
        inputs={"se_tax": se.value},
        children=[se],
    )

    ordinary = inp.w2_wages + inp.severance_total
    agi_val = ordinary + inp.se_net + inp.taxable_interest - half_se.value - inp.sep_contrib
    agi = Traced(
        value=agi_val,
        label="Adjusted gross income",
        formula="w2 + severance_total + se_net + taxable_interest - half_se - sep_contrib",
        inputs={
            "w2": inp.w2_wages, "severance_total": inp.severance_total, "se_net": inp.se_net,
            "taxable_interest": inp.taxable_interest, "half_se": half_se.value,
            "sep_contrib": inp.sep_contrib,
        },
        note="Roth contributions are post-tax and are NOT subtracted",
    )

    pre_qbi_ti = max(0.0, agi_val - r.federal_std_deduction_single)
    qbi = _qbi(inp, pre_qbi_ti, r)
    fed_ti_val = max(0.0, pre_qbi_ti - qbi.value)
    fed_ti = Traced(
        value=fed_ti_val,
        label="Federal taxable income",
        formula="max(0, agi - std_deduction - qbi)",
        inputs={"agi": agi_val, "std_deduction": r.federal_std_deduction_single, "qbi": qbi.value},
        children=[qbi],
    )
    fed_tax_val = tax_from_brackets(fed_ti_val, r.federal_brackets)
    fed_tax = Traced(
        value=fed_tax_val,
        label="Federal income tax",
        formula="brackets(fed_ti, FEDERAL_2026)",
        inputs={"fed_ti": fed_ti_val},
        note="progressive 2026 single brackets (see rates.py)",
        children=[fed_ti],
    )

    # Additional Medicare 0.9% on earned income (wages + SE base) over $200k.
    medicare_earned = inp.w2_wages + inp.severance_wages + inp.se_net * r.se_taxable_factor
    addl_med_val = max(0.0, medicare_earned - r.addl_medicare_threshold_single) * r.addl_medicare_rate
    addl_medicare = Traced(
        value=addl_med_val,
        label="Additional Medicare tax",
        formula="max(0, medicare_earned - threshold) * 0.009",
        inputs={"medicare_earned": medicare_earned, "threshold": r.addl_medicare_threshold_single},
        note="0.9% on wages + SE earnings above $200k (statutory, not indexed)",
    )

    # NIIT 3.8% on the lesser of investment income or (MAGI - $200k). MAGI ≈ AGI here.
    niit_base = max(0.0, min(inp.taxable_interest, agi_val - r.niit_threshold_single))
    niit_val = niit_base * r.niit_rate
    niit = Traced(
        value=niit_val,
        label="Net investment income tax",
        formula="min(taxable_interest, max(0, agi - threshold)) * 0.038",
        inputs={"taxable_interest": inp.taxable_interest, "agi": agi_val,
                "threshold": r.niit_threshold_single},
        note="3.8% on investment income above $200k MAGI (statutory, not indexed)",
    )

    # NY / NYC — start from federal AGI (NY modifications not modeled), apply NY std deduction.
    ny_ti_val = max(0.0, agi_val - r.ny_std_deduction_single)
    ny_tax_val = tax_from_brackets(ny_ti_val, r.ny_brackets_single)
    ny_tax = Traced(
        value=ny_tax_val,
        label="NY State income tax",
        formula="brackets(max(0, agi - ny_std_deduction), NY_2026)",
        inputs={"agi": agi_val, "ny_std_deduction": r.ny_std_deduction_single},
        method="approximation",
        note="uses federal AGI as NY base (NY-specific additions/subtractions not modeled)",
    )
    nyc_tax_val = tax_from_brackets(ny_ti_val, r.nyc_brackets_single)
    nyc_tax = Traced(
        value=nyc_tax_val,
        label="NYC resident income tax",
        formula="brackets(max(0, agi - ny_std_deduction), NYC_2026)",
        inputs={"agi": agi_val, "ny_std_deduction": r.ny_std_deduction_single},
        method="approximation",
        note="NYC resident brackets on NY taxable income; NYC credits not modeled",
    )

    total_val = (fed_tax_val + se.value + ny_tax_val + nyc_tax_val + addl_med_val + niit_val)
    total = Traced(
        value=total_val,
        label="Total tax (fed + SE + NY + NYC + addl Medicare + NIIT)",
        formula="fed_tax + se_tax + ny_tax + nyc_tax + addl_medicare + niit",
        inputs={
            "fed_tax": fed_tax_val, "se_tax": se.value, "ny_tax": ny_tax_val,
            "nyc_tax": nyc_tax_val, "addl_medicare": addl_med_val, "niit": niit_val,
        },
    )

    return TaxResult(
        se_tax=se, half_se=half_se, agi=agi, qbi_deduction=qbi,
        federal_taxable_income=fed_ti, federal_income_tax=fed_tax,
        addl_medicare=addl_medicare, niit=niit, ny_tax=ny_tax, nyc_tax=nyc_tax,
        total_tax=total,
    )
