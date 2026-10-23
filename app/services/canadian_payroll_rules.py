"""Fail-closed infrastructure for reviewed Canadian payroll rule snapshots.

This module deliberately contains no deduction formulas or seeded tax values.
Callers must supply an explicitly reviewed, source-cited ruleset; no network
access, fallback jurisdiction, or nearest-year selection is performed here.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from urllib.parse import urlsplit


SUPPORTED_PROVINCES = frozenset({"AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "SK"})
MINIMUM_SUPPORTED_DATE = date(2026, 1, 1)


class PayrollRuleRegistryError(ValueError):
    """Base error for unsupported or invalid Canadian payroll rule data."""


class InvalidRuleSetError(PayrollRuleRegistryError):
    """A rule set or its source metadata is incomplete or malformed."""


class UnsupportedJurisdictionError(PayrollRuleRegistryError):
    """A jurisdiction is outside the approved provincial-only scope."""


class UnsupportedPayDateError(PayrollRuleRegistryError):
    """No explicitly registered rule set covers the requested pay date."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRuleSetError(f"{field} must be a non-empty string")
    return value


def _require_date(value: object, field: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise InvalidRuleSetError(f"{field} must be a calendar date")
    return value


def _freeze_value(value: object, ancestors: frozenset[int] = frozenset()) -> object:
    """Copy supported data values into immutable JSON-like containers."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidRuleSetError("rule values cannot contain non-finite numbers")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise InvalidRuleSetError("rule values cannot contain non-finite numbers")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in ancestors:
            raise InvalidRuleSetError("rule values cannot contain recursive mappings")
        next_ancestors = ancestors | {identity}
        keys = tuple(value.keys())
        if any(not isinstance(key, str) for key in keys):
            raise InvalidRuleSetError("rule value mapping keys must be strings")
        frozen: dict[str, object] = {}
        for key in sorted(keys):
            frozen[key] = _freeze_value(value[key], next_ancestors)
        return MappingProxyType(frozen)
    if isinstance(value, (tuple, list)):
        identity = id(value)
        if identity in ancestors:
            raise InvalidRuleSetError("rule values cannot contain recursive sequences")
        next_ancestors = ancestors | {identity}
        return tuple(_freeze_value(item, next_ancestors) for item in value)
    raise InvalidRuleSetError(f"unsupported rule value type: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class OfficialSource:
    """Metadata for reviewer-attested official sources.

    Shape is validated here; publisher authenticity and source content require
    human review and are never inferred from the HTTPS URL alone.
    """

    source_id: str
    title: str
    url: str
    publisher: str
    source_version: str
    reference: str
    accessed_on: date

    def __post_init__(self) -> None:
        for field in ("source_id", "title", "publisher", "source_version", "reference"):
            _require_text(getattr(self, field), field)
        _require_date(self.accessed_on, "accessed_on")
        _require_text(self.url, "url")
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise InvalidRuleSetError("source URL must be an HTTPS URL with a host")


@dataclass(frozen=True, slots=True)
class PayrollRule:
    """One immutable value and the official evidence/review method supporting it."""

    rule_id: str
    value: object
    sources: tuple[OfficialSource, ...]
    verification_method: str

    def __post_init__(self) -> None:
        _require_text(self.rule_id, "rule_id")
        _require_text(self.verification_method, "verification_method")
        try:
            sources = tuple(self.sources)
        except TypeError as exc:
            raise InvalidRuleSetError("sources must be a non-empty collection") from exc
        if not sources or any(not isinstance(source, OfficialSource) for source in sources):
            raise InvalidRuleSetError("each rule must cite at least one official source")
        object.__setattr__(self, "sources", tuple(sorted(sources, key=lambda source: source.source_id)))
        object.__setattr__(self, "value", _freeze_value(self.value))


@dataclass(frozen=True, slots=True)
class PayrollRuleSet:
    """A versioned provincial rules snapshot valid on [effective_from, effective_to)."""

    jurisdiction: str
    tax_year: int
    effective_from: date
    effective_to: date
    version: str
    rules: tuple[PayrollRule, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.jurisdiction, str)
            or self.jurisdiction not in SUPPORTED_PROVINCES
        ):
            raise UnsupportedJurisdictionError(
                f"unsupported jurisdiction {self.jurisdiction!r}; only the nine provinces are supported"
            )
        if not isinstance(self.tax_year, int) or isinstance(self.tax_year, bool):
            raise InvalidRuleSetError("tax_year must be an integer")
        if self.tax_year < MINIMUM_SUPPORTED_DATE.year:
            raise InvalidRuleSetError("tax_year must be 2026 or later")
        start = _require_date(self.effective_from, "effective_from")
        end = _require_date(self.effective_to, "effective_to")
        if start >= end:
            raise InvalidRuleSetError("effective interval must have start before end")
        if start < MINIMUM_SUPPORTED_DATE:
            raise InvalidRuleSetError("rule sets cannot start before 2026-01-01")
        if start.year != self.tax_year:
            raise InvalidRuleSetError("effective_from year must equal tax_year")
        next_year = date(self.tax_year + 1, 1, 1)
        if end > next_year:
            raise InvalidRuleSetError("effective interval cannot extend beyond its tax year")
        _require_text(self.version, "version")
        try:
            rules = tuple(self.rules)
        except TypeError as exc:
            raise InvalidRuleSetError("rules must be a non-empty collection") from exc
        if not rules or any(not isinstance(rule, PayrollRule) for rule in rules):
            raise InvalidRuleSetError("a rule set must contain reviewed PayrollRule entries")
        identifiers = [rule.rule_id for rule in rules]
        if len(identifiers) != len(set(identifiers)):
            raise InvalidRuleSetError("duplicate rule identifiers are not allowed")
        object.__setattr__(self, "rules", tuple(sorted(rules, key=lambda rule: rule.rule_id)))

    def covers(self, pay_date: date) -> bool:
        """Return whether this ruleset covers pay_date (inclusive/exclusive bounds)."""
        return self.effective_from <= pay_date < self.effective_to


class PayrollRuleRegistry:
    """Immutable resolver for company-level provinces and explicit rule sets.

    The caller supplies the company's effective province for each pay date;
    this registry has no employee-level jurisdiction or assignment-history data.
    Workplace regulation classification is also upstream, so callers must not
    invoke it for federal, territorial, or Québec workplaces.
    """

    __slots__ = ("_rule_sets",)

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError("PayrollRuleRegistry is immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("PayrollRuleRegistry is immutable")

    def __init__(self, rule_sets: Iterable[PayrollRuleSet]) -> None:
        try:
            entries = tuple(rule_sets)
        except TypeError as exc:
            raise InvalidRuleSetError("rule_sets must be a collection") from exc
        if not entries or any(not isinstance(entry, PayrollRuleSet) for entry in entries):
            raise InvalidRuleSetError("registry must contain one or more PayrollRuleSet entries")

        sorted_entries = tuple(
            sorted(entries, key=lambda entry: (entry.jurisdiction, entry.effective_from, entry.version))
        )
        seen_versions: set[tuple[str, str]] = set()
        by_jurisdiction: dict[str, list[PayrollRuleSet]] = {}
        for entry in sorted_entries:
            version_key = (entry.jurisdiction, entry.version)
            if version_key in seen_versions:
                raise InvalidRuleSetError(
                    f"duplicate version {entry.version!r} for {entry.jurisdiction}"
                )
            seen_versions.add(version_key)
            by_jurisdiction.setdefault(entry.jurisdiction, []).append(entry)

        for jurisdiction, province_sets in by_jurisdiction.items():
            for previous, current in zip(province_sets, province_sets[1:]):
                if current.effective_from < previous.effective_to:
                    raise InvalidRuleSetError(
                        f"overlapping rule-set intervals for {jurisdiction}: "
                        f"{previous.version} and {current.version}"
                    )
        self._rule_sets = sorted_entries

    @property
    def rule_sets(self) -> tuple[PayrollRuleSet, ...]:
        """All immutable registered versions, in stable jurisdiction/date order."""
        return self._rule_sets

    def resolve(self, jurisdiction: str, pay_date: date) -> PayrollRuleSet:
        """Return the single ruleset covering jurisdiction and pay_date, or fail closed."""
        if (
            not isinstance(jurisdiction, str)
            or jurisdiction not in SUPPORTED_PROVINCES
        ):
            raise UnsupportedJurisdictionError(
                f"unsupported jurisdiction {jurisdiction!r}; only the nine provinces are supported"
            )
        if not isinstance(pay_date, date) or isinstance(pay_date, datetime):
            raise UnsupportedPayDateError("pay_date must be a calendar date")
        if pay_date < MINIMUM_SUPPORTED_DATE:
            raise UnsupportedPayDateError("pay dates before 2026-01-01 are unsupported")
        for entry in self._rule_sets:
            if entry.jurisdiction == jurisdiction and entry.covers(pay_date):
                return entry
        raise UnsupportedPayDateError(
            f"no reviewed {jurisdiction} rule set covers pay date {pay_date.isoformat()}"
        )
