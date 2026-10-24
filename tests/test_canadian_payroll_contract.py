from datetime import date
from decimal import Decimal
from typing import get_args, get_origin

import pytest
from pydantic import BeforeValidator, TypeAdapter, ValidationError

from app.schemas.canadian_payroll_contract import (
    SUPPORTED_FREQUENCIES,
    SUPPORTED_PROVINCES,
    SUPPORTED_WORKER_CATEGORIES,
    ApprovedEmployerLevyOutput,
    BlockedPayrollResult,
    CalculatedPayrollResult,
    CanadianPayrollRequest,
    CanadianPayrollResult,
    ComponentProvenance,
    EarningFact,
    EmployeeProvinceAssignment,
    EmployerConfigurationReferences,
    EarningBasisOutput,
    EarningOutput,
    EmployeeDeductionOutput,
    EmployerContributionOutput,
    InvalidInputPayrollResult,
    JurisdictionSnapshot,
    PayrollAmount,
    PayrollBlockReasonCode,
    PayrollTotals,
    PayFrequency,
    PayPeriod,
    PriorYtdBasis,
    ProvinceCode,
    ReviewedDataReference,
    RuleSnapshot,
    WorkerCategory,
)


def make_reviewed_reference(reference_id="reviewed-record"):
    return ReviewedDataReference(
        reference_id=reference_id,
        review_status="reviewed",
        review_attestation_reference="review-attestation",
        reviewed_at=date(2026, 5, 1),
    )


def make_request(*, assignments=None, **overrides):
    values = {
        "company_reference": "company-record",
        "company_country": "CA",
        "currency": "CAD",
        "employee_reference": "employee-record",
        "worker_category": "part_time_hourly",
        "pay_frequency": "weekly",
        "pay_period": PayPeriod(
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 7),
            pay_date=date(2026, 5, 12),
        ),
        "employee_province_assignments": (
            EmployeeProvinceAssignment(
                province="AB",
                effective_from=date(2026, 5, 1),
                effective_to=date(2026, 5, 7),
            ),
        )
        if assignments is None
        else assignments,
        "employee_tax_election_reference": make_reviewed_reference("tax-election"),
        "employee_eligibility_reference": make_reviewed_reference("eligibility"),
        "earning_facts": (),
        "prior_ytd_by_basis": (),
        "employer_configuration_references": EmployerConfigurationReferences(),
    }
    values.update(overrides)
    return CanadianPayrollRequest(**values)


def test_scope_aliases_accept_only_supported_canadian_values():
    assert SUPPORTED_PROVINCES == ("AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "SK")
    assert SUPPORTED_WORKER_CATEGORIES == (
        "part_time_hourly",
        "full_time_hourly",
        "salaried",
    )
    assert SUPPORTED_FREQUENCIES == (
        "daily",
        "weekly",
        "biweekly",
        "semi_monthly",
        "monthly",
    )

    province_adapter = TypeAdapter(ProvinceCode)
    worker_adapter = TypeAdapter(WorkerCategory)
    frequency_adapter = TypeAdapter(PayFrequency)
    for province in SUPPORTED_PROVINCES:
        assert province_adapter.validate_python(province) == province
    for category in SUPPORTED_WORKER_CATEGORIES:
        assert worker_adapter.validate_python(category) == category
    for frequency in SUPPORTED_FREQUENCIES:
        assert frequency_adapter.validate_python(frequency) == frequency

    for unsupported in ("QC", "YT", "NT", "NU", "CA-FED", "ZZ"):
        with pytest.raises(ValidationError):
            province_adapter.validate_python(unsupported)


def test_request_carries_company_employee_and_reviewed_period_context():
    cross_province_assignments = (
        EmployeeProvinceAssignment(
            province="AB",
            effective_from=date(2026, 5, 1),
            effective_to=date(2026, 5, 3),
        ),
        EmployeeProvinceAssignment(
            province="BC",
            effective_from=date(2026, 5, 4),
            effective_to=date(2026, 5, 7),
        ),
    )
    request = make_request(assignments=cross_province_assignments)

    assert request.company_country == "CA"
    assert request.currency == "CAD"
    assert request.employee_reference == "employee-record"
    assert request.employee_tax_election_reference.review_status == "reviewed"
    assert request.employee_eligibility_reference.review_status == "reviewed"
    assert request.employer_configuration_references.employer_levy_references == ()
    assert request.employer_configuration_references.workers_compensation_references == ()
    assert request.pay_period.start_date == date(2026, 5, 1)
    assert request.pay_period.end_date == date(2026, 5, 7)
    assert request.pay_period.pay_date == date(2026, 5, 12)
    assert tuple(a.province for a in request.employee_province_assignments) == ("AB", "BC")

    blocked = TypeAdapter(CanadianPayrollResult).validate_python(
        {
            "status": "blocked",
            "reason_codes": [PayrollBlockReasonCode.CROSS_PROVINCE_PERIOD.value],
        }
    )
    assert isinstance(blocked, BlockedPayrollResult)
    assert blocked.reason_codes == (PayrollBlockReasonCode.CROSS_PROVINCE_PERIOD,)
    assert not hasattr(blocked, "totals")


def test_request_rejects_uncovered_employee_province_period():
    assignments = (
        EmployeeProvinceAssignment(
            province="AB",
            effective_from=date(2026, 5, 2),
            effective_to=date(2026, 5, 7),
        ),
    )

    with pytest.raises(ValidationError, match="cover"):
        make_request(assignments=assignments)


def test_request_rejects_non_canadian_company_currency_and_unreviewed_data():
    with pytest.raises(ValidationError):
        make_request(company_country="US")
    with pytest.raises(ValidationError):
        make_request(currency="USD")
    with pytest.raises(ValidationError):
        make_request(
            employee_tax_election_reference=ReviewedDataReference(
                reference_id="tax-election",
                review_status="unreviewed",
                review_attestation_reference="review-record",
                reviewed_at=date(2026, 5, 1),
            )
        )


def test_prior_ytd_is_keyed_by_distinct_contribution_or_earnings_basis():
    annotation = CanadianPayrollRequest.model_fields["prior_ytd_by_basis"].annotation
    assert get_origin(annotation) is tuple
    assert get_args(annotation)[0] is PriorYtdBasis


def test_all_money_uses_exact_decimal_and_rejects_binary_float_values():
    assert get_args(PayrollAmount)[0] is Decimal
    with pytest.raises(ValidationError):
        TypeAdapter(PayrollAmount).validate_python(float("nan"))

    for model in (
        PriorYtdBasis,
        EarningFact,
        EarningBasisOutput,
        EarningOutput,
        EmployeeDeductionOutput,
        EmployerContributionOutput,
        ApprovedEmployerLevyOutput,
    ):
        amount_field = model.model_fields["amount"]
        assert amount_field.annotation is Decimal
        assert any(isinstance(item, BeforeValidator) for item in amount_field.metadata)
    for field_name in PayrollTotals.model_fields:
        amount_field = PayrollTotals.model_fields[field_name]
        assert amount_field.annotation is Decimal
        assert any(isinstance(item, BeforeValidator) for item in amount_field.metadata)


def test_component_provenance_requires_sources_and_qualified_attestation():
    with pytest.raises(ValidationError):
        ComponentProvenance(
            rule_bundle_reference="rule-bundle",
            rule_reference="component-rule",
            source_references=(),
            qualified_review_attestation_reference="review-record",
            reviewer_qualification_reference="qualification-record",
        )
    with pytest.raises(ValidationError):
        ComponentProvenance(
            rule_bundle_reference="rule-bundle",
            rule_reference="component-rule",
            source_references=("source-record",),
        )

    assert ComponentProvenance.model_fields[
        "qualified_review_attestation_reference"
    ].is_required()
    assert ComponentProvenance.model_fields["reviewer_qualification_reference"].is_required()
    for model in (
        EarningBasisOutput,
        EarningOutput,
        EmployeeDeductionOutput,
        EmployerContributionOutput,
        ApprovedEmployerLevyOutput,
    ):
        assert model.model_fields["provenance"].is_required()


def test_result_variants_separate_calculated_totals_from_blocked_reasons():
    blocked = TypeAdapter(CanadianPayrollResult).validate_python(
        {"status": "blocked", "reason_codes": ["missing_reviewed_component"]}
    )
    invalid = TypeAdapter(CanadianPayrollResult).validate_python(
        {"status": "invalid_input", "reason_codes": ["invalid_pay_period"]}
    )

    assert isinstance(blocked, BlockedPayrollResult)
    assert isinstance(invalid, InvalidInputPayrollResult)
    assert not hasattr(blocked, "totals")
    assert not hasattr(invalid, "totals")
    assert "totals" in CalculatedPayrollResult.model_fields


def test_jurisdiction_and_rule_snapshots_are_immutable_contract_objects():
    jurisdiction = JurisdictionSnapshot(
        province="AB",
        effective_from=date(2026, 5, 1),
        effective_to=date(2026, 5, 7),
        snapshot_reference="jurisdiction-snapshot",
    )
    rule = RuleSnapshot(
        rule_bundle_reference="rule-bundle",
        version_reference="reviewed-rule-version",
        content_digest="digest-reference",
        effective_pay_date=date(2026, 5, 12),
    )

    with pytest.raises(ValidationError):
        jurisdiction.province = "ON"
    with pytest.raises(ValidationError):
        rule.version_reference = "changed"
