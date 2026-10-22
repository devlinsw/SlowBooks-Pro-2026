from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pytest

from app.services.canadian_payroll_rules import (
    OfficialSource,
    PayrollRule,
    PayrollRuleRegistry,
    PayrollRuleSet,
    UnsupportedJurisdictionError,
    UnsupportedPayDateError,
    InvalidRuleSetError,
)


def make_source(**overrides):
    values = {
        "source_id": "demo-source-1",
        "title": "Demonstration government publication",
        "url": "https://www.canada.ca/en/example.html",
        "publisher": "Government of Canada",
        "source_version": "demonstration-edition-1",
        "reference": "Section 1",
        "accessed_on": date(2026, 10, 22),
    }
    values.update(overrides)
    return OfficialSource(**values)


def make_rule(rule_id="demo-rule", value=None, sources=None, method="manual comparison"):
    return PayrollRule(
        rule_id=rule_id,
        value={"marker": "reviewed"} if value is None else value,
        sources=(make_source(),) if sources is None else sources,
        verification_method=method,
    )


def make_set(
    *,
    province="AB",
    tax_year=2026,
    start=date(2026, 1, 1),
    end=date(2027, 1, 1),
    version="ab-demo-2026.1",
    rules=None,
):
    return PayrollRuleSet(
        jurisdiction=province,
        tax_year=tax_year,
        effective_from=start,
        effective_to=end,
        version=version,
        rules=(make_rule(),) if rules is None else rules,
    )


def test_resolve_uses_inclusive_start_exclusive_end_and_tax_year():
    january = make_set(start=date(2026, 1, 1), end=date(2026, 7, 1))
    july = make_set(
        start=date(2026, 7, 1),
        end=date(2027, 1, 1),
        version="ab-demo-2026.2",
    )
    registry = PayrollRuleRegistry((january, july))

    assert registry.resolve("AB", date(2026, 1, 1)) is january
    assert registry.resolve("AB", date(2026, 6, 30)) is january
    assert registry.resolve("AB", date(2026, 7, 1)) is july
    assert registry.resolve("AB", date(2026, 12, 31)).tax_year == 2026


def test_resolve_rejects_gaps_and_dates_before_supported_start():
    registry = PayrollRuleRegistry(
        (make_set(start=date(2026, 1, 1), end=date(2026, 6, 1)),)
    )

    with pytest.raises(UnsupportedPayDateError):
        registry.resolve("AB", date(2026, 6, 1))
    with pytest.raises(UnsupportedPayDateError):
        registry.resolve("AB", date(2025, 12, 31))


def test_registry_rejects_overlapping_intervals_for_same_province():
    first = make_set(start=date(2026, 1, 1), end=date(2026, 8, 1))
    second = make_set(
        start=date(2026, 7, 1),
        end=date(2027, 1, 1),
        version="ab-demo-2026.2",
    )

    with pytest.raises(InvalidRuleSetError, match="overlap"):
        PayrollRuleRegistry((first, second))


def test_resolve_rejects_unsupported_jurisdictions():
    registry = PayrollRuleRegistry((make_set(),))
    for jurisdiction in ("QC", "YT", "NT", "NU", "CA-FED", "ZZ", "ab", []):
        with pytest.raises(UnsupportedJurisdictionError):
            registry.resolve(jurisdiction, date(2026, 5, 1))


def test_rule_set_rejects_non_string_jurisdiction():
    with pytest.raises(UnsupportedJurisdictionError):
        make_set(province=[])



def test_each_supported_province_can_resolve_its_own_rule_set():
    provinces = ("AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "SK")
    registry = PayrollRuleRegistry(
        make_set(province=province, version=f"{province}-demo-2026.1")
        for province in provinces
    )

    assert {entry.jurisdiction for entry in registry.rule_sets} == set(provinces)
    for province in provinces:
        assert registry.resolve(province, date(2026, 3, 1)).jurisdiction == province


def test_resolve_does_not_fall_forward_to_another_year_or_province():
    registry = PayrollRuleRegistry((make_set(),))

    with pytest.raises(UnsupportedPayDateError):
        registry.resolve("AB", date(2027, 1, 1))
    with pytest.raises(UnsupportedPayDateError):
        registry.resolve("BC", date(2026, 4, 1))



def test_rule_set_requires_nonblank_immutable_version():
    with pytest.raises(InvalidRuleSetError, match="version"):
        make_set(version=" ")


def test_rule_requires_source_metadata_and_verification_method():
    with pytest.raises(InvalidRuleSetError, match="source"):
        make_rule(sources=())
    with pytest.raises(InvalidRuleSetError, match="verification"):
        make_rule(method="  ")


def test_source_metadata_requires_official_reference_and_https_url():
    with pytest.raises(InvalidRuleSetError):
        make_source(url="http://www.canada.ca/en/example.html")
    with pytest.raises(InvalidRuleSetError):
        make_source(reference=" ")


def test_rule_payload_is_deeply_immutable_and_registry_is_reproducible():
    payload = {"thresholds": [1, {"label": "original"}]}
    rule = make_rule(value=payload)
    entry = make_set(rules=(rule,))
    registry = PayrollRuleRegistry((entry,))
    payload["thresholds"][1]["label"] = "changed"
    payload["thresholds"].append(2)

    resolved = registry.resolve("AB", date(2026, 4, 1))
    assert resolved is registry.resolve("AB", date(2026, 4, 1))
    assert resolved.version == "ab-demo-2026.1"
    assert resolved.rules[0].value["thresholds"] == (1, {"label": "original"})
    with pytest.raises(TypeError):
        resolved.rules[0].value["thresholds"][1]["label"] = "mutated"
    with pytest.raises(FrozenInstanceError):
        resolved.version = "changed"


def test_rule_payload_mapping_order_is_canonical():
    first = make_rule(value={"z-last": 1, "a-first": 2})
    second = make_rule(value={"a-first": 2, "z-last": 1})

    assert tuple(first.value) == ("a-first", "z-last")
    assert tuple(second.value) == ("a-first", "z-last")


def test_malformed_rule_sets_and_pay_dates_fail_closed():
    with pytest.raises(InvalidRuleSetError):
        make_set(start=date(2026, 8, 1), end=date(2026, 7, 1))
    with pytest.raises(InvalidRuleSetError):
        make_set(tax_year=2025)
    with pytest.raises(InvalidRuleSetError):
        make_set(tax_year=2026, end=date(2027, 1, 2))
    registry = PayrollRuleRegistry((make_set(),))
    with pytest.raises(UnsupportedPayDateError):
        registry.resolve("AB", datetime(2026, 4, 1, 12, 0))


def test_duplicate_rule_identifiers_are_rejected():
    with pytest.raises(InvalidRuleSetError, match="duplicate"):
        make_set(rules=(make_rule("same"), make_rule("same")))


def test_registry_cannot_be_mutated_after_validation():
    registry = PayrollRuleRegistry((make_set(),))

    with pytest.raises(AttributeError):
        registry._rule_sets = ()


def test_registry_state_cannot_be_deleted_and_resolve_remains_functional():
    registry = PayrollRuleRegistry((make_set(),))

    with pytest.raises(AttributeError):
        del registry._rule_sets

    assert registry.resolve("AB", date(2026, 4, 1)).version == "ab-demo-2026.1"
