"""Typed, non-calculating contract for a future Canadian payroll engine.

This module validates the shape and exactness of inputs and outputs only. It
contains no payroll formulas, calculation routines, or routing behavior.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal, TypeAlias, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

SUPPORTED_PROVINCES = ("AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "SK")
SUPPORTED_WORKER_CATEGORIES = ("part_time_hourly", "full_time_hourly", "salaried")
SUPPORTED_FREQUENCIES = ("daily", "weekly", "biweekly", "semi_monthly", "monthly")

ProvinceCode: TypeAlias = Literal["AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "SK"]
WorkerCategory: TypeAlias = Literal["part_time_hourly", "full_time_hourly", "salaried"]
PayFrequency: TypeAlias = Literal["daily", "weekly", "biweekly", "semi_monthly", "monthly"]
PayrollResultStatus: TypeAlias = Literal["calculated", "blocked", "invalid_input"]

NonBlankReference: TypeAlias = Annotated[
    str, StringConstraints(strip_whitespace=True, strict=True, min_length=1)
]


def _parse_exact_decimal(value: object) -> Decimal:
    """Accept Decimal or a decimal string, never a binary floating-point value."""
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, str):
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("amount must be a valid decimal string") from exc
    else:
        raise ValueError("amount must be a Decimal or decimal string; floats are not accepted")
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    return amount


PayrollAmount: TypeAlias = Annotated[Decimal, BeforeValidator(_parse_exact_decimal)]


class ContractModel(BaseModel):
    """Immutable, closed-schema base for contract records."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class PayrollBlockReasonCode(str, Enum):
    UNSUPPORTED_JURISDICTION = "unsupported_jurisdiction"
    FEDERALLY_REGULATED_EMPLOYMENT = "federally_regulated_employment"
    CROSS_PROVINCE_PERIOD = "cross_province_period"
    MISSING_REVIEWED_COMPONENT = "missing_reviewed_component"
    MISSING_QUALIFIED_ATTESTATION = "missing_qualified_attestation"
    MISSING_EMPLOYER_CONFIGURATION = "missing_employer_configuration"
    UNRESOLVED_SOURCE_CURRENCY = "unresolved_source_currency"
    UNREVIEWED_RULE_BUNDLE = "unreviewed_rule_bundle"
    INVALID_PAY_PERIOD = "invalid_pay_period"
    OTHER = "other"


class PayPeriod(ContractModel):
    """Inclusive work period and its actual pay date."""

    start_date: date
    end_date: date
    pay_date: date

    @model_validator(mode="after")
    def end_is_not_before_start(self):
        if self.end_date < self.start_date:
            raise ValueError("period start must be on or before its end")
        return self


class ReviewedDataReference(ContractModel):
    """Reference to employee data that has a recorded review."""

    reference_id: NonBlankReference
    review_status: Literal["reviewed"]
    review_attestation_reference: NonBlankReference
    reviewed_at: date


class EmployeeProvinceAssignment(ContractModel):
    """Employee-specific province-of-employment assignment, inclusive dates."""

    province: ProvinceCode
    effective_from: date
    effective_to: date

    @model_validator(mode="after")
    def end_is_not_before_start(self):
        if self.effective_to < self.effective_from:
            raise ValueError("province assignment end must not precede its start")
        return self


class PriorYtdBasis(ContractModel):
    """Prior year-to-date amount retained separately for one contribution or earnings base."""

    basis_code: NonBlankReference
    amount: PayrollAmount
    accumulated_through: date


class EarningFact(ContractModel):
    """An itemized earning fact supplied to a future calculator."""

    fact_reference: NonBlankReference
    earning_code: NonBlankReference
    amount: PayrollAmount
    source_reference: NonBlankReference
    basis_codes: tuple[NonBlankReference, ...] = ()


class EmployerConfigurationReferences(ContractModel):
    """Employer-specific reviewed setup references when a levy/WCB applies."""

    employer_levy_references: tuple[ReviewedDataReference, ...] = ()
    workers_compensation_references: tuple[ReviewedDataReference, ...] = ()


class CanadianPayrollRequest(ContractModel):
    """Input contract; it records facts and references without calculating pay."""

    company_reference: NonBlankReference
    company_country: Literal["CA"]
    currency: Literal["CAD"]
    employee_reference: NonBlankReference
    worker_category: WorkerCategory
    pay_frequency: PayFrequency
    pay_period: PayPeriod
    employee_province_assignments: tuple[EmployeeProvinceAssignment, ...] = Field(
        min_length=1
    )
    employee_tax_election_reference: ReviewedDataReference
    employee_eligibility_reference: ReviewedDataReference
    earning_facts: tuple[EarningFact, ...] = ()
    prior_ytd_by_basis: tuple[PriorYtdBasis, ...] = ()
    employer_configuration_references: EmployerConfigurationReferences = Field(
        default_factory=EmployerConfigurationReferences
    )

    @model_validator(mode="after")
    def validate_assignment_coverage_and_ytd_bases(self):
        period_start = self.pay_period.start_date
        period_end = self.pay_period.end_date
        relevant = sorted(
            (
                assignment
                for assignment in self.employee_province_assignments
                if assignment.effective_to >= period_start
                and assignment.effective_from <= period_end
            ),
            key=lambda assignment: assignment.effective_from,
        )
        if not relevant or relevant[0].effective_from > period_start:
            raise ValueError(
                "employee province assignments must cover the full inclusive pay period"
            )

        covered_through = relevant[0].effective_to
        if covered_through < period_start:
            raise ValueError(
                "employee province assignments must cover the full inclusive pay period"
            )
        for assignment in relevant[1:]:
            if assignment.effective_from <= covered_through:
                raise ValueError("employee province assignments must not overlap")
            if assignment.effective_from > covered_through + timedelta(days=1):
                raise ValueError(
                    "employee province assignments must cover the full inclusive pay period"
                )
            covered_through = assignment.effective_to
        if covered_through < period_end:
            raise ValueError(
                "employee province assignments must cover the full inclusive pay period"
            )

        basis_codes = tuple(basis.basis_code for basis in self.prior_ytd_by_basis)
        if len(basis_codes) != len(set(basis_codes)):
            raise ValueError("prior YTD bases must have distinct basis codes")
        return self


class ComponentProvenance(ContractModel):
    """Required component-level rule/source and qualified-review provenance."""

    component_reference: NonBlankReference
    rule_bundle_reference: NonBlankReference
    rule_reference: NonBlankReference
    source_references: tuple[NonBlankReference, ...] = Field(min_length=1)
    qualified_review_attestation_reference: NonBlankReference
    reviewer_qualification_reference: NonBlankReference


class EarningBasisOutput(ContractModel):
    basis_code: NonBlankReference
    amount: PayrollAmount
    provenance: ComponentProvenance


class EarningOutput(ContractModel):
    earning_code: NonBlankReference
    amount: PayrollAmount
    bases: tuple[EarningBasisOutput, ...] = ()
    provenance: ComponentProvenance


class EmployeeDeductionOutput(ContractModel):
    deduction_code: NonBlankReference
    amount: PayrollAmount
    provenance: ComponentProvenance


class EmployerContributionOutput(ContractModel):
    contribution_code: NonBlankReference
    amount: PayrollAmount
    provenance: ComponentProvenance


class ApprovedEmployerLevyOutput(ContractModel):
    levy_code: NonBlankReference
    amount: PayrollAmount
    employer_configuration_reference: NonBlankReference
    approval_reference: NonBlankReference
    provenance: ComponentProvenance


class PayrollTotals(ContractModel):
    gross_earnings: PayrollAmount
    employee_deductions: PayrollAmount
    employer_contributions: PayrollAmount
    approved_employer_levies: PayrollAmount
    net_pay: PayrollAmount
    total_employer_cost: PayrollAmount


class JurisdictionSnapshot(ContractModel):
    """Immutable effective-dated jurisdiction snapshot recorded with a result."""

    province: ProvinceCode
    effective_from: date
    effective_to: date
    snapshot_reference: NonBlankReference

    @model_validator(mode="after")
    def end_is_not_before_start(self):
        if self.effective_to < self.effective_from:
            raise ValueError("jurisdiction snapshot end must not precede its start")
        return self


class RuleSnapshot(ContractModel):
    """Immutable identity for the exact reviewed rule bundle applied."""

    rule_bundle_reference: NonBlankReference
    version_reference: NonBlankReference
    content_digest: NonBlankReference
    effective_pay_date: date


class CalculatedPayrollResult(ContractModel):
    status: Literal["calculated"]
    result_reference: NonBlankReference
    employee_reference: NonBlankReference
    currency: Literal["CAD"]
    pay_period: PayPeriod
    earnings: tuple[EarningOutput, ...] = Field(min_length=1)
    employee_deductions: tuple[EmployeeDeductionOutput, ...] = ()
    employer_contributions: tuple[EmployerContributionOutput, ...] = ()
    approved_employer_levies: tuple[ApprovedEmployerLevyOutput, ...] = ()
    totals: PayrollTotals
    jurisdiction_snapshot: JurisdictionSnapshot
    rule_snapshots: tuple[RuleSnapshot, ...] = Field(min_length=1)
    warnings: tuple[NonBlankReference, ...] = ()
    block_reasons: tuple[PayrollBlockReasonCode, ...] = ()

    @model_validator(mode="after")
    def every_component_is_backed_by_its_rule_snapshot(self):
        snapshots_by_bundle = {
            snapshot.rule_bundle_reference for snapshot in self.rule_snapshots
        }
        provenances = [earning.provenance for earning in self.earnings]
        for earning in self.earnings:
            provenances.extend(basis.provenance for basis in earning.bases)
        for component in (
            *self.employee_deductions,
            *self.employer_contributions,
            *self.approved_employer_levies,
        ):
            provenances.append(component.provenance)
        if any(
            provenance.rule_bundle_reference not in snapshots_by_bundle
            for provenance in provenances
        ):
            raise ValueError("every component provenance must match a rule snapshot")
        return self


class BlockedPayrollResult(ContractModel):
    status: Literal["blocked"]
    reason_codes: tuple[PayrollBlockReasonCode, ...] = Field(min_length=1)
    warnings: tuple[NonBlankReference, ...] = ()
    jurisdiction_snapshot: JurisdictionSnapshot | None = None
    rule_snapshots: tuple[RuleSnapshot, ...] = ()


class InvalidInputPayrollResult(ContractModel):
    status: Literal["invalid_input"]
    reason_codes: tuple[PayrollBlockReasonCode, ...] = Field(min_length=1)
    warnings: tuple[NonBlankReference, ...] = ()


CanadianPayrollResult: TypeAlias = Annotated[
    Union[CalculatedPayrollResult, BlockedPayrollResult, InvalidInputPayrollResult],
    Field(discriminator="status"),
]
