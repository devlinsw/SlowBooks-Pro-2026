from datetime import date
from decimal import Decimal
from typing import Literal, get_args, get_origin

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
    InvalidInputReasonCode,
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


def _employer_configuration_snapshot(
    requirement: Literal["employer_levy", "workers_compensation"],
):
    suffix = "levy" if requirement == "employer_levy" else "wcb"
    return contract.EmployerConfigurationSnapshot(
        employer_configuration_reference=f"structural-{suffix}-config",
        snapshot_reference=f"structural-{suffix}-config-snapshot",
        version_reference=f"structural-{suffix}-config-version",
        content_digest=f"structural-{suffix}-config-digest",
        review_attestation_reference=f"structural-{suffix}-config-review",
        reviewer_qualification_reference=f"structural-{suffix}-config-qualification",
        effective_from=date(2026, 5, 1),
        effective_to=date(2026, 5, 7),
        effective_date_basis="full_pay_period",
        applicability_review_attestation_reference=f"structural-{suffix}-date-review",
        applicability_reviewer_qualification_reference=f"structural-{suffix}-date-qualification",
    )


def make_employer_configuration(
    *,
    levy: Literal["applicable", "reviewed_not_applicable"] = "reviewed_not_applicable",
    wcb: Literal["applicable", "reviewed_not_applicable"] = "reviewed_not_applicable",
):
    return EmployerConfigurationReferences(
        applicability_decisions=(
            contract.EmployerRequirementApplicability(
                requirement="employer_levy",
                decision=levy,
                review_attestation_reference="structural-levy-review",
                reviewer_qualification_reference="structural-levy-qualification",
                effective_from=date(2026, 5, 1),
                effective_to=date(2026, 5, 7),
                effective_date_basis="full_pay_period",
                employer_configuration_snapshot=(
                    _employer_configuration_snapshot("employer_levy")
                    if levy == "applicable"
                    else None
                ),
            ),
            contract.EmployerRequirementApplicability(
                requirement="workers_compensation",
                decision=wcb,
                review_attestation_reference="structural-wcb-review",
                reviewer_qualification_reference="structural-wcb-qualification",
                effective_from=date(2026, 5, 1),
                effective_to=date(2026, 5, 7),
                effective_date_basis="full_pay_period",
                employer_configuration_snapshot=(
                    _employer_configuration_snapshot("workers_compensation")
                    if wcb == "applicable"
                    else None
                ),
            ),
        )
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
        "employer_configuration_references": make_employer_configuration(),
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
        contract.ApprovedWorkersCompensationOutput,
    ):
        amount_field = model.model_fields["amount"]
        assert amount_field.annotation is Decimal
        assert any(isinstance(item, BeforeValidator) for item in amount_field.metadata)
    for field_name in PayrollTotals.model_fields:
        amount_field = PayrollTotals.model_fields[field_name]
        assert amount_field.annotation is Decimal
        assert any(isinstance(item, BeforeValidator) for item in amount_field.metadata)


def test_generic_employer_contribution_is_closed_to_cpp_categories():
    category_field = EmployerContributionOutput.model_fields["contribution_category"]
    assert get_args(category_field.annotation) == ("CPP", "CPP2", "EI")
    assert EmployerContributionOutput(
        contribution_category="CPP",
        amount=Decimal("0"),
        provenance=_snapshot_test_provenance(),
    )
    with pytest.raises(ValidationError):
        EmployerContributionOutput(
            contribution_category="workers_compensation",
            amount=Decimal("0"),
            provenance=_snapshot_test_provenance(),
        )


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
                effective_from=date(2026, 5, 1),
                effective_to=date(2026, 5, 7),
                effective_date_basis="full_pay_period",
                applicability_review_attestation_reference="source-date-review",
                applicability_reviewer_qualification_reference="source-date-qualification",
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
        source_snapshots=(
            contract.SourceSnapshot(
                source_reference="source",
                snapshot_reference="source-snapshot",
                version_reference="source-version",
                content_digest="source-digest",
                effective_from=date(2026, 5, 1),
                effective_to=date(2026, 5, 7),
                effective_date_basis="full_pay_period",
                applicability_review_attestation_reference="source-date-review",
                applicability_reviewer_qualification_reference="source-date-qualification",
            ),
        ),
    )

    with pytest.raises(ValidationError):
        jurisdiction.province = "ON"
    with pytest.raises(ValidationError):
        rule.version_reference = "changed"


def _new_contract_api(name):
    assert hasattr(contract, name), f"contract is missing {name}"
    return getattr(contract, name)


def _snapshot_test_source(**overrides):
    values = {
        "source_reference": "structural-source",
        "snapshot_reference": "structural-source-snapshot",
        "version_reference": "structural-source-version",
        "content_digest": "structural-source-digest",
        "effective_from": date(2026, 5, 1),
        "effective_to": date(2026, 5, 7),
        "effective_date_basis": "full_pay_period",
        "applicability_review_attestation_reference": "structural-source-date-review",
        "applicability_reviewer_qualification_reference": "structural-source-date-qualification",
    }
    values.update(overrides)
    return contract.SourceSnapshot(**values)


def _snapshot_test_provenance(**overrides):
    values = {
        "component_reference": "structural-component",
        "rule_bundle_reference": "structural-bundle",
        "rule_snapshot_reference": "structural-snapshot",
        "rule_version_reference": "structural-version",
        "rule_content_digest": "structural-rule-digest",
        "rule_reference": "structural-rule",
        "source_snapshots": (_snapshot_test_source(),),
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
        "source_snapshots": (_snapshot_test_source(),),
    }
    values.update(overrides)
    return contract.RuleSnapshot(**values)


def _snapshot_test_orphan_rule(*, effective_pay_date):
    return _snapshot_test_rule(
        rule_bundle_reference="orphan-rule-bundle",
        snapshot_reference="orphan-rule-snapshot",
        version_reference="orphan-rule-version",
        content_digest="orphan-rule-digest",
        effective_pay_date=effective_pay_date,
        qualified_review_attestation_reference="orphan-rule-review",
        reviewer_qualification_reference="orphan-rule-qualification",
        source_snapshots=(
            _snapshot_test_source(
                source_reference="orphan-source",
                snapshot_reference="orphan-source-snapshot",
                version_reference="orphan-source-version",
                content_digest="orphan-source-digest",
            ),
        ),
    )


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


def test_employer_requirement_decisions_require_configuration_for_applicable_status():
    applicability = _new_contract_api("EmployerRequirementApplicability")
    configuration = _new_contract_api("EmployerConfigurationReferences")

    levy_applicable = applicability(
        requirement="employer_levy",
        decision="applicable",
        review_attestation_reference="structural-levy-review",
        reviewer_qualification_reference="structural-levy-qualification",
        effective_from=date(2026, 5, 1),
        effective_to=date(2026, 5, 7),
        effective_date_basis="full_pay_period",
        employer_configuration_snapshot=contract.EmployerConfigurationSnapshot(
            employer_configuration_reference="structural-employer-config",
            snapshot_reference="structural-employer-config-snapshot",
            version_reference="structural-employer-config-version",
            content_digest="structural-employer-config-digest",
            review_attestation_reference="structural-employer-config-review",
            reviewer_qualification_reference="structural-employer-config-qualification",
            effective_from=date(2026, 5, 1),
            effective_to=date(2026, 5, 7),
            effective_date_basis="full_pay_period",
            applicability_review_attestation_reference="structural-employer-config-date-review",
            applicability_reviewer_qualification_reference="structural-employer-config-date-qualification",
        ),
    )
    wcb_reviewed_not_applicable = applicability(
        requirement="workers_compensation",
        decision="reviewed_not_applicable",
        review_attestation_reference="structural-wcb-review",
        reviewer_qualification_reference="structural-wcb-qualification",
        effective_from=date(2026, 5, 1),
        effective_to=date(2026, 5, 7),
        effective_date_basis="full_pay_period",
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
    with pytest.raises(ValidationError, match="reviewed employer applicability decision requires"):
        applicability(
            requirement="workers_compensation",
            decision="reviewed_not_applicable",
        )
    unreviewed_decision = applicability(
        requirement="workers_compensation",
        decision="unreviewed",
    )
    assert unreviewed_decision.review_attestation_reference is None
    assert unreviewed_decision.reviewer_qualification_reference is None
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


def test_calculated_result_rejects_unreferenced_rule_snapshot_with_stale_pay_date():
    request = make_request()
    base_result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
    )
    result_payload = base_result.model_dump()
    result_payload["rule_snapshots"] = (
        *base_result.rule_snapshots,
        _snapshot_test_orphan_rule(effective_pay_date=date(1900, 1, 1)),
    )

    with pytest.raises(ValidationError, match="rule snapshot pay date"):
        contract.CanadianPayrollEvaluation.model_validate(
            {"request": request, "result": result_payload}
        )


def test_calculated_result_rejects_unreferenced_rule_snapshot_with_valid_pay_date():
    request = make_request()
    base_result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
    )
    result_payload = base_result.model_dump()
    result_payload["rule_snapshots"] = (
        *base_result.rule_snapshots,
        _snapshot_test_orphan_rule(effective_pay_date=date(2026, 5, 12)),
    )

    with pytest.raises(ValidationError, match="must be referenced by component provenance"):
        contract.CanadianPayrollEvaluation.model_validate(
            {"request": request, "result": result_payload}
        )


def test_calculated_result_accepts_rule_snapshot_referenced_only_by_basis_provenance():
    request = make_request()
    primary_rule_snapshot = _snapshot_test_rule()
    basis_source_snapshot = _snapshot_test_source(
        source_reference="basis-only-source",
        snapshot_reference="basis-only-source-snapshot",
        version_reference="basis-only-source-version",
        content_digest="basis-only-source-digest",
        applicability_review_attestation_reference="basis-only-source-date-review",
        applicability_reviewer_qualification_reference="basis-only-source-date-qualification",
    )
    basis_rule_snapshot = _snapshot_test_rule(
        rule_bundle_reference="basis-only-rule-bundle",
        snapshot_reference="basis-only-rule-snapshot",
        version_reference="basis-only-rule-version",
        content_digest="basis-only-rule-digest",
        effective_pay_date=request.pay_period.pay_date,
        qualified_review_attestation_reference="basis-only-rule-review",
        reviewer_qualification_reference="basis-only-rule-qualification",
        source_snapshots=(basis_source_snapshot,),
    )
    basis_provenance = _snapshot_test_provenance(
        component_reference="basis-only-component",
        rule_bundle_reference=basis_rule_snapshot.rule_bundle_reference,
        rule_snapshot_reference=basis_rule_snapshot.snapshot_reference,
        rule_version_reference=basis_rule_snapshot.version_reference,
        rule_content_digest=basis_rule_snapshot.content_digest,
        rule_reference="basis-only-rule",
        source_snapshots=(basis_source_snapshot,),
        qualified_review_attestation_reference=(
            basis_rule_snapshot.qualified_review_attestation_reference
        ),
        reviewer_qualification_reference=(
            basis_rule_snapshot.reviewer_qualification_reference
        ),
    )
    basis_earning = EarningOutput.model_validate(
        {
            "earning_code": "structural-earning",
            "amount": "0",
            "bases": (
                {
                    "basis_code": "structural-basis",
                    "amount": "0",
                    "provenance": basis_provenance,
                },
            ),
            "provenance": _snapshot_test_provenance(),
        }
    )
    result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
        earnings=(basis_earning,),
        rule_snapshots=(primary_rule_snapshot, basis_rule_snapshot),
    )

    assert result.earnings[0].provenance.rule_snapshot_reference == (
        primary_rule_snapshot.snapshot_reference
    )
    assert result.earnings[0].bases[0].provenance.rule_snapshot_reference == (
        basis_rule_snapshot.snapshot_reference
    )
    assert contract.CanadianPayrollEvaluation(request=request, result=result)


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


def test_source_provenance_must_match_source_snapshot_on_exact_rule_snapshot():
    source = contract.SourceSnapshot(
        source_reference="cra-source",
        snapshot_reference="cra-source-snapshot",
        version_reference="cra-version-1",
        content_digest="cra-digest-1",
        effective_from=date(2026, 5, 1),
        effective_to=date(2026, 5, 7),
        effective_date_basis="full_pay_period",
        applicability_review_attestation_reference="source-date-review",
        applicability_reviewer_qualification_reference="source-date-qualification",
    )
    selected_source = contract.SourceSnapshot(
        source_reference="cra-source",
        snapshot_reference="cra-source-snapshot",
        version_reference="cra-version-2",
        content_digest="cra-digest-2",
        effective_from=date(2026, 5, 1),
        effective_to=date(2026, 5, 7),
        effective_date_basis="full_pay_period",
        applicability_review_attestation_reference="source-date-review",
        applicability_reviewer_qualification_reference="source-date-qualification",
    )
    provenance = _snapshot_test_provenance(source_snapshots=(selected_source,))

    with pytest.raises(ValidationError, match="source snapshot"):
        rule_snapshot = _snapshot_test_rule(source_snapshots=(source,))
        _structural_calculated_result(
            earnings=(
                {
                    "earning_code": "structural-earning",
                    "amount": "0",
                    "provenance": provenance,
                },
            ),
            rule_snapshots=(rule_snapshot,),
        )


def test_component_provenance_rejects_unrelated_source_snapshot():
    rule_source = _snapshot_test_source()
    unrelated_source = _snapshot_test_source(
        source_reference="unrelated-source",
        snapshot_reference="unrelated-source-snapshot",
        version_reference="unrelated-version",
        content_digest="unrelated-digest",
    )
    provenance = _snapshot_test_provenance(source_snapshots=(unrelated_source,))
    rule_snapshot = _snapshot_test_rule(source_snapshots=(rule_source,))

    with pytest.raises(ValidationError, match="source snapshots must match"):
        _structural_calculated_result(
            earnings=(
                {
                    "earning_code": "structural-earning",
                    "amount": "0",
                    "provenance": provenance,
                },
            ),
            rule_snapshots=(rule_snapshot,),
        )


# Decimal zeroes in employer-output records below are shape placeholders only.
def test_calculated_result_requires_applicable_levy_and_wcb_outputs():
    evaluation = _new_contract_api("CanadianPayrollEvaluation")
    request = make_request(
        employer_configuration_references=make_employer_configuration(
            levy="applicable", wcb="applicable"
        )
    )
    result_without_either = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
    )
    with pytest.raises(ValidationError, match="employer levy"):
        evaluation(request=request, result=result_without_either)

    levy_only = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
        approved_employer_levies=(
            ApprovedEmployerLevyOutput(
                levy_code="structural-levy",
                amount=Decimal("0"),
                employer_configuration_reference="structural-levy-config",
                employer_configuration_snapshot_reference="structural-levy-config-snapshot",
                approval_reference="structural-levy-approval",
                provenance=_snapshot_test_provenance(),
            ),
        ),
    )
    with pytest.raises(ValidationError, match="workers compensation"):
        evaluation(request=request, result=levy_only)


def test_calculated_employer_output_must_reference_exact_request_configuration():
    evaluation = _new_contract_api("CanadianPayrollEvaluation")
    request = make_request(
        employer_configuration_references=make_employer_configuration(
            levy="applicable", wcb="applicable"
        )
    )
    result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
        approved_employer_levies=(
            ApprovedEmployerLevyOutput(
                levy_code="structural-levy",
                amount=Decimal("0"),
                employer_configuration_reference="unrelated-config",
                employer_configuration_snapshot_reference="unrelated-snapshot",
                approval_reference="structural-levy-approval",
                provenance=_snapshot_test_provenance(),
            ),
        ),
        approved_workers_compensation=(
            contract.ApprovedWorkersCompensationOutput(
                workers_compensation_code="structural-wcb",
                amount=Decimal("0"),
                employer_configuration_reference="structural-wcb-config",
                employer_configuration_snapshot_reference="structural-wcb-config-snapshot",
                approval_reference="structural-wcb-approval",
                provenance=_snapshot_test_provenance(),
            ),
        ),
    )
    with pytest.raises(ValidationError, match="configuration"):
        evaluation(request=request, result=result)


def test_matching_employer_outputs_bind_to_both_reviewed_configurations():
    request = make_request(
        employer_configuration_references=make_employer_configuration(
            levy="applicable", wcb="applicable"
        )
    )
    result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
        approved_employer_levies=(
            ApprovedEmployerLevyOutput(
                levy_code="structural-levy",
                amount=Decimal("0"),
                employer_configuration_reference="structural-levy-config",
                employer_configuration_snapshot_reference="structural-levy-config-snapshot",
                approval_reference="structural-levy-approval",
                provenance=_snapshot_test_provenance(),
            ),
        ),
        approved_workers_compensation=(
            contract.ApprovedWorkersCompensationOutput(
                workers_compensation_code="structural-wcb",
                amount=Decimal("0"),
                employer_configuration_reference="structural-wcb-config",
                employer_configuration_snapshot_reference="structural-wcb-config-snapshot",
                approval_reference="structural-wcb-approval",
                provenance=_snapshot_test_provenance(),
            ),
        ),
    )

    paired = contract.CanadianPayrollEvaluation(request=request, result=result)
    assert paired.result is result


def test_reviewed_not_applicable_workers_compensation_forbids_wcb_output():
    request = make_request(
        employer_configuration_references=make_employer_configuration(
            levy="applicable", wcb="reviewed_not_applicable"
        )
    )
    levy = ApprovedEmployerLevyOutput(
        levy_code="structural-levy",
        amount=Decimal("0"),
        employer_configuration_reference="structural-levy-config",
        employer_configuration_snapshot_reference="structural-levy-config-snapshot",
        approval_reference="structural-levy-approval",
        provenance=_snapshot_test_provenance(),
    )
    wcb = contract.ApprovedWorkersCompensationOutput(
        workers_compensation_code="structural-wcb",
        amount=Decimal("0"),
        employer_configuration_reference="structural-wcb-config",
        employer_configuration_snapshot_reference="structural-wcb-config-snapshot",
        approval_reference="structural-wcb-approval",
        provenance=_snapshot_test_provenance(),
    )
    result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
        approved_employer_levies=(levy,),
        approved_workers_compensation=(wcb,),
    )
    with pytest.raises(ValidationError, match="not-applicable"):
        contract.CanadianPayrollEvaluation(request=request, result=result)


def test_reviewed_not_applicable_levy_forbids_levy_output():
    request = make_request()
    levy = ApprovedEmployerLevyOutput(
        levy_code="structural-levy",
        amount=Decimal("0"),
        employer_configuration_reference="unlisted-config",
        employer_configuration_snapshot_reference="unlisted-snapshot",
        approval_reference="structural-levy-approval",
        provenance=_snapshot_test_provenance(),
    )
    result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
        approved_employer_levies=(levy,),
    )

    with pytest.raises(ValidationError, match="not-applicable"):
        contract.CanadianPayrollEvaluation(request=request, result=result)


def test_employer_configuration_snapshot_is_reviewed_and_immutable():
    configuration_snapshot = _new_contract_api("EmployerConfigurationSnapshot")
    snapshot = configuration_snapshot(
        employer_configuration_reference="structural-config",
        snapshot_reference="structural-config-snapshot",
        version_reference="structural-config-version",
        content_digest="structural-config-digest",
        review_attestation_reference="structural-config-review",
        reviewer_qualification_reference="structural-config-qualification",
        effective_from=date(2026, 5, 1),
        effective_to=date(2026, 5, 7),
        effective_date_basis="full_pay_period",
        applicability_review_attestation_reference="structural-config-date-review",
        applicability_reviewer_qualification_reference="structural-config-date-qualification",
    )
    with pytest.raises(ValidationError):
        snapshot.version_reference = "changed"


def test_invalid_input_can_be_bound_without_a_valid_typed_request():
    evaluation = _new_contract_api("CanadianPayrollEvaluation")
    malformed = InvalidInputPayrollResult(
        status="invalid_input",
        request_reference="malformed-payload-correlation",
        reason_codes=(InvalidInputReasonCode.INVALID_PAY_PERIOD,),
    )
    paired = evaluation(request=None, result=malformed)
    assert paired.request is None
    assert paired.result.request_reference == "malformed-payload-correlation"


def test_valid_typed_request_cannot_be_paired_with_invalid_input_result():
    request = make_request()
    invalid = InvalidInputPayrollResult(
        status="invalid_input",
        request_reference=request.request_reference,
        reason_codes=(InvalidInputReasonCode.INVALID_PAY_PERIOD,),
    )
    with pytest.raises(ValidationError, match="valid typed request"):
        contract.CanadianPayrollEvaluation(request=request, result=invalid)


def test_unsupported_jurisdiction_can_be_blocked_without_typed_request():
    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference="unsupported-province-correlation",
        reason_codes=(PayrollBlockReasonCode.UNSUPPORTED_JURISDICTION,),
    )
    paired = contract.CanadianPayrollEvaluation(request=None, result=blocked)
    assert paired.request is None
    assert paired.result.reason_codes == (PayrollBlockReasonCode.UNSUPPORTED_JURISDICTION,)


def test_requestless_block_is_reserved_for_unsupported_jurisdiction():
    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference="unreviewed-correlation",
        reason_codes=(PayrollBlockReasonCode.MISSING_REVIEWED_COMPONENT,),
    )
    with pytest.raises(ValidationError, match="unsupported jurisdiction"):
        contract.CanadianPayrollEvaluation(request=None, result=blocked)


def test_uncovered_jurisdiction_history_has_specific_invalid_input_reason():
    reason = InvalidInputReasonCode.UNCOVERED_JURISDICTION_HISTORY
    invalid = InvalidInputPayrollResult(
        status="invalid_input",
        request_reference="uncovered-history-correlation",
        reason_codes=(reason,),
    )
    paired = contract.CanadianPayrollEvaluation(request=None, result=invalid)
    assert paired.result.reason_codes == (reason,)


@pytest.mark.parametrize(
    "reason",
    [
        PayrollBlockReasonCode.UNSUPPORTED_JURISDICTION,
        PayrollBlockReasonCode.FEDERALLY_REGULATED_EMPLOYMENT,
    ],
)
def test_invalid_input_rejects_block_reason_codes(reason):
    with pytest.raises(ValidationError):
        InvalidInputPayrollResult(
            status="invalid_input",
            request_reference="unsupported-correlation",
            reason_codes=(reason,),
        )


def test_invalid_input_reason_codes_are_separate_from_block_reasons():
    assert not hasattr(PayrollBlockReasonCode, "INVALID_PAY_PERIOD")
    assert not hasattr(PayrollBlockReasonCode, "UNCOVERED_JURISDICTION_HISTORY")
    assert InvalidInputReasonCode.INVALID_PAY_PERIOD.value == "invalid_pay_period"
    assert (
        InvalidInputReasonCode.UNCOVERED_JURISDICTION_HISTORY.value
        == "uncovered_jurisdiction_history"
    )


def test_generic_employer_contribution_has_only_closed_cpp_categories():
    category_field = EmployerContributionOutput.model_fields["contribution_category"]
    assert get_args(category_field.annotation) == ("CPP", "CPP2", "EI")
    assert "contribution_code" not in EmployerContributionOutput.model_fields
    assert "contribution_scope" not in EmployerContributionOutput.model_fields

    for category in ("CPP", "CPP2", "EI"):
        assert EmployerContributionOutput(
            contribution_category=category,
            amount=Decimal("0"),
            provenance=_snapshot_test_provenance(),
        )

    for forbidden in ("employer_levy", "workers_compensation"):
        with pytest.raises(ValidationError):
            EmployerContributionOutput(
                contribution_category=forbidden,
                amount=Decimal("0"),
                provenance=_snapshot_test_provenance(),
            )


def test_source_snapshot_effective_date_basis_controls_source_coverage():
    source = _snapshot_test_source(
        effective_from=date(2026, 5, 1),
        effective_to=date(2026, 5, 7),
        effective_date_basis="full_pay_period",
        applicability_review_attestation_reference="structural-source-date-review",
        applicability_reviewer_qualification_reference="structural-source-date-qualification",
    )
    provenance = _snapshot_test_provenance(source_snapshots=(source,))
    rule = _snapshot_test_rule(source_snapshots=(source,))
    earning = {
        "earning_code": "structural-earning",
        "amount": "0",
        "provenance": provenance,
    }
    assert _structural_calculated_result(earnings=(earning,), rule_snapshots=(rule,))

    pay_date_only = _snapshot_test_source(
        snapshot_reference="pay-date-only-source",
        effective_from=date(2026, 5, 12),
        effective_to=date(2026, 5, 12),
        effective_date_basis="pay_date",
        applicability_review_attestation_reference="structural-source-date-review",
        applicability_reviewer_qualification_reference="structural-source-date-qualification",
    )
    pay_date_provenance = _snapshot_test_provenance(
        rule_snapshot_reference="pay-date-source-rule-snapshot",
        source_snapshots=(pay_date_only,),
    )
    pay_date_rule = _snapshot_test_rule(
        snapshot_reference="pay-date-source-rule-snapshot",
        source_snapshots=(pay_date_only,),
    )
    assert _structural_calculated_result(
        earnings=(
            {
                "earning_code": "structural-earning",
                "amount": "0",
                "provenance": pay_date_provenance,
            },
        ),
        rule_snapshots=(pay_date_rule,),
    )

    uncovered = _snapshot_test_source(
        snapshot_reference="uncovered-source",
        effective_from=date(2026, 5, 2),
        effective_to=date(2026, 5, 7),
        effective_date_basis="full_pay_period",
        applicability_review_attestation_reference="structural-source-date-review",
        applicability_reviewer_qualification_reference="structural-source-date-qualification",
    )
    uncovered_provenance = _snapshot_test_provenance(
        rule_snapshot_reference="uncovered-source-rule-snapshot",
        source_snapshots=(uncovered,),
    )
    uncovered_rule = _snapshot_test_rule(
        snapshot_reference="uncovered-source-rule-snapshot",
        source_snapshots=(uncovered,),
    )
    with pytest.raises(ValidationError, match="source snapshot.*cover"):
        _structural_calculated_result(
            earnings=(
                {
                    "earning_code": "structural-earning",
                    "amount": "0",
                    "provenance": uncovered_provenance,
                },
            ),
            rule_snapshots=(uncovered_rule,),
        )


def test_employer_configuration_snapshot_covers_its_declared_date_basis():
    evaluation = _new_contract_api("CanadianPayrollEvaluation")

    def evaluated_snapshot(*, effective_from, effective_to, effective_date_basis):
        snapshot = contract.EmployerConfigurationSnapshot(
            employer_configuration_reference="structural-date-config",
            snapshot_reference="structural-date-config-snapshot",
            version_reference="structural-date-config-version",
            content_digest="structural-date-config-digest",
            review_attestation_reference="structural-date-config-review",
            reviewer_qualification_reference="structural-date-config-qualification",
            effective_from=effective_from,
            effective_to=effective_to,
            effective_date_basis=effective_date_basis,
            applicability_review_attestation_reference="structural-date-config-applicability-review",
            applicability_reviewer_qualification_reference="structural-date-config-applicability-qualification",
        )
        configuration = EmployerConfigurationReferences(
            applicability_decisions=(
                contract.EmployerRequirementApplicability(
                    requirement="employer_levy",
                    decision="applicable",
                    review_attestation_reference="structural-levy-review",
                    reviewer_qualification_reference="structural-levy-qualification",
                    effective_from=date(2026, 5, 12),
                    effective_to=date(2026, 5, 12),
                    effective_date_basis="pay_date",
                    employer_configuration_snapshot=snapshot,
                ),
                contract.EmployerRequirementApplicability(
                    requirement="workers_compensation",
                    decision="reviewed_not_applicable",
                    review_attestation_reference="structural-wcb-review",
                    reviewer_qualification_reference="structural-wcb-qualification",
                    effective_from=date(2026, 5, 1),
                    effective_to=date(2026, 5, 7),
                    effective_date_basis="full_pay_period",
                ),
            )
        )
        request = make_request(employer_configuration_references=configuration)
        result = _structural_calculated_result(
            request_reference=request.request_reference,
            employee_reference=request.employee_reference,
            pay_period=request.pay_period,
            approved_employer_levies=(
                ApprovedEmployerLevyOutput(
                    levy_code="structural-levy",
                    amount=Decimal("0"),
                    employer_configuration_reference=snapshot.employer_configuration_reference,
                    employer_configuration_snapshot_reference=snapshot.snapshot_reference,
                    approval_reference="structural-levy-approval",
                    provenance=_snapshot_test_provenance(),
                ),
            ),
        )
        return evaluation(request=request, result=result)

    assert evaluated_snapshot(
        effective_from=date(2026, 5, 12),
        effective_to=date(2026, 5, 12),
        effective_date_basis="pay_date",
    )
    with pytest.raises(ValidationError, match="employer configuration snapshot.*cover"):
        evaluated_snapshot(
            effective_from=date(2026, 5, 2),
            effective_to=date(2026, 5, 12),
            effective_date_basis="full_pay_period",
        )


@pytest.mark.parametrize(
    "snapshot_factory,values",
    [
        (
            lambda **values: contract.SourceSnapshot(
                source_reference="structural-source",
                snapshot_reference="ordered-source",
                version_reference="structural-source-version",
                content_digest="structural-source-digest",
                effective_date_basis="pay_date",
                applicability_review_attestation_reference="structural-review",
                applicability_reviewer_qualification_reference="structural-qualification",
                **values,
            ),
            {"effective_from": date(2026, 5, 13), "effective_to": date(2026, 5, 12)},
        ),
        (
            lambda **values: contract.EmployerConfigurationSnapshot(
                employer_configuration_reference="structural-config",
                snapshot_reference="ordered-config",
                version_reference="structural-config-version",
                content_digest="structural-config-digest",
                review_attestation_reference="structural-review",
                reviewer_qualification_reference="structural-qualification",
                effective_date_basis="pay_date",
                applicability_review_attestation_reference="structural-date-review",
                applicability_reviewer_qualification_reference="structural-date-qualification",
                **values,
            ),
            {"effective_from": date(2026, 5, 13), "effective_to": date(2026, 5, 12)},
        ),
    ],
)
def test_effective_snapshot_date_ranges_must_be_ordered(snapshot_factory, values):
    with pytest.raises(ValidationError, match="end must not precede its start"):
        snapshot_factory(**values)


def test_unspecified_source_date_basis_allows_blocking_but_not_calculated_output():
    source = contract.SourceSnapshot(
        source_reference="structural-unreviewed-source",
        snapshot_reference="structural-unreviewed-source-snapshot",
        version_reference="structural-unreviewed-source-version",
        content_digest="structural-unreviewed-source-digest",
    )
    rule = _snapshot_test_rule(source_snapshots=(source,))
    provenance = _snapshot_test_provenance(source_snapshots=(source,))

    with pytest.raises(ValidationError, match="no reviewed effective-date basis"):
        _structural_calculated_result(
            earnings=(
                {
                    "earning_code": "structural-earning",
                    "amount": "0",
                    "provenance": provenance,
                },
            ),
            rule_snapshots=(rule,),
        )

    request = make_request()
    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=request.request_reference,
        reason_codes=(PayrollBlockReasonCode.MISSING_REVIEWED_COMPONENT,),
        rule_snapshots=(rule,),
    )
    assert contract.CanadianPayrollEvaluation(request=request, result=blocked)


def test_unspecified_employer_configuration_date_basis_stays_blocked():
    snapshot = contract.EmployerConfigurationSnapshot(
        employer_configuration_reference="structural-unreviewed-config",
        snapshot_reference="structural-unreviewed-config-snapshot",
        version_reference="structural-unreviewed-config-version",
        content_digest="structural-unreviewed-config-digest",
        review_attestation_reference="structural-config-review",
        reviewer_qualification_reference="structural-config-qualification",
    )
    configuration = EmployerConfigurationReferences(
        applicability_decisions=(
            contract.EmployerRequirementApplicability(
                requirement="employer_levy",
                decision="applicable",
                review_attestation_reference="structural-levy-review",
                reviewer_qualification_reference="structural-levy-qualification",
                effective_from=date(2026, 5, 1),
                effective_to=date(2026, 5, 7),
                effective_date_basis="full_pay_period",
                employer_configuration_snapshot=snapshot,
            ),
            contract.EmployerRequirementApplicability(
                requirement="workers_compensation",
                decision="reviewed_not_applicable",
                review_attestation_reference="structural-wcb-review",
                reviewer_qualification_reference="structural-wcb-qualification",
                effective_from=date(2026, 5, 1),
                effective_to=date(2026, 5, 7),
                effective_date_basis="full_pay_period",
            ),
        )
    )
    request = make_request(employer_configuration_references=configuration)
    result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
        approved_employer_levies=(
            ApprovedEmployerLevyOutput(
                levy_code="structural-levy",
                amount=Decimal("0"),
                employer_configuration_reference=snapshot.employer_configuration_reference,
                employer_configuration_snapshot_reference=snapshot.snapshot_reference,
                approval_reference="structural-levy-approval",
                provenance=_snapshot_test_provenance(),
            ),
        ),
    )

    with pytest.raises(ValidationError, match="no reviewed effective-date basis"):
        contract.CanadianPayrollEvaluation(request=request, result=result)

    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=request.request_reference,
        reason_codes=(PayrollBlockReasonCode.MISSING_REVIEWED_COMPONENT,),
    )
    assert contract.CanadianPayrollEvaluation(request=request, result=blocked)


@pytest.mark.parametrize(
    "snapshot_factory",
    [
        lambda: contract.SourceSnapshot(
            source_reference="structural-source",
            snapshot_reference="partial-source",
            version_reference="structural-source-version",
            content_digest="structural-source-digest",
            effective_from=date(2026, 5, 1),
        ),
        lambda: contract.EmployerConfigurationSnapshot(
            employer_configuration_reference="structural-config",
            snapshot_reference="partial-config",
            version_reference="structural-config-version",
            content_digest="structural-config-digest",
            review_attestation_reference="structural-review",
            reviewer_qualification_reference="structural-qualification",
            effective_from=date(2026, 5, 1),
        ),
    ],
)
def test_effective_date_metadata_cannot_be_partially_specified(snapshot_factory):
    with pytest.raises(ValidationError, match="must be supplied together"):
        snapshot_factory()


def _applicability_test_request(
    *,
    effective_from=None,
    effective_to=None,
    effective_date_basis=None,
    reviewed=True,
):
    decisions = []
    for requirement in ("employer_levy", "workers_compensation"):
        values = {
            "requirement": requirement,
            "decision": "reviewed_not_applicable" if reviewed else "unreviewed",
        }
        if reviewed:
            values.update(
                review_attestation_reference=f"structural-{requirement}-review",
                reviewer_qualification_reference=f"structural-{requirement}-qualification",
            )
        if any(
            value is not None
            for value in (effective_from, effective_to, effective_date_basis)
        ):
            values.update(
                effective_from=effective_from,
                effective_to=effective_to,
                effective_date_basis=effective_date_basis,
            )
        decisions.append(contract.EmployerRequirementApplicability(**values))
    references = EmployerConfigurationReferences(applicability_decisions=tuple(decisions))
    return make_request(employer_configuration_references=references)


def _unreviewed_applicability_test_request():
    decisions = tuple(
        contract.EmployerRequirementApplicability(
            requirement=requirement,
            decision="unreviewed",
            review_attestation_reference=f"pending-{requirement}-review",
        )
        for requirement in ("employer_levy", "workers_compensation")
    )
    return make_request(
        employer_configuration_references=EmployerConfigurationReferences(
            applicability_decisions=decisions
        )
    )


def _raw_request_with_decisions(decisions):
    request = make_request().model_dump(mode="python")
    request["employer_configuration_references"] = {
        "applicability_decisions": decisions,
    }
    return request


def test_incomplete_reviewed_not_applicable_is_rejected_at_public_envelope():
    request = _raw_request_with_decisions(
        (
            {"requirement": "employer_levy", "decision": "reviewed_not_applicable"},
            {
                "requirement": "workers_compensation",
                "decision": "reviewed_not_applicable",
            },
        )
    )
    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=request["request_reference"],
        reason_codes=(PayrollBlockReasonCode.OTHER,),
    )

    with pytest.raises(
        ValidationError,
        match="reviewed employer applicability decision requires qualified review and effective-date evidence",
    ):
        contract.CanadianPayrollEvaluation(request=request, result=blocked)


def test_unreviewed_applicability_accepts_explicit_missing_review_block():
    request = _unreviewed_applicability_test_request()
    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=request.request_reference,
        reason_codes=(PayrollBlockReasonCode.MISSING_REVIEWED_COMPONENT,),
    )

    assert contract.CanadianPayrollEvaluation(request=request, result=blocked)


def test_unreviewed_applicability_rejects_blocked_result_without_missing_review_reason():
    request = _unreviewed_applicability_test_request()
    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=request.request_reference,
        reason_codes=(PayrollBlockReasonCode.OTHER,),
    )

    with pytest.raises(
        ValidationError,
        match="unreviewed employer applicability decision requires missing_reviewed_component block",
    ):
        contract.CanadianPayrollEvaluation(request=request, result=blocked)


def test_unreviewed_applicability_and_federal_scope_require_both_block_reasons():
    request_payload = _unreviewed_applicability_test_request().model_dump(mode="python")
    request_payload["employment_regulatory_scope"] = "federal"
    request = CanadianPayrollRequest.model_validate(request_payload)
    evaluation = contract.CanadianPayrollEvaluation
    required_reasons = (
        PayrollBlockReasonCode.MISSING_REVIEWED_COMPONENT,
        PayrollBlockReasonCode.FEDERALLY_REGULATED_EMPLOYMENT,
    )
    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=request.request_reference,
        reason_codes=required_reasons,
    )

    paired = evaluation(request=request, result=blocked)
    assert isinstance(paired.result, BlockedPayrollResult)
    assert paired.result.reason_codes == required_reasons

    for reason in required_reasons:
        blocked_with_one_reason = BlockedPayrollResult(
            status="blocked",
            request_reference=request.request_reference,
            reason_codes=(reason,),
        )
        with pytest.raises(ValidationError):
            evaluation(request=request, result=blocked_with_one_reason)


def test_unreviewed_applicability_rejects_calculated_result():
    request = _unreviewed_applicability_test_request()
    calculated = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
    )

    with pytest.raises(
        ValidationError,
        match="unreviewed employer applicability decision must be blocked",
    ):
        contract.CanadianPayrollEvaluation(request=request, result=calculated)


def test_incomplete_applicable_decision_is_rejected_at_public_envelope():
    reviewed_wcb = contract.EmployerRequirementApplicability(
        requirement="workers_compensation",
        decision="reviewed_not_applicable",
        review_attestation_reference="structural-wcb-review",
        reviewer_qualification_reference="structural-wcb-qualification",
        effective_from=date(2026, 5, 1),
        effective_to=date(2026, 5, 7),
        effective_date_basis="full_pay_period",
    ).model_dump(mode="python")
    incomplete_levy = {
        "requirement": "employer_levy",
        "decision": "applicable",
        "employer_configuration_snapshot": _employer_configuration_snapshot(
            "employer_levy"
        ).model_dump(mode="python"),
    }
    request = _raw_request_with_decisions((incomplete_levy, reviewed_wcb))
    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=request["request_reference"],
        reason_codes=(PayrollBlockReasonCode.OTHER,),
    )

    with pytest.raises(
        ValidationError,
        match="reviewed employer applicability decision requires qualified review and effective-date evidence",
    ):
        contract.CanadianPayrollEvaluation(request=request, result=blocked)


def test_unreviewed_applicability_cannot_carry_reviewed_configuration_snapshot():
    decisions = (
        {
            "requirement": "employer_levy",
            "decision": "unreviewed",
            "employer_configuration_snapshot": _employer_configuration_snapshot(
                "employer_levy"
            ).model_dump(mode="python"),
        },
        {
            "requirement": "workers_compensation",
            "decision": "unreviewed",
        },
    )
    request = _raw_request_with_decisions(decisions)
    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=request["request_reference"],
        reason_codes=(PayrollBlockReasonCode.MISSING_REVIEWED_COMPONENT,),
    )

    with pytest.raises(
        ValidationError,
        match="unreviewed employer applicability decision must not carry employer configuration snapshot",
    ):
        contract.CanadianPayrollEvaluation(request=request, result=blocked)


@pytest.mark.parametrize(
    "effective_from,effective_to,effective_date_basis",
    [
        (date(2026, 5, 1), date(2026, 5, 7), "full_pay_period"),
        (date(2026, 5, 12), date(2026, 5, 12), "pay_date"),
    ],
)
def test_calculated_result_accepts_current_reviewed_not_applicable_decisions(
    effective_from, effective_to, effective_date_basis
):
    request = _applicability_test_request(
        effective_from=effective_from,
        effective_to=effective_to,
        effective_date_basis=effective_date_basis,
    )
    result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
    )

    assert contract.CanadianPayrollEvaluation(request=request, result=result)


def test_unbounded_not_applicable_decision_is_not_representable():
    with pytest.raises(
        ValidationError,
        match="reviewed employer applicability decision requires qualified review and effective-date evidence",
    ):
        _applicability_test_request()


@pytest.mark.parametrize(
    "effective_from,effective_to,effective_date_basis",
    [
        (date(2026, 5, 1), date(2026, 5, 6), "full_pay_period"),
        (date(2026, 5, 11), date(2026, 5, 11), "pay_date"),
    ],
)
def test_calculated_result_rejects_stale_not_applicable_decision_windows(
    effective_from, effective_to, effective_date_basis
):
    request = _applicability_test_request(
        effective_from=effective_from,
        effective_to=effective_to,
        effective_date_basis=effective_date_basis,
    )
    result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
    )

    with pytest.raises(ValidationError, match="applicability decision.*must cover"):
        contract.CanadianPayrollEvaluation(request=request, result=result)


def test_incomplete_applicability_decision_is_usable_only_for_blocked_result():
    request = _applicability_test_request(reviewed=False)
    blocked = BlockedPayrollResult(
        status="blocked",
        request_reference=request.request_reference,
        reason_codes=(PayrollBlockReasonCode.MISSING_REVIEWED_COMPONENT,),
    )
    assert contract.CanadianPayrollEvaluation(request=request, result=blocked)

    result = _structural_calculated_result(
        request_reference=request.request_reference,
        employee_reference=request.employee_reference,
        pay_period=request.pay_period,
    )
    with pytest.raises(
        ValidationError,
        match="unreviewed employer applicability decision must be blocked",
    ):
        contract.CanadianPayrollEvaluation(request=request, result=result)


def test_applicability_decision_effective_window_must_be_ordered():
    with pytest.raises(ValidationError, match="applicability decision end must not precede its start"):
        contract.EmployerRequirementApplicability(
            requirement="employer_levy",
            decision="reviewed_not_applicable",
            review_attestation_reference="structural-review",
            reviewer_qualification_reference="structural-qualification",
            effective_from=date(2026, 5, 13),
            effective_to=date(2026, 5, 12),
            effective_date_basis="pay_date",
        )
