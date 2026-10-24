# Canadian payroll calculator contract draft

**Status: DRAFT ONLY — A3 remains OPEN and incomplete.** This document specifies a typed interface boundary, not a payroll implementation.

## Scope boundary

- Supported province codes are AB, BC, MB, NB, NL, NS, ON, PE, and SK only.
- Québec, every territory, and federally regulated employment are explicitly unsupported. They must be blocked; do not reinterpret them as a supported province.
- Supported worker categories are part-time hourly, full-time hourly, and salaried.
- Supported pay frequencies are daily, weekly, biweekly, semi-monthly (twice monthly), and monthly.
- A company operates in one country at a time. This Canadian contract accepts Canadian companies and CAD only. Province of employment is resolved for each employee, not selected once for a multi-province company.
- The employee's effective-dated province assignments must cover the whole inclusive pay period without gaps or overlaps. A period containing more than one province is represented as input facts but must return `blocked` with a cross-province reason; it must not be calculated under a single-province assumption.

The pay-period record contains the full period and the actual pay date. The CRA identifies the 122nd T4127 edition as effective January 1, 2026 and the 123rd edition as effective July 1, 2026 [1][2]. CRA PDOC describes July changes in relation to the entered employee pay date, including when that date is July 1, 2026 or later [3]. This contract records the date only; it does not select, interpret, or execute a rule bundle.

## Request contract

`CanadianPayrollRequest` carries:

- Company and employee references, the Canadian country marker, CAD currency, worker category, and pay frequency.
- The full inclusive pay period and pay date.
- Employee-specific province-of-employment segments, each with an effective interval and one supported province code. The segments must fully cover the period. A within-period province change is a block condition, not an invitation to choose one segment.
- References to reviewed employee tax-election and eligibility records. A reference is not a substitute for checking applicability or completeness.
- Itemized earning facts, each tied to a source record and any relevant earnings-basis codes.
- Prior year-to-date amounts kept separately by distinct contribution or earnings basis. Amounts use the exact-decimal contract type; binary floating-point values are rejected.
- Employer-specific levy and workers' compensation configuration references when applicable. Missing or unreviewed applicable employer configuration blocks a calculation; no generic or zero fallback is implied.

Unsupported jurisdictions and employment cases are outside the supported province type. A caller must return an unsupported-jurisdiction or federally-regulated-employment block rather than silently mapping them to another rule set.

## Result contract

The discriminated result has three statuses:

- `calculated`: carries itemized earnings and bases, employee deductions, employer contributions, approved employer levies, totals, warnings, an immutable jurisdiction snapshot, and immutable rule snapshots. Each output component requires component-level rule and source references. Every applied rule bundle must have a qualified review-attestation reference and reviewer-qualification reference. A calculated response is not valid when any applicable component is missing, unreviewed, or lacks complete provenance; the whole result must be blocked instead.
- `blocked`: carries reason codes, optional jurisdiction/rule snapshots, and warnings. It has no monetary totals. Use it when the request is structurally valid but the employment case is unsupported or an applicable rule, source, attestation, or employer configuration is absent or unreviewed.
- `invalid_input`: carries reason codes and warnings. It has no monetary totals. Use it when required input is malformed or incomplete, including an invalid period or province assignments that do not cover the full period.

Monetary fields accept `Decimal` values or decimal strings only and reject binary floating-point values. This is a representation guarantee, not a rounding or calculation policy. This contract defines no HTTP status codes, formulas, tax routing, calculator, or production behavior.

## A3 acceptance remains open

This is a contract draft only. It adds no production calculator, formula, routing, numeric payroll example, calculated output, or readiness claim. A3 remains OPEN/incomplete: current levy/WCB and source-currency gaps remain unresolved, and qualified payroll/tax reviewer sign-off is still required. Independent review of numeric results is not supplied here. AI review cannot substitute for a qualified payroll/tax reviewer.

## Sources

[1] https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jul/t4127-jul-payroll-deductions-formulas.html
[2] https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jan/t4127-jan-payroll-deductions-formulas-computer-programs.html
[3] https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-businesses/payroll-deductions-online-calculator.html
