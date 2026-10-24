# Canadian Payroll Component Coverage Inventory — Pre-Review Draft

**Status: DRAFT / UNREVIEWED.** This is a scope inventory for preparing the A3 coverage catalogue and qualified review. It is not an authoritative legal, tax, payroll, or applicability map; it does not establish that any component is applicable or not applicable for a particular employer, worker, period, or province. Canadian calculations and outputs remain blocked.

## Purpose and source of scope

This inventory operationalizes the launch features in [issue #7](https://github.com/devlinsw/SlowBooks-Pro-2026/issues/7) and the acceptance conditions in [issue #15](https://github.com/devlinsw/SlowBooks-Pro-2026/issues/15). It must be reconciled by a qualified payroll/tax reviewer before it can become an authoritative required-component catalogue. The companion [source-version register](canadian-payroll-source-register.md) records source identities and visible currency signals; source discovery is not legal interpretation or coverage approval. The [calculator contract](canadian-calculator-contract.md) remains a non-calculating schema draft. The open A2 questions for gross-up, supplemental wages, and garnishments are also recorded in the [U.S. payroll assumptions inventory](us-payroll-assumptions-inventory.md); this draft does not settle their Canadian launch disposition.

Launch scope is provincial employment in AB, BC, MB, NB, NL, NS, ON, PE, and SK; Québec, territories, and federally regulated employment remain unsupported. Supported worker categories are part-time hourly, full-time hourly, and salaried. Frequencies are daily, weekly, bi-weekly, semi-monthly (twice per month), and monthly. The target year is 2026. These are owner-approved product boundaries, not findings about statutory applicability.

## Coverage-state rules

- **UNREVIEWED** is the current state for every component and province in this draft. It blocks calculation; it is not equivalent to zero, exempt, or not applicable.
- A reviewer may mark a component `applicable` or `reviewed_not_applicable` only with component-specific legal/source rationale, effective dates, scope conditions, and a qualified review record. Do not infer N/A from a missing source or an empty output.
- A located source is not evidence that its amendment chain is current through a target pay date. Record edition, effective dates, currency signals, and unresolved conflicts exactly; see the [source-version register](canadian-payroll-source-register.md#federal-cra-version-anchors) and its [province source/version map](canadian-payroll-source-register.md#province-sourceversion-map).
- This draft contains no rates, formulas, numeric examples, legal interpretations, employer-specific classifications, or expected payroll amounts.

## Required component families to enumerate and review

“Required” below means required product coverage by the approved launch scope. It does not declare that every individual employee receives or owes every item.

| Component family | Required review coverage before any calculation | Source/review status |
|---|---|---|
| Federal income-tax withholding | Applicable federal source edition by pay date; employee elections and eligibility; each supported earning/benefit base; frequency, rounding, YTD, and year-transition behavior. | UNREVIEWED. CRA edition pointers are in the source register; no values or calculation method are approved here. |
| Provincial income-tax withholding | For each supported province and pay-date window: source version, employee tax elections and eligibility, bases, frequency, rounding, YTD, and transitions. | UNREVIEWED for all nine provinces; currency signals and source rows are in the source register. |
| CPP and CPP2 — employee deductions | Separate component identities and bases; age/eligibility and exemptions; annual ceilings, prior YTD, pay-frequency treatment, effective-date transitions, and source versions. | UNREVIEWED. CRA edition pointers only; no rate, threshold, exemption, or expected result is approved. |
| CPP and CPP2 — employer contributions | Separate employer-side outputs and bases; matching eligibility/exception rules, ceilings, YTD, transitions, and source versions. | UNREVIEWED. No generic contribution fallback is permitted. |
| EI — employee premiums | Insurability/eligibility and exceptions, assessable earnings base, annual maximum/YTD, pay-frequency treatment, source version, and transition behavior. | UNREVIEWED. CRA edition pointers only; no rate, maximum, or expected result is approved. |
| EI — employer premium | Employer rate/multiplier and any approved adjustments; assessable base, annual limits, source versions, and employer-specific configuration requirements. | UNREVIEWED. No generic or zero-rate fallback is permitted. |
| Regular wages, salary, and benefits | Enumerate every supported earning and benefit type, taxable/insurable/assessable treatments, each statutory earnings base, interaction with hours and pay frequency, and prior-YTD contribution bases. | UNREVIEWED. The complete earning/benefit taxonomy and bases have not been approved. |
| Gross-up requests | Record whether Canadian gross-up is supported or blocked; if supported, capture inputs, jurisdiction/pay-date handling, affected withholding and contribution components, source/version dependencies, and output interaction. Do not reuse U.S. gross-up calculations. | UNREVIEWED. Canadian launch disposition, method, and expected amount are not approved. |
| Supplemental / irregular wages | Record the launch disposition, then enumerate each supported supplemental earnings type and its withholding, contribution, and other statutory bases by province, frequency, and effective date; identify source versions and exceptions. | UNREVIEWED. Canadian scope and treatment are not approved; do not assume U.S. supplemental-wage behavior. |
| Garnishments | Record the launch disposition; if supported, identify garnishment types, order priority, protected/available earnings bases, net-pay interaction, and province-specific source/version requirements. | UNREVIEWED. Canadian scope and treatment are not approved; do not reuse U.S. priority, limit, or net-pay behavior. |
| Provincial overtime | For each province: thresholds, eligible worker classes, exclusions, agreements/averaging, rates, hours/base inputs, pay-period timing, and cross-period treatment, with source version and effective window. | UNREVIEWED; same-period cross-province work remains blocked. Province source leads are in the source register, not approved rules. |
| Vacation pay | For each province: entitlement and calculation bases, eligible earnings, timing, vacation taken/paid, exceptions, and effective windows. | UNREVIEWED; no rate, basis, or N/A decision is approved. |
| Public/statutory holiday pay | For each province: qualifying conditions, eligible earnings and lookback/base, holiday timing, worker category, exceptions, and effective windows. | UNREVIEWED; no formula or applicability decision is approved. |
| Termination and final pay | For each province: notice/termination entitlements, final-pay components and deadlines, included bases, exceptions, and source versions. | UNREVIEWED; no timing or legal interpretation is approved. |
| Provincial employer payroll levies | Identify every potentially applicable levy for each province, employer thresholds/status, taxable payroll base, effective dates, and employer-specific configuration. | UNREVIEWED for all provinces. Missing source evidence never means no levy or zero liability. |
| Workers’ compensation / WCB | For each province: board source/version, employer classification and account, assessable-wage base, rate, effective dates, adjustments, and review evidence. | UNREVIEWED. Employer-specific classification and account inputs are absent; no generic rate or N/A is permitted. |
| Year-to-date and distinct earnings/contribution bases | Enumerate every separate base, annual limit, exemption, adjustment, and YTD source required by the reviewed components; test pay-date transitions and preserved historical periods. | UNREVIEWED. The contract requires distinct bases but does not yet prove the complete base catalogue. |

## Output and cross-cutting acceptance (separate from statutory components)

This inventory does not certify product setup, processing, or output behavior. Each output below is a distinct launch acceptance item, described in the [Canadian payroll design](canadian-payroll.md#reporting-artifacts-and-operating-boundary):

| Output / feature | Required review before enablement | Status |
|---|---|---|
| Net pay | Reconcile to independently reviewed earnings, deductions, contributions, levies, WCB, and garnishment results; do not infer the calculation from a balanced stub. | UNREVIEWED / BLOCKED |
| Canadian pay statement, PDF, and employee portal | For each province, verify statutory pay-statement requirements, Canadian terminology, pay-period/jurisdiction snapshot, totals, YTD, SIN masking, authorization, accessible labels, and consistency with the same reviewed calculation. | UNREVIEWED / BLOCKED |
| CAD cheque and payment record | Verify CAD amount/payee/date, printable cheque and payment recording, and reconciliation with net pay; no direct deposit or bank-file output is in scope. | UNREVIEWED / BLOCKED |
| T4 slips | Verify reporting-year-specific fields and layouts against the applicable CRA forms and guide; no CRA filing is included. | UNREVIEWED / BLOCKED |
| T4 Summary | Verify annual totals reconcile across T4 slips and use the applicable reporting-year form. | UNREVIEWED / BLOCKED |
| T4 XML export | Validate format/content against the applicable CRA XML specification and reject invalid output; no transmission is included. | UNREVIEWED / BLOCKED |
| PD7A internal remittance / reconciliation summary | Verify an internal printable summary against applicable remittance data; it is not a CRA-issued statement/voucher, filing, or payment integration. | UNREVIEWED / BLOCKED |
| Manual ROE worksheet | Verify against the applicable Service Canada paper-form guidance; it is not a serialized ROE form, ROE Web submission, or filing integration. | UNREVIEWED / BLOCKED |

Cross-cutting acceptance also includes one payroll country per company; effective-dated employee province history and whole-inclusive-period jurisdiction; cross-boundary periods blocked; employee setup/elections and earnings/benefit inputs; pre-post review and fail-closed missing-input/unsupported-case errors; and no U.S. calculation or U.S.-formatted output for Canadian periods while preserving valid posted history. These checks are tracked in issues #7, #14, and #15. Existing jurisdiction safety guards do not mean Canadian calculations or any listed outputs are implemented or ready.

## Province disposition snapshot

Every cell below means “review not completed”; it is not a legal applicability determination. Province-specific source pointers and unresolved currency signals are maintained in the linked source register.

| Province | Income tax / CPP / CPP2 / EI | Employment standards components | Gross-up / supplemental wages / garnishments | Employer levies | WCB | Overall disposition |
|---|---|---|---|---|---|---|
| AB | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | BLOCKED |
| BC | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | BLOCKED |
| MB | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | BLOCKED |
| NB | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | BLOCKED |
| NL | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | BLOCKED |
| NS | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | BLOCKED |
| ON | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | BLOCKED |
| PE | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | BLOCKED |
| SK | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | UNREVIEWED | BLOCKED |

## Cross-scenario acceptance grid

For each reviewed component and each applicable province/source window, issue #15 still requires source-versioned inputs and independently reviewed expected outputs across the confirmed worker categories and pay frequencies. The final catalogue must state the exact scenario dimensions and identify every required earnings/deduction base; this draft does not claim that the scenario list or base taxonomy is complete. Same-period cross-province work stays blocked until allocation rules are designed and reviewed.

The reviewer record for each catalogue entry must include at least:

- stable component ID and component family;
- jurisdiction and applicable worker/frequency dimensions;
- primary source title, URL, exact edition/version, effective window, visible currency signal, and pinpoint sections;
- applicability status and reason, including explicit reviewed N/A where justified;
- included/excluded earnings bases, YTD/annual-limit inputs, exceptions, and rounding/timing conventions;
- source-versioned fixture IDs and expected outputs, independently derived and checked;
- reviewer name, qualification/credential verification, relevant experience, review date, attestation, and conflict disclosure.

## Gate before examples or formulas

1. A qualified reviewer reconciles the complete component and earnings-base universe against the official source chain for each supported jurisdiction and pay-date window.
2. The reviewer records every component as applicable, reviewed-not-applicable, or still unreviewed; any unreviewed item keeps the relevant calculation blocked.
3. Only after the catalogue and source currency are accepted may source-versioned numerical fixtures be prepared. Do not invent rates, formulas, expected amounts, or N/A dispositions.
4. Each expected output must receive independent payroll/tax review before any calculation path or Canadian output is enabled.

**This draft is a preparation artifact only. It does not satisfy issue #15 acceptance, complete prerequisite issue #14, approve any component, or make Canadian payroll calculation- or release-ready.**
