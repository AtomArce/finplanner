"""Typed config mirroring state.json (SPEC §3). Pydantic v2.

Field names carry explicit _monthly / _annual units (SPEC §1A: no implicit monthly-vs-annual).
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Jurisdiction(BaseModel):
    state: str = "NY"
    city: str = "NYC"
    filing_status: Literal["single"] = "single"  # only single is modeled in v1


class Meta(BaseModel):
    schema_version: int = 1
    source: str = ""
    jurisdiction: Jurisdiction = Field(default_factory=Jurisdiction)
    tax_year: int = 2026


class Income(BaseModel):
    w2_earned_ytd_2026: float = 0.0
    freelance_taxable_monthly: float = 0.0
    freelance_under_table_monthly: float = 0.0  # spendable cash; EXCLUDED from all tax math
    freelance_months_remaining_2026: int = 6


class InstallmentTreatment(BaseModel):
    type: str
    withheld: bool = False
    taxable: bool = True


class SeveranceTaxTreatment(BaseModel):
    installment_1: InstallmentTreatment
    installment_2: InstallmentTreatment
    installment_3: InstallmentTreatment


class Severance(BaseModel):
    total_pretax: float = 0.0
    signing_date: Optional[date] = None  # None == "TBD" in state.json
    installment_offsets_days: list[int] = Field(default_factory=lambda: [45, 105, 135])
    split: str = "even_thirds"
    tax_treatment: SeveranceTaxTreatment

    @field_validator("signing_date", mode="before")
    @classmethod
    def _parse_tbd(cls, v):
        if v in (None, "", "TBD"):
            return None
        return v


class Expenses(BaseModel):
    rent_monthly: float = 0.0
    other_monthly: float = 0.0
    business_expense_monthly_deductible: float = 0.0
    business_expense_applies_months: int = 6


class StudentLoan(BaseModel):
    balance: float = 0.0
    monthly_payment: float = 0.0
    apr_percent: float = 0.0
    note: str = ""


class Debt(BaseModel):
    student_loan: StudentLoan = Field(default_factory=StudentLoan)


class RetirementInvesting(BaseModel):
    roth_ira_annual_posttax: float = 0.0
    sep_ira_annual_pretax: float = 0.0
    taxable_brokerage_etf_annual: float = 0.0
    starting_cash_excl_severance: float = 0.0
    age_50_or_older: bool = False  # drives catch-up eligibility
    business_is_sstb: bool = True  # most freelance/consulting is a specified-service trade


class Assumptions(BaseModel):
    investment_return_annual_percent: float = 7.0
    emergency_buffer_months: int = 6
    # Tax constants live in rates.py; these are kept only for reference/round-tripping state.json.
    standard_deduction_2026: float = 16_100
    ny_nyc_deduction_placeholder: float = 8_000
    se_tax_rate: float = 0.153
    se_taxable_factor: float = 0.9235
    qbi_rate: float = 0.20


class HysaPick(BaseModel):
    name: str
    apy: float


class CardPick(BaseModel):
    name: str
    rewards_pct: float
    apr: float
    annual_fee: float


class InstitutionPicks(BaseModel):
    checking: Optional[str] = None
    business_checking: Optional[str] = None
    hysa: Optional[HysaPick] = None
    roth_ira: Optional[str] = None
    sep_ira: Optional[str] = None
    brokerage: Optional[str] = None
    credit_card: Optional[CardPick] = None

    @field_validator("hysa", "credit_card", mode="before")
    @classmethod
    def _allow_null(cls, v):
        return v or None


class PlannerConfig(BaseModel):
    """Top-level config. Mirrors state.json one-to-one (minus _comment / _options_reference)."""

    meta: Meta = Field(default_factory=Meta)
    income: Income = Field(default_factory=Income)
    severance: Severance
    expenses: Expenses = Field(default_factory=Expenses)
    debt: Debt = Field(default_factory=Debt)
    retirement_and_investing: RetirementInvesting = Field(default_factory=RetirementInvesting)
    assumptions: Assumptions = Field(default_factory=Assumptions)
    institution_picks: InstitutionPicks = Field(default_factory=InstitutionPicks)
    checklist_tasks: list[str] = Field(default_factory=list)

    # ---- convenience derived inputs (computed once, read everywhere — SPEC §1A) ----

    @property
    def free_months(self) -> int:
        """Months the freelance income / business expense apply for in 2026."""
        return self.income.freelance_months_remaining_2026

    @property
    def freelance_taxable_annual(self) -> float:
        return self.income.freelance_taxable_monthly * self.free_months

    @property
    def freelance_under_table_annual(self) -> float:
        return self.income.freelance_under_table_monthly * self.free_months

    @property
    def bizexp_annual(self) -> float:
        """Standardized as bizexp_monthly * applies_months everywhere (fixes the v5 *12 bug)."""
        return (
            self.expenses.business_expense_monthly_deductible
            * self.expenses.business_expense_applies_months
        )

    @property
    def hysa_apy(self) -> float:
        return self.institution_picks.hysa.apy / 100.0 if self.institution_picks.hysa else 0.0

    @property
    def card_rewards_pct(self) -> float:
        cc = self.institution_picks.credit_card
        return cc.rewards_pct if cc else 0.0

    @property
    def card_annual_fee(self) -> float:
        cc = self.institution_picks.credit_card
        return cc.annual_fee if cc else 0.0
