# Canadian Payroll A2: Multi-Province Safety Plan

> **For Hermes:** Execute this plan task-by-task with the subagent-driven-development workflow and strict TDD.

**Goal:** Replace the company-wide single-province assumption with a single-country company mode plus effective-dated province-of-employment per employee, while preventing U.S. calculations or outputs from being used for Canadian payroll periods.

**Architecture:** Keep the company-level effective-dated Canadian-country boundary (no concurrent U.S./Canadian payroll in one company). Store province-of-employment as an employee-specific effective-dated timeline and snapshot that province on each employee pay stub; preserve posted history. Until Canadian calculators and outputs are implemented and reviewed, every Canadian calculation path fails closed rather than falling through to U.S. logic. A period that spans countries or an employee's province change is unsupported and must fail closed.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SQLite/PostgreSQL, pytest, vanilla JavaScript.

---

## Confirmed Scope and Safety Boundaries

- Canada launch: provincially regulated employees in AB, BC, MB, NB, NL, NS, ON, PE, SK; exclude Québec, territories, and federally regulated work.
- A company runs payroll in one country at a time. Canadian and U.S. payroll may not run concurrently in one company.
- A company may employ workers in multiple Canadian provinces concurrently. Province is assigned per employee and effective date, not once per company.
- A single employee whose employment province changes within one pay period is blocked until the allocation/design is separately reviewed.
- Preserve valid pre-Canadian U.S. history immutably. Legacy U.S.-calculated drafts for Canadian periods may not be processed or included in Canadian YTD/paystubs.
- This A2 work adds no Canadian tax, overtime, remittance, WCB, or other statutory formulas/rates and does not claim calculation or launch readiness.
- Do not open a PR, merge, deploy, or close #14/#7 as a result of this plan. Keep #14 open until its acceptance criteria are verified.

## Task 1: Country boundary and employee province history

**Objective:** Persist company country mode separately from each employee's province, migrate existing single-province history without rewriting payroll history, and expose safe configuration APIs.

**Files:**
- Modify: `app/models/payroll_jurisdiction.py`, `app/models/__init__.py`
- Create: `app/models/employee_payroll_jurisdiction.py`
- Modify: `app/models/payroll.py` (add per-stub immutable jurisdiction snapshot)
- Modify: `app/services/payroll_jurisdiction_service.py`
- Modify: `app/routes/payroll_jurisdiction.py`
- Modify: `app/routes/main.py` or the actual router-registration module only if a separate router is needed
- Modify: `app/static/js/settings.js` and its settings markup
- Create: a new Alembic revision descending from current head `06ae9f5dc58e`
- Test: `tests/test_payroll_jurisdiction.py` and focused migration/model tests

**Acceptance:**
- Company country-mode records identify Canada and effective dates but do not select a company-wide province. Existing legacy province values are copied to every existing employee's timeline with the exact effective ranges preserved; old pay-run snapshots and posted rows are not rewritten.
- Employee province histories permit different employees to have different supported provinces for the same date; reject unsupported provinces, Québec, territories, and non-provincial regulatory scope.
- Enforce employee/effective-date uniqueness, one open range per employee, valid dates, and no ambiguous gaps within an established timeline. Resolve a pay period only when the employee has continuous coverage by one province for the entire period; reject cross-province periods.
- Add a per-stub jurisdiction snapshot field so a later Canadian calculation can record the employee's province independently of other stubs in the same run. Do not mark legacy U.S.-calculated amounts as Canadian snapshots.
- Keep locking transaction-scoped and acquired before route-specific reads/writes for company and employee jurisdiction timelines. Fail closed on unsupported lock dialects/errors.
- Update the company settings UI so it no longer claims one province applies to the whole company; clearly state that employee province setup/calculation support is still incomplete.
- Tests prove migration backfill, multiple provinces in one company, invalid input rejection, timeline ambiguity/cross-province rejection, snapshot persistence, and single-head migration state.

## Task 2: Payroll mutation and calculator guards

**Objective:** Ensure Canadian or country-transition periods cannot invoke U.S. calculation/posting paths, and protect immutable processed history from later jurisdiction changes.

**Files:**
- Modify: `app/routes/payroll/runs.py`
- Modify: `app/schemas/deductions.py` if gross-up needs an explicit pay date
- Modify: `app/services/payroll_jurisdiction_service.py` only through the agreed Task 1 interface
- Test: `tests/test_canadian_payroll_run_jurisdiction.py`, `tests/test_payroll_jurisdiction_guard_concurrency.py`, `tests/test_payroll_processing_jurisdiction_concurrency.py`, and gross-up tests

**Acceptance:**
- Resolve country against the full run period. A period wholly before Canadian activation preserves legacy U.S. behavior; a Canadian period fails before creating payroll rows or invoking the U.S. withholding engine; a period spanning the country boundary fails closed.
- Processing any legacy U.S.-calculated draft whose pay period is Canadian or crosses the boundary is blocked before journal, liability, or status changes.
- Country activation and employee province changes are prospective and refuse dates that would reinterpret an already-processed pay period for the affected company/employee.
- Gross-up resolves an explicit pay date when Canadian history exists; absent/ambiguous date context fails closed. Canadian gross-up is rejected before YTD or U.S. withholding runs. No-history legacy U.S. behavior remains covered.
- Locks are acquired before the first route-specific database read and held through calculation/commit. Tests exercise both race-winner orders and assert response plus persisted state.

## Task 3: Read-side, YTD, paystub, and overtime guards

**Objective:** Prevent U.S.-calculated Canadian-period data from leaking into Canadian outputs or being classified under U.S. overtime defaults.

**Files:**
- Modify: `app/routes/payroll/ytd.py`, `app/routes/employees.py`, `app/routes/payroll/exports.py`
- Modify: `app/routes/time_entries.py`, `app/schemas/time_entries.py`, and `app/services/overtime.py` only where required for a safe guard
- Test: YTD, employee-YTD, paystub/export, and overtime route tests

**Acceptance:**
- Canadian-period legacy U.S. drafts are excluded from Canadian YTD and cannot produce a Canadian paystub; return a clear fail-closed response until Canadian YTD/paystub outputs exist.
- Valid pre-effective U.S. history remains available as historical U.S. data and is never relabeled as Canadian.
- The date-free U.S. overtime classifier cannot silently apply its default/FLSA rule to a Canadian province or Canadian work period. Canadian and unsupported Canadian jurisdictions fail before `classify_period` is invoked. U.S. behavior with no Canadian jurisdiction history remains covered.
- API/UI responses do not imply that Canadian calculations, stubs, or YTD are supported.
- Every payroll-backed U.S. tax-form output is guarded: `/api/tax-forms/{941,941/pdf,940,940/pdf,w2,w2/{employee_id},w2/{employee_id}/pdf,sui,liability}` and JSON/PDF GET+POST `/api/payroll/forms/{w2/{emp_id},w3/{year},940/{year},941/{year}/{quarter}}[/pdf]`. Do not apply this guard to vendor-bill-backed 1099/1096 routes.
- Annual W-2/W-3/940 periods use inclusive calendar-year bounds; SUI/liability use the inclusive quarter. Form 941 validates both its quarter and every contributor in its January 1–quarter-end YTD window.
- Under the shared company/employee jurisdiction lock, select the exact processed contributor set, outer-join to detect orphan stubs, and validate every contributor's full inclusive pay period plus company and employee jurisdiction snapshots before U.S. calculation. A pay date before Canadian activation does not make a run safe when its full period crosses the boundary.
- Canadian/boundary periods return 422, ambiguous/orphan history returns 409, and lock/jurisdiction-history DB read failures return a static generic 503 without database details. A period wholly before activation remains available as immutable U.S. history; no-history U.S. behavior and existing safe GET/POST statuses remain unchanged.
- PDF calculation, audit hash, and renderer use one validated in-memory contributor set and the same computed data. Stage/flush the audit row, render while retaining the jurisdiction lock, and commit only after rendering; render failures roll back the uncommitted audit row. Rechecks acquire the lock before reading the audit row and do not recalculate unsafe periods. Audit list/get/verify metadata endpoints remain available.
- The Tax Forms UI states U.S. forms cover wholly U.S. periods only, overlapping Canadian periods are blocked, Canadian forms are not implemented, and safe historical U.S. forms remain available without hiding the 1099/1096 contractor workflow.

## Task 4: Integration, evidence, and tracking

**Objective:** Verify the exact integrated candidate, update design/issue evidence, and leave incomplete Canadian calculations visibly blocked.

**Files:**
- Update: `docs/design/canadian-payroll.md` and `docs/design/us-payroll-assumptions-inventory.md`
- Update: fork issues #7 and #14 only with verified progress; keep acceptance checks for incomplete work unchecked

**Verification:**
1. Run focused TDD tests for each task and verify each behavior-change test fails on the exact parent before implementation.
2. Run Ruff, `py_compile`, `git diff --check`, Alembic single-head checks, fresh SQLite migration upgrade, and upgrade-from-current-head migration tests.
3. Run relevant concurrency tests repeatedly on the exact integrated SHA.
4. Run the full suite on the exact final SHA. Record PostgreSQL/Playwright skips separately; run them only with a disposable PostgreSQL URL and installed browser dependencies.
5. Obtain independent exact-SHA specification and security/code-quality reviews before pushing the candidate branch. Re-run affected checks after any review fix.
6. Push only the reviewed candidate to the existing A2 redesign branch and verify the remote SHA. Do not open a PR, merge, deploy, or close issues in this block.

**Baseline:** On `canada/a2-multiprovince-guard-redesign` before A2 code edits, the focused jurisdiction/run-guard suite passed **86 tests**; Alembic reported one head (`06ae9f5dc58e`). The worktree was clean at base `36dbb7f0811acda3bd1c79a5f701629b40cda4e5` after incorporating the approved A1 country-boundary clarification.
