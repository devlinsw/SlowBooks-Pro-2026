# Canadian payroll scope and source-to-requirement matrix

**Status: OWNER-APPROVED SCOPE; DESIGN / IMPLEMENTATION IN PROGRESS; NOT RELEASE-READY.**
Scope approval is not legal, tax, or payroll reviewer sign-off; none is recorded here. Source review checked on 2026-10-22. This document supersedes the payroll portion of [canada.md](canada.md); that document remains PARKED for its unrelated sales-tax and conversion material.

## Approved boundary

- Canada payroll is limited to ordinary hourly and salary employees in **provincially regulated workplaces** in AB, BC, MB, NB, NL, NS, ON, PE, and SK. Québec and the territories are deferred. Employment governed by federal labour standards is excluded and must be blocked, not calculated using a provincial rule set.
- One province is selected per company and shared by all employees. A province change is effective-dated and applies prospectively only. Posted payroll history is immutable; a province change must not rewrite or recalculate posted runs.
- Pay dates from 2026 onward; existing weekly, biweekly, semi-monthly, and monthly frequencies only. Federal and provincial income-tax withholding and federal CPP/CPP2/EI calculations use the CRA payroll guidance and edition effective for the pay date. For pay dates January 1–June 30, 2026, use the 122nd T4127 edition effective January 1; for pay dates July 1–December 31, use the 123rd edition effective July 1, referring to the 122nd edition for sections not reproduced in the July edition [1][2]. The CRA calculator identifies the employee's pay date as the date input for the July 1, 2026 changes [52]. Maintain reviewed, versioned rate/formula tables; do not silently download or activate changes. A future year without reviewed source data is not enabled.
- Include each province's ordinary overtime, vacation-pay, statutory/public-holiday, termination, and applicable statutory employer payroll-levy rules, subject to the matrix gaps and release gates below. Workers' compensation / WCB assessments are explicitly deferred.
- Filing is manual. There is no direct CRA or Service Canada submission, ROE Web filing, bank file, or direct-deposit integration in this scope.

## Source-to-requirement matrix

Source IDs link to the government pages in [Sources](#sources), retrieved or checked on 2026-10-22. The shared CRA T4127 references [1][2] apply to federal withholding and to the provincial withholding column in every province row. No statutory rates or calculation formulas are restated here; use the effective source and obtain review before implementation.

| Jurisdiction | Tax / payroll withholding | Overtime | Vacation pay | Public / statutory holidays | Termination | Statutory employer payroll levies |
|---|---|---|---|---|---|---|
| **Federal (payroll layer)** | Federal and provincial withholding: CRA T4127 effective for the pay date [1][2]. | **Out of scope** for federally regulated employment; block rather than apply provincial overtime rules. | **Out of scope** for federally regulated employment; block. | **Out of scope** for federally regulated employment; block. | **Out of scope** for federally regulated employment; block. | Employer CPP and CPP2 contributions and EI premiums: current CRA references [4][5][6]. |
| **AB** | CRA T4127 province-specific withholding [1][2]. | Alberta overtime guidance [13]. | Alberta vacation-pay guidance [14]. | Alberta general-holiday guidance [15]. | Alberta termination / lay-off guidance [16]. | **OPEN:** confirm whether any additional provincial employer payroll levy applies; do not interpret an unlocated source as “none.” |
| **BC** | CRA T4127 province-specific withholding [1][2]. | B.C. overtime guidance [17]. | B.C. annual vacation guidance [18]. | B.C. statutory-holiday guidance [19]. | B.C. quitting / dismissal guidance [20]. | Employer health tax: current B.C. tax guidance [21]; employer applicability and calculations require tax review. |
| **MB** | CRA T4127 province-specific withholding [1][2]. | Manitoba overtime fact sheet [22]. | Manitoba vacation-pay fact sheet [23]. | Manitoba general-holidays fact sheet [24]. | Manitoba termination fact sheet [25]. | Health and Post-Secondary Education Tax Levy: Manitoba Finance employer-payroll guidance [26]; applicability and calculations require tax review. |
| **NB** | CRA T4127 province-specific withholding [1][2]. | New Brunswick wage / overtime guidance [37]. | New Brunswick vacation guidance [38]. | New Brunswick paid-public-holiday guidance [38]. | New Brunswick termination guidance [39]. | **OPEN:** confirm whether any additional provincial employer payroll levy applies; do not interpret an unlocated source as “none.” |
| **NL** | CRA T4127 province-specific withholding [1][2]. | Labour Standards Act and Regulations [40][41]. | Labour Standards Act [40]. | Labour Standards Act [40]. | Labour Standards Act [40]. | Health and Post-Secondary Education Tax provisions (Revenue Administration Act, Part IV, ss. 73–74) [42]; current employer applicability and parameters require tax review. |
| **NS** | CRA T4127 province-specific withholding [1][2]. | Nova Scotia overtime guidance [43]. | Nova Scotia vacation guidance [44]. | Labour Standards Code holiday guidance and separate Remembrance Day guidance [45][46]. | Nova Scotia employer-ending-employment guidance [47]. | **OPEN:** confirm whether any additional provincial employer payroll levy applies; do not interpret an unlocated source as “none.” |
| **ON** | CRA T4127 province-specific withholding [1][2]. | Ontario ESA overtime guide [27]. | Ontario ESA vacation guide [28]. | Ontario public-holiday guide [29]. | Ontario ESA termination guide [30]. | Employer Health Tax: current Ontario tax guidance [31]; employer applicability and calculations require tax review. |
| **PE** | CRA T4127 province-specific withholding [1][2]. | Employment Standards Act reference consolidation [48]. | Employment Standards Act reference consolidation [48]. | Employment Standards Act reference consolidation [48]. | Employment Standards Act reference consolidation [48]. | **OPEN:** confirm whether any additional provincial employer payroll levy applies; do not interpret an unlocated source as “none.” |
| **SK** | CRA T4127 province-specific withholding [1][2]. | Saskatchewan overtime guidance and notice of 2026 amendments [32][36]. | Saskatchewan vacation and vacation-pay guidance [33]. | Saskatchewan public-holiday guidance [34]. | Saskatchewan individual layoff / termination guidance [35]. | **OPEN:** confirm whether any additional provincial employer payroll levy applies; do not interpret an unlocated source as “none.” |

### Coverage notes and unresolved source questions

- **Additional provincial employer payroll levies:** source research did not establish whether a levy applies in AB, NB, NS, PE, or SK. These remain OPEN research and reviewer items, not conclusions that those provinces have no levy. CPP/CPP2 and EI are common federal employer contributions and do not resolve the provincial-levy question.
- **NB vacation transition:** the current government vacation page does not unambiguously settle the exact eight-year service boundary. Keep the transition OPEN until checked against current legislation or regulations [38].
- **NL source currency:** the official Labour Standards Regulations list amendments through 81/24 [41]; verify any later amendments and current government interpretation before enabling 2026+ employment rules. The Revenue Administration Act identifies Health and Post-Secondary Education Tax provisions in Part IV [42], but the Finance guidance URL found during discovery returned a not-found page in browser verification. Keep current employer applicability and tax parameters OPEN until an accessible current official Finance source is confirmed.
- **ON public holidays:** the linked provincial guide reports an update date of July 8, 2024. Confirm against current legislation and any subsequent government guidance before approving holiday logic [29].
- **PE source authority:** the linked provincial Employment Standards Act consolidation says it is current to June 30, 2026, but is for reference and is not the official version. Cross-check the official Act and amendments before encoding any rule [48].
- Government guidance is a source map, not a legal opinion. Where a guidance page flags exceptions or special treatment, do not generalize those cases into this ordinary-employee scope; route them to a reviewer or block them.

## Reporting artifacts and operating boundary

- **T4 slips and T4 Summary:** use the CRA's current T4 and T4SUM form pages as layout references, selecting the form for the applicable reporting year [49][50]. Follow the current CRA filing guide for completion [7]. The CRA describes the T4 Summary as the annual totals reported across T4 slips [51].
- **CRA XML:** export T4 XML and validate format and content against the applicable CRA XML specifications / current T4 schema before it can be saved as ready for manual filing [8][9]. Validation is local; this does not submit or transmit the file to CRA.
- **PD7A:** provide a printable internal remittance and reconciliation summary aligned to CRA payroll-remittance guidance [3]. CRA describes PD7A as a statement for previous remittances plus a voucher for the next remittance, and identifies its displayed sample as the revised statement it began sending in May 2016 [10]. Do not treat that sample image as a current filing template; CRA identifies the PD7A remittance voucher as personalized and says most remittance vouchers cannot be printed at home [53]. The product artifact is not a CRA-issued statement or voucher and is not a payment or filing integration.
- **ROE:** provide a manual worksheet aligned to the current Service Canada guide's block-by-block instructions and Annex 2 blank-paper-ROE example [11]. The paper form is one page in triplicate with a pre-printed serial number; employers must order it through the Employer Contact Centre, so the worksheet is not a substitute for the serialized form [11][12]. Verify against these paper-form sources, not the legacy 2021 ROE Web layout. No ROE Web, electronic submission, or Service Canada filing is included.
- No direct CRA / Service Canada filing or submission and no bank-file / direct-deposit output.

## Unsupported cases — block, do not approximate

- Québec, the territories, and federally regulated employment.
- Union / collective-agreement rules, industry or statutory exemptions, tipped work, commission pay, piecework, and other specialized wage arrangements not stated as supported above.
- Workers' compensation / WCB assessments.
- Unsupported province, pay frequency, pay-date year, employee class, or unresolved regulatory / source status. Do not silently fall back to federal-only deductions or another province's rules.
- Direct filing, direct remittance, ROE Web, or bank integration.

## Testing, review, and release gates

1. Resolve and document every OPEN source question above. For PE, verify the official law text; for NL, verify amendments after the consolidated versions; validate all province rules against current statutes/regulations where guidance does not settle the rule.
2. Payroll/tax reviewer must approve federal withholding, CPP/CPP2/EI, the provincial payroll-tax/levy treatment, and each effective-dated CRA formula edition. A qualified provincial employment-standards reviewer must approve the nine province matrices and any edge cases. Reviewer approval is **pending**, not implied by this document.
3. For each supported province, create reference tests for ordinary hourly and salary pay across weekly, biweekly, semi-monthly, and monthly frequencies; cover effective-date boundaries, overtime, vacation-pay accrual/payout, holidays worked/not worked, and termination/final-pay cases using current government examples and primary legislation. Add tax tests against the applicable CRA T4127 edition and independently reviewed expected results.
4. Test prospective province changes, historical immutability, current-year source-version selection, XML schema rejection of invalid output, printable artifacts, and the blocked-case paths. No province is release-ready while an applicable levy, legal interpretation, or source-version question remains unresolved.
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
