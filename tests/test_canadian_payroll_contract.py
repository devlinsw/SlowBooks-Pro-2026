from datetime import date
from decimal import Decimal
from typing import get_args, get_origin

import pytest
from pydantic import BeforeValidator, TypeAdapter, ValidationError

from app.schemas import canadian_payroll_contract as contract
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
    # Synthetic schema evidence only; these statuses do not assert liability.
    values = {
        "request_reference": "structural-request",
        "company_reference": "company-record",
        "company_payroll_country_assignments": (
            contract.CompanyPayrollCountryAssignment(
                country="CA",
                effective_from=date(2026, 5, 1),
                effective_to=date(2026, 5, 7),
            ),
        ),
        "currency": "CAD",
        "employee_reference": "employee-record",
        "worker_category": "part_time_hourly",
        "pay_frequency": "weekly",
        "employment_regulatory_scope": "provincial",
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
        "employer_configuration_references": EmployerConfigurationReferences(
            applicability_decisions=(
                contract.EmployerRequirementApplicability(
                    requirement="employer_levy",
                    decision="applicable",
                    review_attestation_reference="structural-levy-review",
                    reviewer_qualification_reference="structural-levy-qualification",
                    employer_configuration_reference="structural-levy-config",
                ),
                contract.EmployerRequirementApplicability(
                    requirement="workers_compensation",
                    decision="applicable",
                    review_attestation_reference="structural-wcb-review",
                    reviewer_qualification_reference="structural-wcb-qualification",
                    employer_configuration_reference="structural-wcb-config",
                ),
            )
        ),
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

    assert request.request_reference == "structural-request"
    assert tuple(
        assignment.country for assignment in request.company_payroll_country_assignments
    ) == ("CA",)
    assert request.currency == "CAD"
    assert request.employee_reference == "employee-record"
    assert request.employee_tax_election_reference.review_status == "reviewed"
    assert request.employee_eligibility_reference.review_status == "reviewed"
    assert len(request.employer_configuration_references.applicability_decisions) == 2
    assert request.pay_period.start_date == date(2026, 5, 1)
    assert request.pay_period.end_date == date(2026, 5, 7)
    assert request.pay_period.pay_date == date(2026, 5, 12)
    assert tuple(a.province for a in request.employee_province_assignments) == ("AB", "BC")

    blocked = TypeAdapter(CanadianPayrollResult).validate_python(
        {
            "status": "blocked",
            "request_reference": request.request_reference,
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


def test_request_rejects_unsupported_country_currency_and_unreviewed_data():
    with pytest.raises(ValidationError):
        make_request(currency="USD")
    with pytest.raises(ValidationError):
        make_request(
            company_payroll_country_assignments=(
                contract.CompanyPayrollCountryAssignment.model_validate(
                    {
                        "country": "MX",
                        "effective_from": date(2026, 5, 1),
                        "effective_to": date(2026, 5, 7),
                    }
                ),
            )
        )
    with pytest.raises(ValidationError):
        make_request(
            employee_tax_election_reference=ReviewedDataReference.model_validate(
                {
                    "reference_id": "tax-election",
                    "review_status": "unreviewed",
                    "review_attestation_reference": "review-record",
                    "reviewed_at": date(2026, 5, 1),
                }
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
    required = {
        "component_reference": "component-record",
        "rule_bundle_reference": "rule-bundle",
        "rule_snapshot_reference": "rule-snapshot",
        "rule_version_reference": "rule-version",
        "rule_content_digest": "rule-digest",
        "rule_reference": "component-rule",
        "source_snapshots": (
            contract.SourceSnapshot(
                source_reference="source-record",
                snapshot_reference="source-snapshot",
                version_reference="source-version",
                content_digest="source-digest",
            ),
        ),
        "qualified_review_attestation_reference": "review-record",
        "reviewer_qualification_reference": "qualification-record",
    }
    with pytest.raises(ValidationError):
        ComponentProvenance(**{**required, "source_snapshots": ()})
    with pytest.raises(ValidationError):
        ComponentProvenance.model_validate(
            {
                "component_reference": "component-record",
                "rule_bundle_reference": "rule-bundle",
                "rule_snapshot_reference": "rule-snapshot",
                "rule_version_reference": "rule-version",
                "rule_content_digest": "rule-digest",
                "rule_reference": "component-rule",
                "source_snapshots": required["source_snapshots"],
            }
        )

    assert ComponentProvenance.model_fields[
        "qualified_review_attestation_reference"
    ].is_required()
    assert ComponentProvenance.model_fields["rule_snapshot_reference"].is_required()
    assert ComponentProvenance.model_fields["rule_version_reference"].is_required()
    assert ComponentProvenance.model_fields["rule_content_digest"].is_required()
    assert ComponentProvenance.model_fields["source_snapshots"].is_required()
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
        {
            "status": "blocked",
            "request_reference": "structural-request",
            "reason_codes": ["missing_reviewed_component"],
        }
    )
    invalid = TypeAdapter(CanadianPayrollResult).validate_python(
        {
            "status": "invalid_input",
            "request_reference": "structural-request",
            "reason_codes": ["invalid_pay_period"],
        }
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
        snapshot_reference="rule-snapshot",
        version_reference="reviewed-rule-version",
        content_digest="digest-reference",
        effective_pay_date=date(2026, 5, 12),
        qualified_review_attestation_reference="review-attestation",
        reviewer_qualification_reference="reviewer-qualification",
    )

    with pytest.raises(ValidationError):
        jurisdiction.province = "ON"
    with pytest.raises(ValidationError):
        rule.version_reference = "changed"


def _new_contract_api(name):
    assert hasattr(contract, name), f"contract is missing {name}"
    return getattr(contract, name)


def _snapshot_test_provenance(**overrides):
    values = {
        "component_reference": "structural-component",
        "rule_bundle_reference": "structural-bundle",
        "rule_snapshot_reference": "structural-snapshot",
        "rule_version_reference": "structural-version",
        "rule_content_digest": "structural-rule-digest",
        "rule_reference": "structural-rule",
        "source_snapshots": (
            {
                "source_reference": "structural-source",
                "snapshot_reference": "structural-source-snapshot",
                "version_reference": "structural-source-version",
                "content_digest": "structural-source-digest",
            },
        ),
        "qualified_review_attestation_reference": "structural-review",
        "reviewer_qualification_reference": "structural-qualification",
    }
    values.update(overrides)
    return contract.ComponentProvenance(**values)


def _snapshot_test_rule(**overrides):
    values = {
        "rule_bundle_reference": "structural-bundle",
        "snapshot_reference": "structural-snapshot",
        "version_reference": "structural-version",
        "content_digest": "structural-rule-digest",
        "effective_pay_date": date(2026, 5, 12),
        "qualified_review_attestation_reference": "structural-review",
        "reviewer_qualification_reference": "structural-qualification",
    }
    values.update(overrides)
    return contract.RuleSnapshot(**values)


def _structural_calculated_result(**overrides):
    # Zero strings only satisfy required shape fields; no amount is an oracle.
    provenance = _snapshot_test_provenance()
    rule_snapshot = _snapshot_test_rule()
    values = {
        "status": "calculated",
        "request_reference": "structural-request",
        "result_reference": "structural-result",
        "employee_reference": "structural-employee",
        "currency": "CAD",
        "pay_period": PayPeriod(
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 7),
            pay_date=date(2026, 5, 12),
        ),
        "earnings": (
            {
                "earning_code": "structural-earning",
                "amount": "0",
                "provenance": provenance,
            },
        ),
        "totals": {
            "gross_earnings": "0",
            "employee_deductions": "0",
            "employer_contributions": "0",
            "approved_employer_levies": "0",
            "net_pay": "0",
            "total_employer_cost": "0",
        },
        "jurisdiction_snapshot": {
            "province": "AB",
            "effective_from": date(2026, 5, 1),
            "effective_to": date(2026, 5, 7),
            "snapshot_reference": "structural-jurisdiction",
        },
        "rule_snapshots": (rule_snapshot,),
    }
    values.update(overrides)
    return CalculatedPayrollResult(**values)


def test_calculated_result_does_not_expose_block_reasons():
    assert "block_reasons" not in CalculatedPayrollResult.model_fields


def test_employer_requirement_decisions_are_explicit_and_reviewed():
    applicability = _new_contract_api("EmployerRequirementApplicability")
    configuration = _new_contract_api("EmployerConfigurationReferences")

    levy_applicable = applicability(
        requirement="employer_levy",
        decision="applicable",
        review_attestation_reference="structural-levy-review",
        reviewer_qualification_reference="structural-levy-qualification",
        employer_configuration_reference="structural-employer-config",
    )
    wcb_reviewed_not_applicable = applicability(
        requirement="workers_compensation",
        decision="reviewed_not_applicable",
        review_attestation_reference="structural-wcb-review",
        reviewer_qualification_reference="structural-wcb-qualification",
    )
    assert configuration(
        applicability_decisions=(levy_applicable, wcb_reviewed_not_applicable)
    )

    with pytest.raises(ValidationError):
        applicability(
            requirement="employer_levy",
            decision="applicable",
            review_attestation_reference="structural-review",
            reviewer_qualification_reference="structural-qualification",
        )
    with pytest.raises(ValidationError):
        applicability(
            requirement="workers_compensation",
            decision="reviewed_not_applicable",
            reviewer_qualification_reference="structural-qualification",
        )
    with pytest.raises(ValidationError):
        configuration(applicability_decisions=())
    with pytest.raises(ValidationError):
        configuration()
    with pytest.raises(ValidationError):
        configuration(applicability_decisions=(levy_applicable, levy_applicable))


def test_effective_company_country_history_covers_period_and_is_single_country_at_a_time():
    country_assignment = _new_contract_api("CompanyPayrollCountryAssignment")
    assignments = (
        country_assignment(
            country="CA",
            effective_from=date(2026, 5, 1),
            effective_to=date(2026, 5, 7),
        ),
    )
    request = make_request(company_payroll_country_assignments=assignments)
    assert request.company_payroll_country_assignments == assignments

    crossing = (
        country_assignment(
            country="CA",
            effective_from=date(2026, 5, 1),
            effective_to=date(2026, 5, 3),
        ),
        country_assignment(
            country="US",
            effective_from=date(2026, 5, 4),
            effective_to=date(2026, 5, 7),
        ),
    )
    us_only = (
        country_assignment(
            country="US",
            effective_from=date(2026, 5, 1),
            effective_to=date(2026, 5, 7),
        ),
    )
    with pytest.raises(ValidationError, match="company country"):
        make_request(
            company_payroll_country_assignments=(
                country_assignment(
                    country="CA",
                    effective_from=date(2026, 5, 2),
                    effective_to=date(2026, 5, 7),
                ),
            )
        )
    with pytest.raises(ValidationError, match="company country assignments must not overlap"):
        make_request(
            company_payroll_country_assignments=(
                country_assignment(
                    country="CA",
                    effective_from=date(2026, 5, 1),
                    effective_to=date(2026, 5, 4),
                ),
                country_assignment(
                    country="US",
                    effective_from=date(2026, 5, 4),
                    effective_to=date(2026, 5, 7),
                ),
            )
        )

    evaluation = _new_contract_api("CanadianPayrollEvaluation")
    for history in (crossing, us_only):
        request = make_request(company_payroll_country_assignments=history)
        blocked = BlockedPayrollResult(
            status="blocked",
            request_reference=request.request_reference,
            reason_codes=(PayrollBlockReasonCode.UNSUPPORTED_JURISDICTION,),
        )
        paired = evaluation(request=request, result=blocked)
        assert paired.result is blocked
        assert not hasattr(paired.result, "totals")
        calculated = _structural_calculated_result(
            request_reference=request.request_reference,
            employee_reference=request.employee_reference,
            pay_period=request.pay_period,
        )
        with pytest.raises(ValidationError, match="company country"):
            evaluation(request=request, result=calculated)


def test_request_result_binding_blocks_cross_province_and_federal_calculations():
    evaluation = _new_contract_api("CanadianPayrollEvaluation")
    single_province_request = make_request(request_reference="structural-request")
    calculated = _structural_calculated_result(
        request_reference=single_province_request.request_reference,
        employee_reference=single_province_request.employee_reference,
        pay_period=single_province_request.pay_period,
    )
    assert evaluation(request=single_province_request, result=calculated)

    cross_province_request = make_request(
        request_reference="cross-province-request",
        assignments=(
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
        ),
    )
    cross_province_calculated = _structural_calculated_result(
        request_reference=cross_province_request.request_reference,
        employee_reference=cross_province_request.employee_reference,
        pay_period=cross_province_request.pay_period,
    )
    with pytest.raises(ValidationError, match="cross-province"):
        evaluation(request=cross_province_request, result=cross_province_calculated)
    cross_province_blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=cross_province_request.request_reference,
        reason_codes=(PayrollBlockReasonCode.CROSS_PROVINCE_PERIOD,),
    )
    paired_cross_province_block = evaluation(
        request=cross_province_request, result=cross_province_blocked
    )
    assert not hasattr(paired_cross_province_block.result, "totals")

    federal_request = make_request(
        request_reference="federal-request", employment_regulatory_scope="federal"
    )
    federal_calculated = _structural_calculated_result(
        request_reference=federal_request.request_reference,
        employee_reference=federal_request.employee_reference,
        pay_period=federal_request.pay_period,
    )
    with pytest.raises(ValidationError, match="federally regulated"):
        evaluation(request=federal_request, result=federal_calculated)
    federal_blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=federal_request.request_reference,
        reason_codes=(PayrollBlockReasonCode.FEDERALLY_REGULATED_EMPLOYMENT,),
    )
    paired_federal_block = evaluation(request=federal_request, result=federal_blocked)
    assert not hasattr(paired_federal_block.result, "totals")


def test_component_provenance_binds_exact_rule_and_source_snapshots():
    _new_contract_api("SourceSnapshot")
    provenance = _snapshot_test_provenance()
    rule_snapshot = _snapshot_test_rule()

    result = _structural_calculated_result(rule_snapshots=(rule_snapshot,))
    assert result.earnings[0].provenance.rule_snapshot_reference == rule_snapshot.snapshot_reference
    assert result.earnings[0].provenance.source_snapshots[0].version_reference
    assert result.earnings[0].provenance.source_snapshots[0].content_digest

    with pytest.raises(ValidationError, match="rule snapshot"):
        _structural_calculated_result(
            earnings=(
                {
                    "earning_code": "structural-earning",
                    "amount": "0",
                    "provenance": provenance.model_copy(
                        update={"rule_content_digest": "different-digest"}
                    ),
                },
            ),
            rule_snapshots=(rule_snapshot,),
        )

    another_snapshot = _snapshot_test_rule(
        snapshot_reference="conflicting-snapshot",
        version_reference="another-version",
        content_digest="another-digest",
    )
    with pytest.raises(ValidationError, match="one snapshot per rule bundle"):
        _structural_calculated_result(rule_snapshots=(rule_snapshot, another_snapshot))

    source_snapshot = _new_contract_api("SourceSnapshot")
    with pytest.raises(ValidationError):
        source_snapshot(source_reference="source-without-version")


def test_request_result_reference_must_match_exactly():
    evaluation = _new_contract_api("CanadianPayrollEvaluation")
    request = make_request(request_reference="request-A")
    result = BlockedPayrollResult(
        status="blocked",
        request_reference="request-B",
        reason_codes=(PayrollBlockReasonCode.MISSING_REVIEWED_COMPONENT,),
    )
    with pytest.raises(ValidationError, match="request reference"):
        evaluation(request=request, result=result)
