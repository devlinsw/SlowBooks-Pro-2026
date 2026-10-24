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
CompanyPayrollCountry: TypeAlias = Literal["CA", "US"]
EmploymentRegulatoryScope: TypeAlias = Literal["provincial", "federal"]
EmployerRequirement: TypeAlias = Literal["employer_levy", "workers_compensation"]
EffectiveDateBasis: TypeAlias = Literal["pay_date", "full_pay_period"]

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
    OTHER = "other"


class InvalidInputReasonCode(str, Enum):
    """Closed reasons for malformed or incomplete raw input, not policy blocks."""

    INVALID_PAY_PERIOD = "invalid_pay_period"
    UNCOVERED_JURISDICTION_HISTORY = "uncovered_jurisdiction_history"
    MALFORMED_INPUT = "malformed_input"
    MISSING_INPUT = "missing_input"


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


def _require_effective_window_coverage(
    effective_from, effective_to, date_basis, pay_period, subject
):
    if effective_from is None or effective_to is None or date_basis is None:
        raise ValueError(f"{subject} has no reviewed effective-date basis/window")
    if date_basis == "pay_date":
        required_from = required_to = pay_period.pay_date
    else:
        required_from = pay_period.start_date
        required_to = pay_period.end_date
    if effective_from > required_from or effective_to < required_to:
        raise ValueError(
            f"{subject} effective window must cover the declared {date_basis} dates"
        )


class ReviewedDataReference(ContractModel):
    """Reference to employee data that has a recorded review."""

    reference_id: NonBlankReference
    review_status: Literal["reviewed"]
    review_attestation_reference: NonBlankReference
    reviewed_at: date


class CompanyPayrollCountryAssignment(ContractModel):
    """Company payroll-country assignment, with inclusive effective dates."""

    country: CompanyPayrollCountry
    effective_from: date
    effective_to: date

    @model_validator(mode="after")
    def end_is_not_before_start(self):
        if self.effective_to < self.effective_from:
            raise ValueError("company country assignment end must not precede its start")
        return self


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


def _covered_assignments(assignments, period_start, period_end, subject):
    relevant = sorted(
        (
            assignment
            for assignment in assignments
            if assignment.effective_to >= period_start
            and assignment.effective_from <= period_end
        ),
        key=lambda assignment: assignment.effective_from,
    )
    if not relevant or relevant[0].effective_from > period_start:
        raise ValueError(f"{subject} assignments must cover the full inclusive pay period")

    covered_through = relevant[0].effective_to
    if covered_through < period_start:
        raise ValueError(f"{subject} assignments must cover the full inclusive pay period")
    for assignment in relevant[1:]:
        if assignment.effective_from <= covered_through:
            raise ValueError(f"{subject} assignments must not overlap")
        if assignment.effective_from > covered_through + timedelta(days=1):
            raise ValueError(f"{subject} assignments must cover the full inclusive pay period")
        covered_through = assignment.effective_to
    if covered_through < period_end:
        raise ValueError(f"{subject} assignments must cover the full inclusive pay period")
    return relevant


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


class EmployerConfigurationSnapshot(ContractModel):
    """Immutable employer configuration with reviewed date-basis metadata."""

    employer_configuration_reference: NonBlankReference
    snapshot_reference: NonBlankReference
    version_reference: NonBlankReference
    content_digest: NonBlankReference
    review_attestation_reference: NonBlankReference
    reviewer_qualification_reference: NonBlankReference
    effective_from: date | None = None
    effective_to: date | None = None
    effective_date_basis: EffectiveDateBasis | None = None
    applicability_review_attestation_reference: NonBlankReference | None = None
    applicability_reviewer_qualification_reference: NonBlankReference | None = None

    @model_validator(mode="after")
    def effective_window_is_ordered(self):
        metadata = (
            self.effective_from,
            self.effective_to,
            self.effective_date_basis,
            self.applicability_review_attestation_reference,
            self.applicability_reviewer_qualification_reference,
        )
        if (
            self.effective_from is None
            or self.effective_to is None
            or self.effective_date_basis is None
            or self.applicability_review_attestation_reference is None
            or self.applicability_reviewer_qualification_reference is None
        ):
            if all(value is None for value in metadata):
                return self
            raise ValueError(
                "employer configuration effective-date window, basis, and qualified "
                "applicability review references must be supplied together"
            )
        if self.effective_to < self.effective_from:
            raise ValueError("employer configuration snapshot end must not precede its start")
        return self


class EmployerRequirementApplicability(ContractModel):
    """Date-bounded reviewed evidence for one levy or workers' compensation requirement."""

    requirement: EmployerRequirement
    decision: Literal["applicable", "reviewed_not_applicable"]
    review_attestation_reference: NonBlankReference | None = None
    reviewer_qualification_reference: NonBlankReference | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    effective_date_basis: EffectiveDateBasis | None = None
    employer_configuration_snapshot: EmployerConfigurationSnapshot | None = None

    @model_validator(mode="after")
    def decision_has_required_evidence(self):
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("employer applicability decision end must not precede its start")
        if self.decision == "applicable" and self.employer_configuration_snapshot is None:
            raise ValueError("applicable employer requirement needs reviewed employer configuration")
        if (
            self.decision == "reviewed_not_applicable"
            and self.employer_configuration_snapshot is not None
        ):
            raise ValueError("reviewed not-applicable decision must not carry employer configuration")
        return self


class EmployerConfigurationReferences(ContractModel):
    """Explicit reviewed applicability decisions for every represented requirement."""

    applicability_decisions: tuple[EmployerRequirementApplicability, ...] = Field(
        min_length=2
    )

    @model_validator(mode="after")
    def every_requirement_has_one_decision(self):
        requirements = tuple(item.requirement for item in self.applicability_decisions)
        if len(requirements) != 2 or set(requirements) != {
            "employer_levy",
            "workers_compensation",
        }:
            raise ValueError(
                "employer levy and workers compensation each need exactly one applicability decision"
            )
        return self


class CanadianPayrollRequest(ContractModel):
    """Input contract; it records facts and references without calculating pay."""

    request_reference: NonBlankReference
    company_reference: NonBlankReference
    company_payroll_country_assignments: tuple[CompanyPayrollCountryAssignment, ...] = Field(
        min_length=1
    )
    currency: Literal["CAD"]
    employee_reference: NonBlankReference
    worker_category: WorkerCategory
    pay_frequency: PayFrequency
    employment_regulatory_scope: EmploymentRegulatoryScope
    pay_period: PayPeriod
    employee_province_assignments: tuple[EmployeeProvinceAssignment, ...] = Field(
        min_length=1
    )
    employee_tax_election_reference: ReviewedDataReference
    employee_eligibility_reference: ReviewedDataReference
    earning_facts: tuple[EarningFact, ...] = ()
    prior_ytd_by_basis: tuple[PriorYtdBasis, ...] = ()
    employer_configuration_references: EmployerConfigurationReferences

    @model_validator(mode="after")
    def validate_assignment_coverage_and_ytd_bases(self):
        period_start = self.pay_period.start_date
        period_end = self.pay_period.end_date
        _covered_assignments(
            self.company_payroll_country_assignments,
            period_start,
            period_end,
            "company country",
        )
        _covered_assignments(
            self.employee_province_assignments,
            period_start,
            period_end,
            "employee province",
        )

        basis_codes = tuple(basis.basis_code for basis in self.prior_ytd_by_basis)
        if len(basis_codes) != len(set(basis_codes)):
            raise ValueError("prior YTD bases must have distinct basis codes")
        return self


class SourceSnapshot(ContractModel):
    """Exact source identity and qualified review of its effective-date basis."""

    source_reference: NonBlankReference
    snapshot_reference: NonBlankReference
    version_reference: NonBlankReference
    content_digest: NonBlankReference
    effective_from: date | None = None
    effective_to: date | None = None
    effective_date_basis: EffectiveDateBasis | None = None
    applicability_review_attestation_reference: NonBlankReference | None = None
    applicability_reviewer_qualification_reference: NonBlankReference | None = None

    @model_validator(mode="after")
    def effective_window_is_ordered(self):
        metadata = (
            self.effective_from,
            self.effective_to,
            self.effective_date_basis,
            self.applicability_review_attestation_reference,
            self.applicability_reviewer_qualification_reference,
        )
        if (
            self.effective_from is None
            or self.effective_to is None
            or self.effective_date_basis is None
            or self.applicability_review_attestation_reference is None
            or self.applicability_reviewer_qualification_reference is None
        ):
            if all(value is None for value in metadata):
                return self
            raise ValueError(
                "source effective-date window, basis, and qualified applicability "
                "review references must be supplied together"
            )
        if self.effective_to < self.effective_from:
            raise ValueError("source snapshot end must not precede its start")
        return self


class ComponentProvenance(ContractModel):
    """Exact rule/source identities and qualified review for one output component."""

    component_reference: NonBlankReference
    rule_bundle_reference: NonBlankReference
    rule_snapshot_reference: NonBlankReference
    rule_version_reference: NonBlankReference
    rule_content_digest: NonBlankReference
    rule_reference: NonBlankReference
    source_snapshots: tuple[SourceSnapshot, ...] = Field(min_length=1)
    qualified_review_attestation_reference: NonBlankReference
    reviewer_qualification_reference: NonBlankReference

    @model_validator(mode="after")
    def source_snapshots_are_unique(self):
        references = tuple(snapshot.snapshot_reference for snapshot in self.source_snapshots)
        if len(references) != len(set(references)):
            raise ValueError("component source snapshot references must be unique")
        return self


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
    """Generic statutory employer contribution, closed to CPP, CPP2, and EI."""

    contribution_category: Literal["CPP", "CPP2", "EI"]
    amount: PayrollAmount
    provenance: ComponentProvenance


class ApprovedEmployerLevyOutput(ContractModel):
    levy_code: NonBlankReference
    amount: PayrollAmount
    employer_configuration_reference: NonBlankReference
    employer_configuration_snapshot_reference: NonBlankReference
    approval_reference: NonBlankReference
    provenance: ComponentProvenance


class ApprovedWorkersCompensationOutput(ContractModel):
    """Explicit WCB output, separate from unlinked generic contributions."""

    workers_compensation_code: NonBlankReference
    amount: PayrollAmount
    employer_configuration_reference: NonBlankReference
    employer_configuration_snapshot_reference: NonBlankReference
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
    snapshot_reference: NonBlankReference
    version_reference: NonBlankReference
    content_digest: NonBlankReference
    effective_pay_date: date
    qualified_review_attestation_reference: NonBlankReference
    reviewer_qualification_reference: NonBlankReference
    source_snapshots: tuple[SourceSnapshot, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def source_snapshots_are_unique(self):
        references = tuple(snapshot.snapshot_reference for snapshot in self.source_snapshots)
        if len(references) != len(set(references)):
            raise ValueError("rule source snapshot references must be unique")
        return self


class CalculatedPayrollResult(ContractModel):
    status: Literal["calculated"]
    request_reference: NonBlankReference
    result_reference: NonBlankReference
    employee_reference: NonBlankReference
    currency: Literal["CAD"]
    pay_period: PayPeriod
    earnings: tuple[EarningOutput, ...] = Field(min_length=1)
    employee_deductions: tuple[EmployeeDeductionOutput, ...] = ()
    employer_contributions: tuple[EmployerContributionOutput, ...] = ()
    approved_employer_levies: tuple[ApprovedEmployerLevyOutput, ...] = ()
    approved_workers_compensation: tuple[ApprovedWorkersCompensationOutput, ...] = ()
    totals: PayrollTotals
    jurisdiction_snapshot: JurisdictionSnapshot
    rule_snapshots: tuple[RuleSnapshot, ...] = Field(min_length=1)
    warnings: tuple[NonBlankReference, ...] = ()

    @model_validator(mode="after")
    def every_component_is_backed_by_its_rule_snapshot(self):
        snapshots_by_reference = {
            snapshot.snapshot_reference: snapshot for snapshot in self.rule_snapshots
        }
        if len(snapshots_by_reference) != len(self.rule_snapshots):
            raise ValueError("rule snapshot references must be unique")
        bundle_references = tuple(
            snapshot.rule_bundle_reference for snapshot in self.rule_snapshots
        )
        if len(bundle_references) != len(set(bundle_references)):
            raise ValueError("a result may carry only one snapshot per rule bundle")

        provenances = [earning.provenance for earning in self.earnings]
        for earning in self.earnings:
            provenances.extend(basis.provenance for basis in earning.bases)
        for component in (
            *self.employee_deductions,
            *self.employer_contributions,
            *self.approved_employer_levies,
            *self.approved_workers_compensation,
        ):
            provenances.append(component.provenance)

        for snapshot in self.rule_snapshots:
            for source_snapshot in snapshot.source_snapshots:
                _require_effective_window_coverage(
                    source_snapshot.effective_from,
                    source_snapshot.effective_to,
                    source_snapshot.effective_date_basis,
                    self.pay_period,
                    "source snapshot",
                )

        for provenance in provenances:
            snapshot = snapshots_by_reference.get(provenance.rule_snapshot_reference)
            if snapshot is None:
                raise ValueError("every component must identify an exact rule snapshot")
            if (
                provenance.rule_bundle_reference != snapshot.rule_bundle_reference
                or provenance.rule_version_reference != snapshot.version_reference
                or provenance.rule_content_digest != snapshot.content_digest
                or provenance.qualified_review_attestation_reference
                != snapshot.qualified_review_attestation_reference
                or provenance.reviewer_qualification_reference
                != snapshot.reviewer_qualification_reference
            ):
                raise ValueError("component provenance must match its exact rule snapshot")
            if any(
                source not in snapshot.source_snapshots
                for source in provenance.source_snapshots
            ):
                raise ValueError(
                    "component source snapshots must match sources on its exact rule snapshot"
                )
            if snapshot.effective_pay_date != self.pay_period.pay_date:
                raise ValueError("rule snapshot pay date must match the result pay date")
        return self


class BlockedPayrollResult(ContractModel):
    status: Literal["blocked"]
    request_reference: NonBlankReference
    reason_codes: tuple[PayrollBlockReasonCode, ...] = Field(min_length=1)
    warnings: tuple[NonBlankReference, ...] = ()
    jurisdiction_snapshot: JurisdictionSnapshot | None = None
    rule_snapshots: tuple[RuleSnapshot, ...] = ()


class InvalidInputPayrollResult(ContractModel):
    status: Literal["invalid_input"]
    request_reference: NonBlankReference
    reason_codes: tuple[InvalidInputReasonCode, ...] = Field(min_length=1)
    warnings: tuple[NonBlankReference, ...] = ()


CanadianPayrollResult: TypeAlias = Annotated[
    Union[CalculatedPayrollResult, BlockedPayrollResult, InvalidInputPayrollResult],
    Field(discriminator="status"),
]


class CanadianPayrollEvaluation(ContractModel):
    """Bind typed requests or raw-input outcomes by their request/correlation reference."""

    request: CanadianPayrollRequest | None = None
    result: CanadianPayrollResult

    @model_validator(mode="after")
    def result_matches_request_and_supported_context(self):
        request = self.request
        result = self.result
        if request is None:
            if result.status == "invalid_input":
                return self
            if result.status == "blocked" and set(result.reason_codes) == {
                PayrollBlockReasonCode.UNSUPPORTED_JURISDICTION
            }:
                return self
            raise ValueError(
                "request-less results are limited to invalid input or unsupported jurisdiction"
            )

        if result.request_reference != request.request_reference:
            raise ValueError("result request reference must match the bound request reference")
        if result.status == "invalid_input":
            raise ValueError("invalid input cannot be paired with a valid typed request")

        country_assignments = _covered_assignments(
            request.company_payroll_country_assignments,
            request.pay_period.start_date,
            request.pay_period.end_date,
            "company country",
        )
        province_assignments = _covered_assignments(
            request.employee_province_assignments,
            request.pay_period.start_date,
            request.pay_period.end_date,
            "employee province",
        )
        countries = {assignment.country for assignment in country_assignments}
        provinces = {assignment.province for assignment in province_assignments}

        required_blockers = set()
        if request.employment_regulatory_scope == "federal":
            required_blockers.add(PayrollBlockReasonCode.FEDERALLY_REGULATED_EMPLOYMENT)
        if countries != {"CA"}:
            required_blockers.add(PayrollBlockReasonCode.UNSUPPORTED_JURISDICTION)
        if len(provinces) != 1:
            required_blockers.add(PayrollBlockReasonCode.CROSS_PROVINCE_PERIOD)

        if result.status == "calculated":
            if PayrollBlockReasonCode.FEDERALLY_REGULATED_EMPLOYMENT in required_blockers:
                raise ValueError("federally regulated employment must be blocked")
            if PayrollBlockReasonCode.UNSUPPORTED_JURISDICTION in required_blockers:
                raise ValueError("company country outside Canada must be blocked")
            if PayrollBlockReasonCode.CROSS_PROVINCE_PERIOD in required_blockers:
                raise ValueError("cross-province request must be blocked")
            if result.employee_reference != request.employee_reference:
                raise ValueError("calculated result employee must match the request")
            if result.currency != request.currency or result.pay_period != request.pay_period:
                raise ValueError("calculated result period and currency must match the request")

            province = next(iter(provinces))
            snapshot = result.jurisdiction_snapshot
            if snapshot.province != province:
                raise ValueError("calculated result jurisdiction must match the request province")
            if (
                snapshot.effective_from > request.pay_period.start_date
                or snapshot.effective_to < request.pay_period.end_date
            ):
                raise ValueError("jurisdiction snapshot must cover the complete request period")
            self._validate_employer_outputs(request, result)
            return self

        if required_blockers:
            if result.status != "blocked":
                raise ValueError("unsupported request context must produce a blocked result")
            missing = required_blockers.difference(result.reason_codes)
            if missing:
                raise ValueError("blocked result must include the request's required block reason")
        return self

    @staticmethod
    def _validate_employer_outputs(request, result):
        decisions = {
            decision.requirement: decision
            for decision in request.employer_configuration_references.applicability_decisions
        }
        output_groups = {
            "employer_levy": result.approved_employer_levies,
            "workers_compensation": result.approved_workers_compensation,
        }
        for requirement, outputs in output_groups.items():
            decision = decisions[requirement]
            if (
                decision.review_attestation_reference is None
                or decision.reviewer_qualification_reference is None
                or decision.effective_from is None
                or decision.effective_to is None
                or decision.effective_date_basis is None
            ):
                raise ValueError(
                    "employer applicability decision requires qualified review and "
                    "effective-date evidence"
                )
            _require_effective_window_coverage(
                decision.effective_from,
                decision.effective_to,
                decision.effective_date_basis,
                request.pay_period,
                "employer applicability decision",
            )
            if decision.decision == "reviewed_not_applicable":
                if outputs:
                    raise ValueError(
                        f"reviewed not-applicable {requirement} must not have an output"
                    )
                continue

            configuration = decision.employer_configuration_snapshot
            if configuration is None:
                raise ValueError(f"applicable {requirement} has no reviewed configuration")
            _require_effective_window_coverage(
                configuration.effective_from,
                configuration.effective_to,
                configuration.effective_date_basis,
                request.pay_period,
                "employer configuration snapshot",
            )
            for output in outputs:
                if (
                    output.employer_configuration_reference
                    != configuration.employer_configuration_reference
                    or output.employer_configuration_snapshot_reference
                    != configuration.snapshot_reference
                ):
                    raise ValueError(
                        f"{requirement} output must reference the request's exact configuration snapshot"
                    )
            if not outputs:
                label = "employer levy" if requirement == "employer_levy" else "workers compensation"
                raise ValueError(f"applicable {label} requires a calculated output")
