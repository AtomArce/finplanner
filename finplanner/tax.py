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
    def business_net(self) -> float:
        """Signed Schedule C result: gross freelance minus business expense (can be negative = loss)."""
        return self.freelance_taxable_annual - self.bizexp_annual

    @property
    def se_net(self) -> float:
        """Net self-employment PROFIT for SE tax / QBI / SEP (a loss floors at $0)."""
        return max(0.0, self.business_net)


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
    ubt: Traced
    total_tax: Traced
    severance_withheld: Traced
    balance_due_or_refund: Traced

    def all_traced(self) -> list[Traced]:
        return [
            self.se_tax, self.half_se, self.agi, self.qbi_deduction,
            self.federal_taxable_income, self.federal_income_tax,
            self.addl_medicare, self.niit, self.ny_tax, self.nyc_tax, self.ubt,
            self.total_tax, self.severance_withheld, self.balance_due_or_refund,
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
        return Traced(0.0, "QBI deduction", "0", {}, note="no qualified business income (no SE profit)")

    # Below the threshold: full 20% for both SSTB and non-SSTB.
    if pre_qbi_ti <= threshold:
        return Traced(
            value=base,
            label="QBI deduction",
            formula="min(qbi_rate * se_net, qbi_rate * pre_qbi_ti)",
            inputs={"qbi_rate": r.qbi_rate, "se_net": inp.se_net, "pre_qbi_ti": pre_qbi_ti},
        )

    # Above the threshold, BOTH paths phase out to $0 across the band for this filer:
    #   - SSTB: statutory phase-out of the deduction itself.
    #   - non-SSTB: the W-2-wage/UBIA limit. We assume $0 W-2 wages paid by the business
    #     (sole proprietor / single-member LLC, no employees), so the limit is ~$0 and the
    #     deduction phases out on the same linear band.
    reason = "SSTB" if inp.business_is_sstb else "non-SSTB W-2 wage/UBIA limit (assumes $0 wages paid)"
    if pre_qbi_ti >= threshold + width:
        return Traced(
            value=0.0,
            label="QBI deduction",
            formula="0",
            inputs={},
            method="approximation",
            note=f"{reason}: fully phased out above taxable income {threshold + width:,.0f}",
        )
    allowed = 1.0 - (pre_qbi_ti - threshold) / width
    return Traced(
        value=base * allowed,
        label="QBI deduction",
        formula="base * (1 - (pre_qbi_ti - threshold) / width)",
        inputs={"base": base, "pre_qbi_ti": pre_qbi_ti, "threshold": threshold, "width": width},
        method="approximation",
        note=f"{reason}: partial phase-out across the {width:,.0f} band",
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
    # A business LOSS reduces AGI (offsets W-2/severance), but only up to the §461(l) cap;
    # any excess loss is carried forward as an NOL (not modeled here). A profit flows in full.
    business_for_agi = max(inp.business_net, -r.ebl_cap_single)
    loss_capped = inp.business_net < -r.ebl_cap_single
    agi_val = ordinary + business_for_agi + inp.taxable_interest - half_se.value - inp.sep_contrib
    agi_note = (
        "Severance modeled as 1/3 W-2 wages + 2/3 non-wage damages per the agreement. "
        "Roth contributions are post-tax and are NOT subtracted. "
        "A business loss offsets ordinary income (NY/NYC follow federal AGI)."
    )
    if loss_capped:
        agi_note += (f" Business loss exceeds the §461(l) cap ({r.ebl_cap_single:,.0f}); "
                     f"only that much offsets this year, the rest carries forward.")
    agi = Traced(
        value=agi_val,
        label="Adjusted gross income",
        formula="w2 + severance_total + business_for_agi + taxable_interest - half_se - sep_contrib",
        inputs={
            "w2": inp.w2_wages, "severance_total": inp.severance_total,
            "business_for_agi": business_for_agi,
            "taxable_interest": inp.taxable_interest, "half_se": half_se.value,
            "sep_contrib": inp.sep_contrib,
        },
        method="approximation" if loss_capped else "exact",
        note=agi_note,
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

    # NYC Unincorporated Business Tax — 4% on LLC net profit; $0 in a loss year.
    ubt_val = r.ubt_rate * inp.se_net  # se_net already floors a loss at 0
    ubt = Traced(
        value=ubt_val,
        label="NYC Unincorporated Business Tax (UBT)",
        formula="ubt_rate * max(0, business_net)",
        inputs={"ubt_rate": r.ubt_rate, "business_net": inp.business_net},
        method="approximation",
        note=("4% on LLC net profit; $0 in a loss year. The NYC resident credit (offsets ~23–100%) "
              "and the NYC-202 loss-year NOL carryforward are NOT modeled — your real UBT is likely lower."),
    )

    total_val = (fed_tax_val + se.value + ny_tax_val + nyc_tax_val + addl_med_val + niit_val + ubt_val)
    total = Traced(
        value=total_val,
        label="Total tax (fed + SE + NY + NYC + addl Medicare + NIIT + UBT)",
        formula="fed_tax + se_tax + ny_tax + nyc_tax + addl_medicare + niit + ubt",
        inputs={
            "fed_tax": fed_tax_val, "se_tax": se.value, "ny_tax": ny_tax_val,
            "nyc_tax": nyc_tax_val, "addl_medicare": addl_med_val, "niit": niit_val, "ubt": ubt_val,
        },
        note="Full liability on this income — NOT the balance due after withholding (see below).",
    )

    # Severance supplemental withholding (lump-sum flat rates) — only the W-2-wage installment is
    # withheld; the non-wage damages installments are not. Regular W-2-job withholding NOT modeled.
    supp_rate = r.fed_supplemental_rate + r.ny_supplemental_rate + r.nyc_supplemental_rate
    withheld_val = inp.severance_wages * supp_rate
    severance_withheld = Traced(
        value=withheld_val,
        label="Severance withholding (already paid)",
        formula="severance_wages * (fed_supp + ny_supp + nyc_supp)",
        inputs={"severance_wages": inp.severance_wages, "fed_supp": r.fed_supplemental_rate,
                "ny_supp": r.ny_supplemental_rate, "nyc_supp": r.nyc_supplemental_rate},
        method="approximation",
        note=(f"Flat supplemental withholding (~{supp_rate*100:.1f}%) on the W-2-wage severance "
              "installment only. Regular W-2-job withholding is NOT modeled, so real withholding "
              "is higher and your balance due is lower than shown."),
    )
    balance_val = total_val - withheld_val
    balance_due_or_refund = Traced(
        value=balance_val,
        label="Estimated balance due at filing (negative = refund)",
        formula="total_tax - severance_withheld",
        inputs={"total_tax": total_val, "severance_withheld": withheld_val},
        method="approximation",
        note=("Positive = you owe at filing; negative = refund. Business losses lower total tax, "
              "which is how over-withheld severance comes back as a refund."),
    )

    return TaxResult(
        se_tax=se, half_se=half_se, agi=agi, qbi_deduction=qbi,
        federal_taxable_income=fed_ti, federal_income_tax=fed_tax,
        addl_medicare=addl_medicare, niit=niit, ny_tax=ny_tax, nyc_tax=nyc_tax, ubt=ubt,
        total_tax=total, severance_withheld=severance_withheld,
        balance_due_or_refund=balance_due_or_refund,
    )
