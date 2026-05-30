"""Single source of truth for tax brackets, deductions, and limits — versioned by year.

Adding 2027 should be a data change here, NOT a code change elsewhere.

All 2026 constants below were web-verified on 2026-05-28 against the sources noted.
Re-verify before relying on them for a new tax year.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bracket:
    """A marginal tax bracket: `rate` applies to income above `floor` (up to the next floor)."""

    floor: float
    rate: float


def tax_from_brackets(taxable: float, brackets: list[Bracket]) -> float:
    """Progressive tax: sum of (rate × income falling in each band). Brackets sorted by floor."""
    taxable = max(0.0, taxable)
    total = 0.0
    ordered = sorted(brackets, key=lambda b: b.floor)
    for i, b in enumerate(ordered):
        upper = ordered[i + 1].floor if i + 1 < len(ordered) else float("inf")
        if taxable <= b.floor:
            break
        band = min(taxable, upper) - b.floor
        total += band * b.rate
    return total


@dataclass(frozen=True)
class YearRates:
    year: int

    # Federal — IRS Rev. Proc. 2025-32, verified 2026-05-28 (Tax Foundation, IRS).
    federal_brackets: list[Bracket]
    federal_std_deduction_single: float  # $16,100 (2026, OBBBA), verified 2026-05-28 (SSA/IRS COLA).

    # Self-employment / payroll.
    ss_wage_base: float  # $184,500 (2026), verified 2026-05-28 (SSA).
    ss_rate: float  # 12.4% SE (employer+employee), statutory.
    medicare_rate: float  # 2.9% SE, statutory.
    se_taxable_factor: float  # 0.9235 = (1 - 7.65%), net-SE adjustment.
    addl_medicare_rate: float  # 0.9%, statutory.
    addl_medicare_threshold_single: float  # $200,000, statutory (NOT inflation-indexed).

    # Net Investment Income Tax — statutory $200k single, NOT indexed.
    niit_rate: float  # 3.8%
    niit_threshold_single: float  # $200,000

    # QBI (§199A) — OBBBA 2026, verified 2026-05-28.
    qbi_rate: float  # 20%
    qbi_threshold_single: float  # $191,950 full deduction below this (SSTB).
    qbi_phaseout_width_single: float  # $75,000 phase-out band (fully gone at threshold + width).

    # Retirement limits — IRS Notice 2025-67, verified 2026-05-28.
    roth_ira_limit: float  # $7,500 (2026).
    roth_ira_catchup_50plus: float  # +$1,100.
    roth_phaseout_start_single: float  # $153,000 MAGI.
    roth_phaseout_end_single: float  # $168,000 MAGI.
    sep_additions_limit: float  # $72,000 (2026) overall additions cap.

    # NY State — verified 2026-05-28.
    ny_brackets_single: list[Bracket]
    ny_std_deduction_single: float  # $8,000.

    # NYC resident — verified 2026-05-28.
    nyc_brackets_single: list[Bracket]


RATES_2026 = YearRates(
    year=2026,
    # https://taxfoundation.org/data/all/federal/2026-tax-brackets/ (IRS Rev. Proc. 2025-32)
    federal_brackets=[
        Bracket(0, 0.10),
        Bracket(11_925, 0.12),
        Bracket(48_475, 0.22),
        Bracket(103_350, 0.24),
        Bracket(197_300, 0.32),
        Bracket(250_525, 0.35),
        Bracket(626_350, 0.37),
    ],
    federal_std_deduction_single=16_100,
    ss_wage_base=184_500,
    ss_rate=0.124,
    medicare_rate=0.029,
    se_taxable_factor=0.9235,
    addl_medicare_rate=0.009,
    addl_medicare_threshold_single=200_000,
    niit_rate=0.038,
    niit_threshold_single=200_000,
    qbi_rate=0.20,
    qbi_threshold_single=191_950,
    qbi_phaseout_width_single=75_000,
    roth_ira_limit=7_500,
    roth_ira_catchup_50plus=1_100,
    roth_phaseout_start_single=153_000,
    roth_phaseout_end_single=168_000,
    sep_additions_limit=72_000,
    # https://www.nerdwallet.com/taxes/learn/new-york-state-tax (NY DTF 2026)
    ny_brackets_single=[
        Bracket(0, 0.04),
        Bracket(17_150, 0.045),
        Bracket(23_600, 0.0525),
        Bracket(27_900, 0.0585),
        Bracket(161_550, 0.0625),
        Bracket(323_200, 0.0685),
        Bracket(2_155_350, 0.0965),
        Bracket(5_000_000, 0.103),
        Bracket(25_000_000, 0.109),
    ],
    ny_std_deduction_single=8_000,
    # https://reedcorp.tax/new-york-2026-tax-brackets/ (NYC resident single)
    nyc_brackets_single=[
        Bracket(0, 0.03078),
        Bracket(12_000, 0.03762),
        Bracket(25_000, 0.03819),
        Bracket(50_000, 0.03876),
    ],
)


RATES_BY_YEAR: dict[int, YearRates] = {2026: RATES_2026}


def rates_for(year: int) -> YearRates:
    if year not in RATES_BY_YEAR:
        raise ValueError(
            f"No rate table for tax year {year}. Add a YearRates entry in rates.py "
            f"(verify constants against IRS/NY sources first). Available: {sorted(RATES_BY_YEAR)}"
        )
    return RATES_BY_YEAR[year]
