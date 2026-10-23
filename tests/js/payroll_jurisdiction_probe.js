const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('app/static/js/settings.js', 'utf8');
const scope = { value: 'federally_regulated' };
const province = { value: 'BC' };
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
  'payroll-jurisdiction-scope': scope,
  'payroll-jurisdiction-province': province,
  'payroll-jurisdiction-effective-from': effectiveFrom,
  'payroll-jurisdiction-save': saveButton,
  'payroll-jurisdiction-history': history,
  'payroll-jurisdiction-save-status': status,
};
const posts = [];
const state = {
  country_code: 'CA',
  province_code: 'AB',
  effective_from: '2026-10-22',
  effective_to: null,
  minimum_effective_from: '2031-02-03',
  history: [],
};

const context = {
  API: {
    get: async () => state,
    post: async (url, payload) => {
      posts.push({ url, payload });
      return { province_code: payload.province_code, effective_from: payload.effective_from };
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

  await settings.savePayrollJurisdiction();
  const federalPosts = posts.length;
  const federalStatus = status.textContent;

  scope.value = '';
  await settings.savePayrollJurisdiction();
  const missingScopePosts = posts.length;
  const missingScopeStatus = status.textContent;

  scope.value = 'provincially_regulated';
  await settings.savePayrollJurisdiction();
  const markup = source.slice(
    source.indexOf('id="payroll-jurisdiction-scope"') - 200,
    source.indexOf('id="payroll-jurisdiction-effective-from"'),
  );
  const effectiveFieldId = source.indexOf('id="payroll-jurisdiction-effective-from"');
  const effectiveInput = source.slice(
    source.lastIndexOf('<input ', effectiveFieldId),
    source.indexOf('>', effectiveFieldId),
  );
  const provincialPosts = posts.length;
  const postedScope = posts[0]?.payload?.regulatory_scope ?? null;
  const normalEffectiveDateEnabled = effectiveFrom.disabled === false;
  const normalSaveEnabled = saveButton.disabled === false;
  effectiveFrom.value = '10000-01-01';
  const overMaximumBrowserValidity = effectiveFrom.validity.rangeOverflow;
  await settings.savePayrollJurisdiction();
  const overMaximumPosts = posts.length;
  const overMaximumStatus = status.textContent;

  state.minimum_effective_from = null;
  await settings.loadPayrollJurisdiction();
  const terminalStatus = status.textContent;
  const terminalEffectiveDateDisabled = effectiveFrom.disabled === true;
  const terminalSaveDisabled = saveButton.disabled === true;
  await settings.savePayrollJurisdiction();

  console.log(JSON.stringify({
    minimum,
    maximum: effectiveFrom.max,
    value: safeDefault,
    federal_posts: federalPosts,
    federal_status: federalStatus,
    missing_scope_posts: missingScopePosts,
    missing_scope_status: missingScopeStatus,
    provincial_posts: provincialPosts,
    posted_scope: postedScope,
    minimum_is_rendered_as_min_and_value:
      effectiveInput.includes('min="${escapeHtml(jurisdiction.minimum_effective_from ||') &&
      effectiveInput.includes('value="${escapeHtml(jurisdiction.minimum_effective_from ||'),
    maximum_is_rendered: effectiveInput.includes('max="9999-12-31"'),
    over_maximum_browser_validity: overMaximumBrowserValidity,
    over_maximum_posts: overMaximumPosts,
    over_maximum_status: overMaximumStatus,
    normal_effective_date_enabled: normalEffectiveDateEnabled,
    normal_save_enabled: normalSaveEnabled,
    terminal_effective_date_disabled: terminalEffectiveDateDisabled,
    terminal_save_disabled: terminalSaveDisabled,
    terminal_posts: posts.length,
    terminal_status: status.textContent || terminalStatus,
    markup_has_schedule_button: source.includes('id="payroll-jurisdiction-save"'),
    markup_has_required_scope: /id="payroll-jurisdiction-scope"[^>]*required/.test(markup),
    markup_names_federal_unsupported: /Federal payroll is not supported/.test(markup),
  }));
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
