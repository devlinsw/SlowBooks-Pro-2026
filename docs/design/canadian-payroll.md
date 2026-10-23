# Canadian payroll scope and source-to-requirement matrix

**Status: OWNER-APPROVED SCOPE; DESIGN / IMPLEMENTATION IN PROGRESS; NOT RELEASE-READY.**
Scope approval is not legal, tax, or payroll reviewer sign-off; none is recorded here. Source review checked on 2026-10-22. This document supersedes the payroll portion of [canada.md](canada.md); that document remains PARKED for its unrelated sales-tax and conversion material.

## Approved boundary

- Business-confirmed on 2026-10-23: launch covers provincially regulated workplaces in AB, BC, MB, NB, NL, NS, ON, PE, and SK. Québec and all territories are excluded. Federally regulated employment is excluded and must be blocked, not calculated using a provincial rule set. Each company runs payroll in only one country at a time; a Canadian company cannot also run U.S. payroll concurrently. Scope approval is not legal, tax, or payroll-review sign-off.
- Supported employee categories are part-time hourly, full-time hourly, and salaried employees (all types). All features listed in [Canadian payroll issue #7](https://github.com/devlinsw/SlowBooks-Pro-2026/issues/7) are intended for launch; specialized wage arrangements and statutory exemptions not stated as supported remain blocked pending review.
- A company may operate in multiple provinces concurrently. The design must resolve the applicable province of employment per employee and pay period, rather than selecting one province for the whole company. Rules for an employee whose work spans provinces within one pay period remain an A3 design/review item; block such cases until resolved. Jurisdiction changes are effective-dated and prospective only. Posted payroll history is immutable and must not be rewritten or recalculated by later changes.
- Canadian-period drafts must use validated Canadian payroll calculations; U.S. withholding must never be used. If a legacy U.S.-calculated draft's pay date is now covered by that employee's Canadian jurisdiction, block posting and exclude its values from Canadian YTD/paystubs until voided and recreated with Canadian calculations. Preserve valid pre-effective U.S. payroll history as immutable.
- The initial target payroll/tax year is 2026. Requested frequencies are daily, weekly, bi-weekly, semi-monthly (twice per month, not once every two months), and monthly. Federal and provincial income-tax withholding and federal CPP/CPP2/EI calculations use the CRA payroll guidance and edition effective for the pay date. For pay dates January 1–June 30, 2026, use the 122nd T4127 edition effective January 1; for pay dates July 1–December 31, use the 123rd edition effective July 1, referring to the 122nd edition for sections not reproduced in the July edition [1][2]. The CRA calculator identifies the employee's pay date as the date input for the July 1, 2026 changes [52]. Maintain reviewed, versioned rate/formula tables; do not silently download or activate changes. A future year without reviewed source data is not enabled.
- Include applicable provincial overtime, vacation pay, statutory/public holidays, termination, employer payroll levies, and WCB / workers' compensation premiums, subject to the matrix gaps and release gates below. Overtime must follow the applicable provincial rules and be paid in the configured pay frequency; timing and cross-period cases require legal/payroll review. WCB calculations require verified board sources, classification, and employer-specific account/rate inputs; never use a generic or zero fallback.
- Currency is CAD. Launch includes system-generated/printable cheques and pay statements. Statutory filing remains manual: no direct CRA or Service Canada submission, ROE Web filing, bank file, or direct-deposit integration is in scope.

## Source-to-requirement matrix

Source IDs link to the government pages in [Sources](#sources), retrieved or checked on 2026-10-22. The shared CRA T4127 references [1][2] apply to federal withholding and to the provincial withholding column in every province row. No statutory rates or calculation formulas are restated here; use the effective source and obtain review before implementation.

| Jurisdiction | Tax / payroll withholding | Overtime | Vacation pay | Public / statutory holidays | Termination | Statutory employer payroll levies | WCB / workers' compensation |
|---|---|---|---|---|---|---|---|
| **Federal (payroll layer)** | Federal and provincial withholding: CRA T4127 effective for the pay date [1][2]. | **Out of scope** for federally regulated employment; block rather than apply provincial overtime rules. | **Out of scope** for federally regulated employment; block. | **Out of scope** for federally regulated employment; block. | **Out of scope** for federally regulated employment; block. | Employer CPP and CPP2 contributions and EI premiums: current CRA references [4][5][6]. | Resolve under applicable provincial coverage; federally regulated employment is excluded. |
| **AB** | CRA T4127 province-specific withholding [1][2]. | Alberta overtime guidance [13]. | Alberta vacation-pay guidance [14]. | Alberta general-holiday guidance [15]. | Alberta termination / lay-off guidance [16]. | **OPEN:** confirm whether any additional provincial employer payroll levy applies; do not interpret an unlocated source as “none.” | **OPEN:** authoritative board source, classification and employer-account assessment inputs required; no generic rate or zero fallback. |
| **BC** | CRA T4127 province-specific withholding [1][2]. | B.C. overtime guidance [17]. | B.C. annual vacation guidance [18]. | B.C. statutory-holiday guidance [19]. | B.C. quitting / dismissal guidance [20]. | Employer health tax: current B.C. tax guidance [21]; employer applicability and calculations require tax review. | **OPEN:** authoritative board source, classification and employer-account assessment inputs required; no generic rate or zero fallback. |
| **MB** | CRA T4127 province-specific withholding [1][2]. | Manitoba overtime fact sheet [22]. | Manitoba vacation-pay fact sheet [23]. | Manitoba general-holidays fact sheet [24]. | Manitoba termination fact sheet [25]. | Health and Post-Secondary Education Tax Levy: Manitoba Finance employer-payroll guidance [26]; applicability and calculations require tax review. | **OPEN:** authoritative board source, classification and employer-account assessment inputs required; no generic rate or zero fallback. |
| **NB** | CRA T4127 province-specific withholding [1][2]. | New Brunswick wage / overtime guidance [37]. | New Brunswick vacation guidance and Employment Standards Act, s. 24(1.1) [38][54]. | New Brunswick paid-public-holiday guidance [38]. | New Brunswick termination guidance [39]. | **OPEN:** confirm whether any additional provincial employer payroll levy applies; do not interpret an unlocated source as “none.” | **OPEN:** authoritative board source, classification and employer-account assessment inputs required; no generic rate or zero fallback. |
| **NL** | CRA T4127 province-specific withholding [1][2]. | Labour Standards Act and Regulations [40][41]. | Labour Standards Act [40]. | Labour Standards Act [40]. | Labour Standards Act [40]. | Health and Post-Secondary Education Tax provisions (Revenue Administration Act, Part IV, ss. 73–74) [42]; current Finance guidance on employer applicability and parameters [55]; tax review required. | **OPEN:** authoritative board source, classification and employer-account assessment inputs required; no generic rate or zero fallback. |
| **NS** | CRA T4127 province-specific withholding [1][2]. | Nova Scotia overtime guidance [43]. | Nova Scotia vacation guidance [44]. | Labour Standards Code holiday guidance and separate Remembrance Day guidance [45][46]. | Nova Scotia employer-ending-employment guidance [47]. | **OPEN:** confirm whether any additional provincial employer payroll levy applies; do not interpret an unlocated source as “none.” | **OPEN:** authoritative board source, classification and employer-account assessment inputs required; no generic rate or zero fallback. |
| **ON** | CRA T4127 province-specific withholding [1][2]. | Ontario ESA overtime guide [27]. | Ontario ESA vacation guide [28]. | Ontario public-holiday guide, checked against current Employment Standards Act [29][56]. | Ontario ESA termination guide [30]. | Employer Health Tax: current Ontario tax guidance [31]; employer applicability and calculations require tax review. | **OPEN:** authoritative board source, classification and employer-account assessment inputs required; no generic rate or zero fallback. |
| **PE** | CRA T4127 province-specific withholding [1][2]. | Employment Standards Act reference consolidation [48], original official Act [57], and 2026 proclamation / new regulations [58]. | Employment Standards Act reference consolidation [48], original official Act [57], and 2026 proclamation / new regulations [58]. | Employment Standards Act reference consolidation [48], original official Act [57], and 2026 proclamation / new regulations [58]. | Employment Standards Act reference consolidation [48], original official Act [57], and 2026 proclamation / new regulations [58]. | **OPEN:** confirm whether any additional provincial employer payroll levy applies; do not interpret an unlocated source as “none.” | **OPEN:** authoritative board source, classification and employer-account assessment inputs required; no generic rate or zero fallback. |
| **SK** | CRA T4127 province-specific withholding [1][2]. | Saskatchewan overtime guidance and notice of 2026 amendments [32][36]. | Saskatchewan vacation and vacation-pay guidance [33]. | Saskatchewan public-holiday guidance [34]. | Saskatchewan individual layoff / termination guidance [35]. | **OPEN:** confirm whether any additional provincial employer payroll levy applies; do not interpret an unlocated source as “none.” | **OPEN:** authoritative board source, classification and employer-account assessment inputs required; no generic rate or zero fallback. |

### Coverage notes and unresolved source questions

- **Additional provincial employer payroll levies:** source research did not establish whether a levy applies in AB, NB, NS, PE, or SK. These remain OPEN research and reviewer items, not conclusions that those provinces have no levy. CPP/CPP2 and EI are common federal employer contributions and do not resolve the provincial-levy question.
- **WCB / workers' compensation:** included in launch scope by business decision. Province-specific board sources, classification, assessable-wage rules, effective schedules, and employer-account factors remain OPEN for all provinces; block calculation until the applicable inputs and rates are verified. Never infer a zero assessment.
- **NB vacation transition — exact text checked; complete-current-law and reviewer gates remain OPEN:** The retrieved text of Employment Standards Act s. 24(1.1) says “eight or more years” of continuous employment [54], whereas the government vacation page says “more than eight years” [38]. The official [54] page’s visible currency note says the Act is consolidated to June 12, 2026, but its raw HTML also contains a hidden `d-none` marker reading “Current to 1 January 2024”; these page metadata conflict, so the consolidation currency remains unresolved [54]. The separate 2026, c.3 amendment text adds a long-term illness and injury leave provision after s. 44.028, not s. 24(1.1) [59]. This targeted amendment check does not establish that all New Brunswick law is current; complete-current-law verification and employment-standards reviewer approval remain OPEN.
- **NL source currency and HAPSET:** the current official Assembly Regulations page lists amendments through 81/24, and the current Act page lists amendments through 2024 c.21 and c.35 [40][41]. Current Department of Finance guidance confirms HAPSET employer applicability, the published rate and threshold, and allocation guidance [55]. Tax applicability and calculations still require tax review; employment-standards interpretation and approval remain separate release gates.
- **ON public holidays:** the official guide remains marked “Updated: July 08, 2024” [29]. It has been checked against the current ESA consolidation, whose stated currency date is October 19, 2026 [56]. Use current legislation and applicable guidance rather than treating the dated guide as complete; holiday logic still requires reviewer approval.
- **PE source authority — partially resolved; current amendment check remains OPEN:** the official 2024 Act is chapter 66 and provides for commencement by proclamation [57]; the official Royal Gazette proclaims it effective June 30, 2026 and publishes the new Employment Standards Regulations [58]. The linked consolidation [48] says it is for reference only and is not the official version. Later authoritative Act/amendment text beyond these retrieved sources has not been verified; do not encode rules based only on the reference consolidation.
- Government guidance is a source map, not a legal opinion. Where a guidance page flags exceptions or special treatment, do not generalize those cases to supported employee categories; route them to a reviewer or block them.

## Reporting artifacts and operating boundary

- **T4 slips and T4 Summary:** use the CRA's current T4 and T4SUM form pages as layout references, selecting the form for the applicable reporting year [49][50]. Follow the current CRA filing guide for completion [7]. The CRA describes the T4 Summary as the annual totals reported across T4 slips [51].
- **CRA XML:** export T4 XML and validate format and content against the applicable CRA XML specifications / current T4 schema before it can be saved as ready for manual filing [8][9]. Validation is local; this does not submit or transmit the file to CRA.
- **PD7A:** provide a printable internal remittance and reconciliation summary aligned to CRA payroll-remittance guidance [3]. CRA describes PD7A as a statement for previous remittances plus a voucher for the next remittance, and identifies its displayed sample as the revised statement it began sending in May 2016 [10]. Do not treat that sample image as a current filing template; CRA identifies the PD7A remittance voucher as personalized and says most remittance vouchers cannot be printed at home [53]. The product artifact is not a CRA-issued statement or voucher and is not a payment or filing integration.
- **ROE:** provide a manual worksheet aligned to the current Service Canada guide's block-by-block instructions and Annex 2 blank-paper-ROE example [11]. The paper form is one page in triplicate with a pre-printed serial number; employers must order it through the Employer Contact Centre, so the worksheet is not a substitute for the serialized form [11][12]. Verify against these paper-form sources, not the legacy 2021 ROE Web layout. No ROE Web, electronic submission, or Service Canada filing is included.
- No direct CRA / Service Canada filing or submission and no bank-file / direct-deposit output; CAD cheques and pay statements are in launch scope.

## Unsupported cases — block, do not approximate

- Québec, the territories, and federally regulated employment.
- Union / collective-agreement rules, industry or statutory exemptions, tipped work, commission pay, piecework, and other specialized wage arrangements not stated as supported above.
- Employer-specific WCB assessments when the applicable board source, classification, assessable wages, account inputs, and effective rate are unavailable or unreviewed; block instead of approximating.
- Unsupported province, pay frequency, pay-date year, employee class, or unresolved regulatory / source status. Do not silently fall back to federal-only deductions or another province's rules.
- Direct filing, direct remittance, ROE Web, or bank integration.

## Testing, review, and release gates

1. Resolve and document every OPEN source question above. For PE, complete the official amendment check beyond the original Act and 2026 commencement materials. Maintain current official NL Act/Regulations versions and confirm any later amendments before release. Validate all province rules against current statutes/regulations where guidance does not settle the rule.
2. Payroll/tax reviewer must approve federal withholding, CPP/CPP2/EI, the provincial payroll-tax/levy treatment, and each effective-dated CRA formula edition. A qualified provincial employment-standards reviewer must approve the nine province matrices and any edge cases. Reviewer approval is **pending**, not implied by this document.
3. For each supported province, create reference tests for part-time/full-time hourly and salaried pay across daily, weekly, bi-weekly, semi-monthly, and monthly frequencies; cover effective-date boundaries, overtime, vacation-pay accrual/payout, holidays worked/not worked, and termination/final-pay cases using current government examples and primary legislation. Add tax tests against the applicable CRA T4127 edition and independently reviewed expected results.
4. Test employee-level province-of-employment resolution in multi-province employers, prospective jurisdiction changes, historical immutability, Canadian-only draft calculations, blocking and Canadian YTD/paystub exclusion of legacy U.S.-calculated drafts, preservation of pre-effective U.S. history, current-year source-version selection, WCB/levy blocks when account inputs or reviewed rates are absent, cheque/pay-statement artifacts, XML schema rejection of invalid output, and all other blocked-case paths. No province is release-ready while an applicable levy, WCB rule, legal interpretation, or source-version question remains unresolved.
5. Keep source/rate updates reviewed and effective-dated, test them before activation, and retain the review record. Do not silently fetch and apply government changes.

## Sources

[1] https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jan/t4127-jan-payroll-deductions-formulas-computer-programs.html — Payroll Deductions Formulas - 122nd Edition Effective January 1, 2026 - Canada.ca
[2] https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jul/t4127-jul-payroll-deductions-formulas.html — Payroll Deductions Formulas - 123rd Edition Effective July 1, 2026
[3] https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/t4001/employers-guide-payroll-deductions-remittances.html — Employers’ Guide – Payroll Deductions and Remittances
[4] https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/payroll-deductions-contributions/canada-pension-plan-cpp/cpp-contribution-rates-maximums-exemptions.html — CPP contribution rates, maximums and exemptions – Calculate payroll deductions and contributions
[5] https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/calculating-deductions/making-deductions/second-additional-cpp-contribution-rates-maximums.html — Second additional CPP (CPP2) contribution rates and maximums – Calculate payroll deductions and contributions
[6] https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/payroll-deductions-contributions/employment-insurance-ei/ei-premium-rates-maximums.html — EI premium rates and maximums – Calculate payroll deductions and contributions - Canada.ca
[7] https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/rc4120.html — RC4120 Employers' Guide - Filing the T4 slip and Summary - Canada.ca
[8] https://www.canada.ca/en/revenue-agency/services/e-services/filing-information-returns-electronically-t4-t5-other-types-returns-overview/xml-specs.html — XML specifications for all information return types - Canada.ca
[9] https://www.canada.ca/en/revenue-agency/services/e-services/filing-information-returns-electronically-t4-t5-other-types-returns-overview/t619-2026/t4-2026.html — T4, Statement of Remuneration Paid - Canada.ca
[10] https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/remitting-source-deductions/how-when-remit-overview/statement-account-current-source-deductions-regular-quarterly-remitters.html — PD7A - Statement of account for current source deductions – Regular and quarterly remitters - Canada.ca
[11] https://www.canada.ca/en/employment-social-development/programs/ei/ei-list/reports/roe-guide.html — Employers: How to complete the record of employment (ROE) form - Canada.ca
[12] https://www.canada.ca/en/employment-social-development/programs/ei/ei-list/ei-roe.html — EI Record of Employment - Canada.ca
[13] https://www.alberta.ca/overtime-hours-overtime-pay — Employment standards rules – Overtime hours and overtime pay | Alberta.ca
[14] https://www.alberta.ca/vacation-pay — Employment standards rules – Vacations and vacation pay | Alberta.ca
[15] https://www.alberta.ca/alberta-general-holidays — Employment standards – Alberta general holidays | Alberta.ca
[16] https://www.alberta.ca/employment-standards-termination-and-lay-off — Employment standards – Termination and lay-off | Alberta.ca
[17] https://www2.gov.bc.ca/gov/content/employment-business/employment-standards-advice/employment-standards/hours/overtime-pay — Overtime pay - Province of British Columbia
[18] https://www2.gov.bc.ca/gov/content/employment-business/employment-standards-advice/employment-standards/time-off/vacation — Annual vacation - Province of British Columbia
[19] https://www2.gov.bc.ca/gov/content/employment-business/employment-standards-advice/employment-standards/statutory-holidays — Statutory holidays - Province of British Columbia
[20] https://www2.gov.bc.ca/gov/content/employment-business/employment-standards-advice/employment-standards/termination/quit-fired — Quitting or getting fired - Province of British Columbia
[21] https://www.gov.bc.ca/gov/content/taxes/employer-health-tax/employer-health-tax-overview — Employer health tax overview
[22] https://www.gov.mb.ca/labour/standards/doc,overtime,factsheet.html — Employment Standards | Employment Standards | Overtime
[23] https://www.gov.mb.ca/labour/standards/doc,vacations,factsheet.html — Employment Standards | Employment Standards | Vacations and Vacation Pay
[24] https://www.gov.mb.ca/labour/standards/doc,gen-holidays-after-april-30-07,factsheet.html — Employment Standards | Employment Standards | General Holidays
[25] https://www.gov.mb.ca/labour/standards/doc,terminate-employment-after-apr-30-07,factsheet.html — Employment Standards | Employment Standards | Termination of Employment
[26] https://www.gov.mb.ca/finance/taxation/taxes/payroll.html — Province of Manitoba | finance - Health and Post-Secondary Education Tax Levy
[27] https://www.ontario.ca/document/your-guide-employment-standards-act-0/overtime-pay — Overtime pay | Your guide to the Employment Standards Act | ontario.ca
[28] https://www.ontario.ca/document/your-guide-employment-standards-act-0/vacation — Vacation | Your guide to the Employment Standards Act | ontario.ca
[29] https://www.ontario.ca/document/your-guide-employment-standards-act-0/public-holidays — Public holidays | Your guide to the Employment Standards Act | ontario.ca
[30] https://www.ontario.ca/document/your-guide-employment-standards-act-0/termination-employment — Termination of employment | Your guide to the Employment Standards Act | ontario.ca
[31] https://www.ontario.ca/document/employer-health-tax-eht — Employer Health Tax (EHT) | ontario.ca
[32] https://www.saskatchewan.ca/business/employment-standards/overtime/general-overtime-information — Overtime | Overtime | Government of Saskatchewan
[33] https://www.saskatchewan.ca/business/employment-standards/vacations-and-vacation-pay/annual-vacation-and-vacation-pay — Annual Vacation and Vacation Pay | Vacations and Vacation Pay | Government of Saskatchewan
[34] https://www.saskatchewan.ca/business/employment-standards/public-statutory-holidays/paying-employees-for-public-holidays — Paying Employees for Public Holidays | Public (Statutory) Holidays | Government of Saskatchewan
[35] https://www.saskatchewan.ca/business/employment-standards/layoffs-and-termination/individual-layoff-or-termination — Individual Layoff or Termination | Layoffs and Termination | Government of Saskatchewan
[36] https://www.saskatchewan.ca/government/news-and-media/2025/september/03/supporting-businesses-and-workers-through-amendments-to-employment-standards — Supporting Businesses and Workers Through Amendments to Employment Standards | News and Media | Government of Saskatchewan
[37] https://www.gnb.ca/en/topic/jobs-workplaces/labour-market-workforce/employment-standards/wage-pay.html — Minimum wage, overtime and minimum pay for reporting for work - gnb.ca
[38] https://www.gnb.ca/en/topic/jobs-workplaces/labour-market-workforce/employment-standards/holiday-vacation.html — Paid public holidays, vacation time and pay  - gnb.ca
[39] https://www.gnb.ca/en/topic/jobs-workplaces/labour-market-workforce/employment-standards/rights-terminated.html — Employee rights including if terminated, laid off, or dismissed and unfair employment actions - gnb.ca
[40] https://assembly.nl.ca/legislation/sr/statutes/l02.htm — RSNL1990 CHAPTER L-2 - LABOUR STANDARDS ACT
[41] https://assembly.nl.ca/Legislation/sr/regulations/rc960781.htm — Labour Standards Regulations under the Labour Standards Act
[42] https://www.assembly.nl.ca/legislation/sr/statutes/r15-01.htm — SNL2009 CHAPTER R-15.01 - REVENUE ADMINISTRATION ACT
[43] https://novascotia.ca/lae/employmentrights/overtime.asp — Overtime : NS Labour and Advanced Education, Employment Rights
[44] https://novascotia.ca/lae/employmentrights/vacationleavepay.asp — Vacation Time and Vacation Pay
[45] https://novascotia.ca/lae/employmentrights/holidaypay.asp — Holiday Pay | novascotia.ca
[46] https://novascotia.ca/lae/employmentrights/remembrance.asp — Remembrance Day | novascotia.ca
[47] https://novascotia.ca/lae/employmentrights/employernowork.asp — When the Employer Ends the Employment : NS Labour and Advanced Education, Employment Rights
[48] https://www.princeedwardisland.ca/sites/default/files/b281/E-6.3-Employment%20Standards%20Act.pdf — Employment Standards Act
[49] https://www.canada.ca/en/revenue-agency/services/forms-publications/forms/t4.html — T4 Statement of Remuneration Paid (slip) - Canada.ca
[50] https://www.canada.ca/en/revenue-agency/services/forms-publications/forms/t4sum.html — T4SUM Summary of Remuneration Paid - Canada.ca
[51] https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/completing-filing-information-returns/t4-information-employers/t4-summary.html — T4 Summary – Information for employers - Canada.ca
[52] https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-businesses/payroll-deductions-online-calculator.html — Payroll Deductions Online Calculator - Canada.ca
[53] https://www.canada.ca/en/revenue-agency/services/forms-publications/request-payment-forms-remittance-vouchers.html — Remittance vouchers and payment forms - Payments to the CRA - Canada.ca
[54] https://laws.gnb.ca/en/document/cs/E-7.2 — E-7.2 - Employment Standards Act - New Brunswick Acts and Regulations
[55] https://www.gov.nl.ca/fin/tax-programs-incentives/business/education — Health and Post Secondary Education Tax (Payroll Tax) - Finance
[56] https://www.ontario.ca/laws/statute/00e41 — Employment Standards Act, 2000, S.O. 2000, c. 41 - Ontario e-Laws
[57] https://docs.assembly.pe.ca/download/dms?fileName=chapter-66%20(Employment%20Standards%20Act&objectId=b52b3eac-ca06-409c-ae5b-41a6716cbb4b — Employment Standards Act, 2024, c.66 - Legislative Assembly of PEI (King’s Printer)
[58] https://www.princeedwardisland.ca/sites/default/files/b135/RG%20Issue%2024-June%2013%202026%20online%202%20parts.pdf — Royal Gazette, June 13, 2026 - Government of Prince Edward Island
[59] https://laws.gnb.ca/en/document/as/2026,%20c.3 — 2026, c.3 - An Act to Amend the Employment Standards Act

<!-- matrix citation link targets generated from the source ledger -->
[1]: <https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jan/t4127-jan-payroll-deductions-formulas-computer-programs.html>
[2]: <https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jul/t4127-jul-payroll-deductions-formulas.html>
[3]: <https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/t4001/employers-guide-payroll-deductions-remittances.html>
[4]: <https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/payroll-deductions-contributions/canada-pension-plan-cpp/cpp-contribution-rates-maximums-exemptions.html>
[5]: <https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/calculating-deductions/making-deductions/second-additional-cpp-contribution-rates-maximums.html>
[6]: <https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/payroll-deductions-contributions/employment-insurance-ei/ei-premium-rates-maximums.html>
[7]: <https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/rc4120.html>
[8]: <https://www.canada.ca/en/revenue-agency/services/e-services/filing-information-returns-electronically-t4-t5-other-types-returns-overview/xml-specs.html>
[9]: <https://www.canada.ca/en/revenue-agency/services/e-services/filing-information-returns-electronically-t4-t5-other-types-returns-overview/t619-2026/t4-2026.html>
[10]: <https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/remitting-source-deductions/how-when-remit-overview/statement-account-current-source-deductions-regular-quarterly-remitters.html>
[11]: <https://www.canada.ca/en/employment-social-development/programs/ei/ei-list/reports/roe-guide.html>
[12]: <https://www.canada.ca/en/employment-social-development/programs/ei/ei-list/ei-roe.html>
[13]: <https://www.alberta.ca/overtime-hours-overtime-pay>
[14]: <https://www.alberta.ca/vacation-pay>
[15]: <https://www.alberta.ca/alberta-general-holidays>
[16]: <https://www.alberta.ca/employment-standards-termination-and-lay-off>
[17]: <https://www2.gov.bc.ca/gov/content/employment-business/employment-standards-advice/employment-standards/hours/overtime-pay>
[18]: <https://www2.gov.bc.ca/gov/content/employment-business/employment-standards-advice/employment-standards/time-off/vacation>
[19]: <https://www2.gov.bc.ca/gov/content/employment-business/employment-standards-advice/employment-standards/statutory-holidays>
[20]: <https://www2.gov.bc.ca/gov/content/employment-business/employment-standards-advice/employment-standards/termination/quit-fired>
[21]: <https://www.gov.bc.ca/gov/content/taxes/employer-health-tax/employer-health-tax-overview>
[22]: <https://www.gov.mb.ca/labour/standards/doc,overtime,factsheet.html>
[23]: <https://www.gov.mb.ca/labour/standards/doc,vacations,factsheet.html>
[24]: <https://www.gov.mb.ca/labour/standards/doc,gen-holidays-after-april-30-07,factsheet.html>
[25]: <https://www.gov.mb.ca/labour/standards/doc,terminate-employment-after-apr-30-07,factsheet.html>
[26]: <https://www.gov.mb.ca/finance/taxation/taxes/payroll.html>
[27]: <https://www.ontario.ca/document/your-guide-employment-standards-act-0/overtime-pay>
[28]: <https://www.ontario.ca/document/your-guide-employment-standards-act-0/vacation>
[29]: <https://www.ontario.ca/document/your-guide-employment-standards-act-0/public-holidays>
[30]: <https://www.ontario.ca/document/your-guide-employment-standards-act-0/termination-employment>
[31]: <https://www.ontario.ca/document/employer-health-tax-eht>
[32]: <https://www.saskatchewan.ca/business/employment-standards/overtime/general-overtime-information>
[33]: <https://www.saskatchewan.ca/business/employment-standards/vacations-and-vacation-pay/annual-vacation-and-vacation-pay>
[34]: <https://www.saskatchewan.ca/business/employment-standards/public-statutory-holidays/paying-employees-for-public-holidays>
[35]: <https://www.saskatchewan.ca/business/employment-standards/layoffs-and-termination/individual-layoff-or-termination>
[36]: <https://www.saskatchewan.ca/government/news-and-media/2025/september/03/supporting-businesses-and-workers-through-amendments-to-employment-standards>
[37]: <https://www.gnb.ca/en/topic/jobs-workplaces/labour-market-workforce/employment-standards/wage-pay.html>
[38]: <https://www.gnb.ca/en/topic/jobs-workplaces/labour-market-workforce/employment-standards/holiday-vacation.html>
[39]: <https://www.gnb.ca/en/topic/jobs-workplaces/labour-market-workforce/employment-standards/rights-terminated.html>
[40]: <https://assembly.nl.ca/legislation/sr/statutes/l02.htm>
[41]: <https://assembly.nl.ca/Legislation/sr/regulations/rc960781.htm>
[42]: <https://www.assembly.nl.ca/legislation/sr/statutes/r15-01.htm>
[43]: <https://novascotia.ca/lae/employmentrights/overtime.asp>
[44]: <https://novascotia.ca/lae/employmentrights/vacationleavepay.asp>
[45]: <https://novascotia.ca/lae/employmentrights/holidaypay.asp>
[46]: <https://novascotia.ca/lae/employmentrights/remembrance.asp>
[47]: <https://novascotia.ca/lae/employmentrights/employernowork.asp>
[48]: <https://www.princeedwardisland.ca/sites/default/files/b281/E-6.3-Employment%20Standards%20Act.pdf>
[49]: <https://www.canada.ca/en/revenue-agency/services/forms-publications/forms/t4.html>
[50]: <https://www.canada.ca/en/revenue-agency/services/forms-publications/forms/t4sum.html>
[51]: <https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/completing-filing-information-returns/t4-information-employers/t4-summary.html>
[52]: <https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-businesses/payroll-deductions-online-calculator.html>
[53]: <https://www.canada.ca/en/revenue-agency/services/forms-publications/request-payment-forms-remittance-vouchers.html>
[54]: <https://laws.gnb.ca/en/document/cs/E-7.2>
[55]: <https://www.gov.nl.ca/fin/tax-programs-incentives/business/education>
[56]: <https://www.ontario.ca/laws/statute/00e41>
[57]: <https://docs.assembly.pe.ca/download/dms?fileName=chapter-66%20(Employment%20Standards%20Act&objectId=b52b3eac-ca06-409c-ae5b-41a6716cbb4b>
[58]: <https://www.princeedwardisland.ca/sites/default/files/b135/RG%20Issue%2024-June%2013%202026%20online%202%20parts.pdf>
[59]: <https://laws.gnb.ca/en/document/as/2026,%20c.3>
