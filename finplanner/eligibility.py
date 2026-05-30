"""Eligibility / limit checks -> warnings (SPEC §1B, §4.9).

Encodes the rules the prototype let the user violate: Roth cap + MAGI phase-out, SEP limit
from net SE, QBI SSTB phase-out. Returns warnings so the UI can surface them and (optionally)
clamp the input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .rates import YearRates

Severity = Literal["info", "warning", "error"]


@dataclass
class Warning_:
    field: str
    severity: Severity
    message: str
    suggested_value: float | None = None


def roth_allowed(magi: float, age_50_or_older: bool, r: YearRates) -> float:
    """Max allowed Roth contribution after the MAGI phase-out (single filer)."""
    cap = r.roth_ira_limit + (r.roth_ira_catchup_50plus if age_50_or_older else 0.0)
    start, end = r.roth_phaseout_start_single, r.roth_phaseout_end_single
    if magi <= start:
        return cap
    if magi >= end:
        return 0.0
    return cap * (1.0 - (magi - start) / (end - start))


def sep_max(se_net: float, r: YearRates) -> float:
    """Max SEP contribution ≈ 20% of net SE after the ½-SE-tax adjustment, capped at additions limit."""
    half_se = se_net * 0.9235 * 0.153 / 2.0
    adjusted_net = max(0.0, se_net - half_se)
    return min(adjusted_net * 0.20, r.sep_additions_limit)


def roth_limit(
    contribution: float,
    magi: float,
    age_50_or_older: bool,
    r: YearRates,
) -> list[Warning_]:
    """Hard cap + MAGI phase-out for single filers (SPEC §1B)."""
    out: list[Warning_] = []
    cap = r.roth_ira_limit + (r.roth_ira_catchup_50plus if age_50_or_older else 0.0)
    start, end = r.roth_phaseout_start_single, r.roth_phaseout_end_single
    allowed = roth_allowed(magi, age_50_or_older, r)

    if contribution > cap:
        out.append(Warning_(
            "roth_ira_annual_posttax", "error",
            f"Roth contribution {contribution:,.0f} exceeds the {r.year} limit of {cap:,.0f}.",
            suggested_value=cap,
        ))
    if allowed < cap and contribution > allowed:
        if allowed == 0.0:
            out.append(Warning_(
                "roth_ira_annual_posttax", "error",
                f"MAGI {magi:,.0f} is above the Roth phase-out ceiling ({end:,.0f}); direct Roth "
                f"contributions are not allowed. Consider a backdoor Roth.",
                suggested_value=0.0,
            ))
        else:
            out.append(Warning_(
                "roth_ira_annual_posttax", "warning",
                f"MAGI {magi:,.0f} is in the Roth phase-out range; allowed contribution is reduced "
                f"to ~{allowed:,.0f}.",
                suggested_value=round(allowed, 2),
            ))
    return out


def sep_limit(contribution: float, se_net: float, r: YearRates) -> list[Warning_]:
    """SEP max ≈ 20% of net SE after the ½-SE-tax adjustment, capped at the additions limit."""
    max_sep = sep_max(se_net, r)
    out: list[Warning_] = []
    if contribution > max_sep + 1:
        if se_net <= 0:
            msg = (
                f"A SEP IRA contribution of {contribution:,.0f} isn't allowed with $0 net "
                f"self-employment income. A SEP is a RETIREMENT contribution capped at ~20% of "
                f"your net SE earnings (1099/freelance profit) — it is NOT a business expense. "
                f"Deductible business purchases through the LLC are a SEPARATE lever that lowers "
                f"taxable income directly (the 'business expense' input). With freelance income at "
                f"$0, your SEP room is $0; it opens up once you have SE profit."
            )
        else:
            msg = (
                f"SEP contribution {contribution:,.0f} exceeds the estimated max of ~{max_sep:,.0f} "
                f"for net SE earnings of {se_net:,.0f} (≈20% of adjusted net, capped at "
                f"{r.sep_additions_limit:,.0f}). A SEP is a retirement contribution tied to SE "
                f"profit — distinct from deductible business expenses, which lower taxable income "
                f"directly."
            )
        out.append(Warning_("sep_ira_annual_pretax", "warning", msg, suggested_value=round(max_sep, 2)))
    return out


def qbi_sstb(pre_qbi_taxable_income: float, is_sstb: bool, r: YearRates) -> list[Warning_]:
    """Warn when an SSTB is in or above the QBI phase-out band (SPEC §1B)."""
    if not is_sstb:
        return []
    start = r.qbi_threshold_single
    end = start + r.qbi_phaseout_width_single
    if pre_qbi_taxable_income >= end:
        return [Warning_(
            "qbi", "warning",
            f"Specified-service business with taxable income {pre_qbi_taxable_income:,.0f} is above "
            f"the QBI phase-out ceiling ({end:,.0f}); the QBI deduction is $0.",
            suggested_value=0.0,
        )]
    if pre_qbi_taxable_income > start:
        return [Warning_(
            "qbi", "info",
            f"Specified-service business is in the QBI phase-out range ({start:,.0f}–{end:,.0f}); "
            f"the deduction is partially reduced.",
        )]
    return []
