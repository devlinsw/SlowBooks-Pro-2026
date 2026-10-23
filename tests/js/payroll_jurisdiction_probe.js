const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('app/static/js/settings.js', 'utf8');
const effectiveFrom = {
  value: '2030-01-01',
  min: '',
  max: '',
  disabled: false,
  get validity() {
    const [year, month, day] = this.value.split('-').map(Number);
    const [maxYear, maxMonth, maxDay] = this.max.split('-').map(Number);
    return {
      rangeOverflow: Boolean(
        this.max &&
        (year > maxYear ||
          (year === maxYear && month > maxMonth) ||
          (year === maxYear && month === maxMonth && day > maxDay)),
      ),
    };
  },
};
const saveButton = { disabled: false };
const history = { innerHTML: '' };
const status = { textContent: '' };
const elements = {
  'payroll-jurisdiction-effective-from': effectiveFrom,
  'payroll-jurisdiction-save': saveButton,
  'payroll-jurisdiction-history': history,
  'payroll-jurisdiction-save-status': status,
};
const posts = [];
const state = {
  country_code: null,
  effective_from: null,
  effective_to: null,
  minimum_effective_from: '2031-02-03',
  history: [],
};

const context = {
  API: {
    get: async () => state,
    post: async (url, payload) => {
      posts.push({ url, payload });
      return { country_code: payload.country_code, effective_from: payload.effective_from };
    },
  },
  document: { getElementById: (id) => elements[id] || null },
  escapeHtml: (value) => String(value ?? ''),
  console,
};
vm.createContext(context);
vm.runInContext(`${source}\nthis.SettingsPage = SettingsPage;`, context);

(async () => {
  const settings = context.SettingsPage;
  await settings.loadPayrollJurisdiction();
  const minimum = effectiveFrom.min;
  const safeDefault = effectiveFrom.value;
  const effectiveFieldId = source.indexOf('id="payroll-jurisdiction-effective-from"');
  const effectiveInput = source.slice(
    source.lastIndexOf('<input ', effectiveFieldId),
    source.indexOf('>', effectiveFieldId),
  );

  await settings.savePayrollJurisdiction();
  const postedPayload = posts[0]?.payload ?? null;
  const postedCountry = postedPayload?.country_code ?? null;
  const postedEffectiveFrom = postedPayload?.effective_from ?? null;
  effectiveFrom.value = '10000-01-01';
  const overMaximumBrowserValidity = effectiveFrom.validity.rangeOverflow;
  await settings.savePayrollJurisdiction();
  const overMaximumPosts = posts.length;
  const overMaximumStatus = status.textContent;

  state.minimum_effective_from = null;
  await settings.loadPayrollJurisdiction();
  const terminalEffectiveDateDisabled = effectiveFrom.disabled === true;
  const terminalSaveDisabled = saveButton.disabled === true;
  await settings.savePayrollJurisdiction();

  console.log(JSON.stringify({
    minimum,
    maximum: effectiveFrom.max,
    value: safeDefault,
    posted_country: postedCountry,
    posted_effective_from: postedEffectiveFrom,
    posted_payload: postedPayload,
    minimum_is_rendered_as_min_and_value:
      effectiveInput.includes('min="${escapeHtml(jurisdiction.minimum_effective_from ||') &&
      effectiveInput.includes('value="${escapeHtml(jurisdiction.minimum_effective_from ||'),
    maximum_is_rendered: effectiveInput.includes('max="9999-12-31"'),
    over_maximum_browser_validity: overMaximumBrowserValidity,
    over_maximum_posts: overMaximumPosts,
    over_maximum_status: overMaximumStatus,
    terminal_effective_date_disabled: terminalEffectiveDateDisabled,
    terminal_save_disabled: terminalSaveDisabled,
    terminal_posts: posts.length,
    terminal_status: status.textContent,
  }));
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
