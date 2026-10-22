const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(ROOT, 'app/static/js/employees.js'), 'utf8');

function pageWith(jurisdiction, { lookupError = null } = {}) {
  const calls = [];
  const opened = [];
  const state = {
    jurisdiction,
    lookupError,
    employees: [
      {
        id: 7,
        first_name: 'Riley',
        last_name: 'Morgan',
        pay_type: 'hourly',
        pay_rate: 28,
        is_active: true,
        filing_status: 'single',
      },
    ],
  };
  const context = {
    API: {
      async get(url) {
        calls.push(url);
        if (url === '/settings/payroll-jurisdiction') {
          if (state.lookupError) throw state.lookupError;
          return state.jurisdiction;
        }
        if (url.startsWith('/employees')) return state.employees;
        if (url === '/employees/7') return state.employees[0];
        if (url === '/benefits/groups' || url === '/payroll/states') return [];
        throw new Error(`unexpected GET ${url}`);
      },
    },
    ActiveLists: {
      query: () => '',
      remember: () => {},
      pickerHtml: () => '<select id="list-show"><option>Active</option></select>',
      emptyText: () => '',
      buttonHtml: () => '',
    },
    escapeHtml: (value) => String(value ?? ''),
    formatCurrency: (value) => `$${Number(value || 0).toFixed(2)}`,
    todayISO: () => '2026-10-22',
    openModal: (...args) => opened.push(args),
    closeModal: () => {},
    toast: () => {},
    console,
  };
  vm.createContext(context);
  vm.runInContext(`${source}\nthis.EmployeesPage = EmployeesPage;`, context);
  return { page: context.EmployeesPage, calls, opened, state };
}

const CANADA = {
  country_code: 'CA',
  province_code: 'ON',
  regulatory_scope: 'provincially_regulated',
  effective_from: '2026-10-22',
  effective_to: null,
};
const NO_ACTIVE_JURISDICTION = {
  country_code: null,
  province_code: null,
  regulatory_scope: 'provincially_regulated',
  effective_from: null,
  effective_to: null,
  history: [],
};
const FUTURE_JURISDICTION = {
  ...NO_ACTIVE_JURISDICTION,
  history: [
    {
      country_code: 'CA',
      province_code: 'ON',
      regulatory_scope: 'provincially_regulated',
      effective_from: '2026-10-27',
      effective_to: null,
    },
  ],
};

test('Canadian employee page hides US profile actions and filing data', async () => {
  const { page, calls } = pageWith(CANADA);
  const html = await page.render();

  assert.match(html, /role="alert"/);
  assert.match(html, /Canadian employee setup is unavailable/);
  assert.match(html, /Do not enter US W-4, state, or Social Security data/);
  assert.doesNotMatch(html, /\+ Add Employee/);
  assert.doesNotMatch(html, />Filing</);
  assert.doesNotMatch(html, />Edit</);
  assert.match(html, />Details</);
  assert.ok(calls.includes('/settings/payroll-jurisdiction'));
});

test('admin jurisdiction lookup errors render a failure state, never US controls', async () => {
  const { page } = pageWith(null, { lookupError: new Error('offline') });
  const html = await page.render();

  assert.match(html, /role="alert"/);
  assert.match(html, /Payroll jurisdiction status could not be verified/);
  assert.doesNotMatch(html, /\+ Add Employee/);
  assert.doesNotMatch(html, />Filing</);
  assert.doesNotMatch(html, />Edit</);
});

test('direct calls cannot open an employee form for a Canadian company', async () => {
  const { page, opened } = pageWith(CANADA);

  await page.showForm(7);

  assert.equal(opened.length, 0);
});

test('no active jurisdiction preserves the existing US employee interface', async () => {
  const { page } = pageWith(NO_ACTIVE_JURISDICTION);
  const html = await page.render();

  assert.match(html, /\+ Add Employee/);
  assert.match(html, />Filing</);
  assert.match(html, />Edit</);
});

test('future-only jurisdiction preserves the existing US employee interface', async () => {
  const { page } = pageWith(FUTURE_JURISDICTION);
  const html = await page.render();

  assert.match(html, /\+ Add Employee/);
  assert.match(html, />Filing</);
  assert.match(html, />Edit</);
});
