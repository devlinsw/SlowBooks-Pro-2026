# Canadian payroll calculator contract draft

**Status: DRAFT ONLY — A3 remains OPEN and incomplete.** This document specifies a typed interface boundary, not a payroll implementation.

## Scope boundary

- Supported province codes are AB, BC, MB, NB, NL, NS, ON, PE, and SK only.
- Québec, every territory, and federally regulated employment are explicitly unsupported. They must be blocked; do not reinterpret them as a supported province.
- Supported worker categories are part-time hourly, full-time hourly, and salaried.
- Supported pay frequencies are daily, weekly, biweekly, semi-monthly (twice monthly), and monthly.
- Currency is CAD only. The request records the company's payroll-country history as effective-dated CA or US assignments. Assignments must cover the full inclusive pay period without gaps or overlaps. A calculation is not permitted if any part of that period is assigned to the US; this contract adds no US-calculation behavior.
- The employee's effective-dated province assignments must cover the whole inclusive pay period without gaps or overlaps. A period containing more than one province is represented as input facts but must return `blocked` with a cross-province reason; it must not be calculated under a single-province assumption.
- Employment regulatory scope is explicit. A federally regulated request must be paired with a blocked result carrying the federally-regulated-employment reason.

The pay-period record contains the full period and the actual pay date. The CRA identifies the 122nd T4127 edition as effective January 1, 2026 and the 123rd edition as effective July 1, 2026 [1][2]. CRA PDOC describes July changes in relation to the entered employee pay date, including when that date is July 1, 2026 or later [3]. This contract records the date only; it does not select, interpret, or execute a rule bundle.

## Request contract

`CanadianPayrollRequest` carries:

- A nonblank request reference, company and employee references, effective-dated company payroll-country assignments, CAD currency, worker category, pay frequency, and regulatory scope.
- The full inclusive pay period and pay date.
- Employee-specific province-of-employment segments, each with an effective interval and one supported province code. The segments must fully cover the period. A within-period province change is a block condition, not an invitation to choose one segment.
- References to reviewed employee tax-election and eligibility records. A reference is not a substitute for checking applicability or completeness.
- Itemized earning facts, each tied to a source record and any relevant earnings-basis codes.
- Prior year-to-date amounts kept separately by distinct contribution or earnings basis. Amounts use the exact-decimal contract type; binary floating-point values are rejected.
- Explicit reviewed applicability evidence for both requirement categories represented here: employer levy and workers' compensation. Each decision requires review-attestation and reviewer-qualification references. An `applicable` decision also requires an immutable employer-specific configuration snapshot with its own version, digest, review-attestation, and reviewer-qualification references; `reviewed_not_applicable` is an explicit reviewed decision, not an empty/default state. The contract does not state that either category is applicable or not applicable for any province, and a missing decision never implies no liability.

Unsupported jurisdictions and employment cases are outside the supported province type. A caller must return an unsupported-jurisdiction or federally-regulated-employment block rather than silently mapping them to another rule set. Unsupported raw jurisdiction codes cannot be represented as a typed request; they may use a request-less blocked outcome whose required request reference is the raw-input correlation reference. Typed federal, country-history, and cross-province blocks remain bound to their valid request.

## Result contract

`CanadianPayrollEvaluation` binds a typed request to its result using the request reference. If no valid typed request exists, a request-less outcome is still bound by the required request reference as a raw-input correlation reference. A calculated result must match the request's employee, period, currency, effective-dated country context, regulatory scope, and single province. A result for a different request cannot be paired by supplying an unrelated result object.

The discriminated result has three statuses:

- `calculated`: carries itemized earnings and bases, employee deductions, generic employer contributions explicitly marked non-WCB, approved employer levies, explicit approved workers' compensation outputs, totals, warnings, an immutable jurisdiction snapshot, and immutable rule snapshots. It is allowed only for a provincially regulated request whose company payroll-country assignment is CA throughout the period and whose employee province is stable throughout the period. Calculated results have no block-reasons field. Each output component is bound to one exact rule-snapshot reference, version, and digest, and carries exact source-snapshot references, versions, and digests plus qualified review-attestation and reviewer-qualification references. Each component's complete source identity must equal an entry in that exact rule snapshot's source collection; component source metadata cannot be supplied independently. A result cannot contain conflicting snapshots for the same rule bundle. Every `applicable` levy or workers' compensation decision requires at least one corresponding output; each output must reference the exact reviewed configuration and snapshot carried by the request. A `reviewed_not_applicable` decision forbids the corresponding output. Workers' compensation uses its own linked output type, not a generic employer-contribution row.
- `blocked`: carries a request/correlation reference, reason codes, optional jurisdiction/rule snapshots, and warnings. It has no monetary totals. A request-less blocked outcome is allowed only for `unsupported_jurisdiction`; federal, country-history, and cross-province blocks for valid typed requests must stay request-bound. Missing or unreviewed employer evidence must never be represented as a calculated result.
- `invalid_input`: carries a request/correlation reference, reason codes, and warnings. It has no monetary totals and is allowed only when no valid typed request exists. Use it when required raw input is malformed or incomplete, including an invalid period (`invalid_pay_period`) or uncovered company/province jurisdiction history (`uncovered_jurisdiction_history`). A valid typed request cannot be paired with `invalid_input`.

When reviewed, `SourceSnapshot` and applicable `EmployerConfigurationSnapshot` records carry inclusive effective-from/to bounds and an explicit `effective_date_basis` (`pay_date` or `full_pay_period`). The source basis has qualified applicability-review references; the employer-configuration basis has its own qualified applicability-review references alongside the configuration review. Validation checks that each window covers the exact date or dates selected by its declared basis for the result/request. The basis is explicit reviewed metadata: this schema does not choose a source-specific legal basis, infer one, or assert provincial applicability. When review has not established a basis and effective window, those fields may remain unspecified for a blocked outcome; a calculated result requires complete reviewed date metadata.

Monetary fields accept `Decimal` values or decimal strings only and reject binary floating-point values. This is a representation guarantee, not a rounding or calculation policy. This contract defines no HTTP status codes, formulas, tax routing, calculator, or production behavior. Structural test placeholders do not establish numerical payroll results or provincial applicability.

## Coverage limitation

For A3 coverage, the schema only validates payload shape, provenance of present output rows, request/result boundary pairing, and the explicitly represented employer-levy and workers' compensation categories. It does **not** establish exhaustive income-tax, CPP, CPP2, EI, vacation, overtime, holiday, termination, or earnings-base coverage, and it does not supply an authoritative component-coverage catalogue. A `calculated` schema variant is not evidence of regulatory completeness or readiness. Full A3 and issue #15 remain OPEN/incomplete pending source-versioned independently approved outputs and an authoritative reviewed coverage catalogue. No acceptance criterion is marked complete by this schema draft.

## A3 acceptance remains open

This is a contract draft only. It adds no production calculator, formula, routing, numeric payroll example, calculated output, or readiness claim. A3 and issue #15 remain OPEN/incomplete: current levy/WCB and source-currency gaps remain unresolved, and qualified payroll/tax reviewer sign-off is still required. Independent review of numeric results is not supplied here. AI review cannot substitute for a qualified payroll/tax reviewer.

## Sources

[1] https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jul/t4127-jul-payroll-deductions-formulas.html
[2] https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jan/t4127-jan-payroll-deductions-formulas-computer-programs.html
[3] https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-businesses/payroll-deductions-online-calculator.html
