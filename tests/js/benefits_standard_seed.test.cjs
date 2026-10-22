const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const manualCode = {
    id: 7,
    code: 'MANUAL',
    name: 'Manual code',
    kind: 'deduction',
    category: 'pretax',
    calc_method: 'fixed_amount',
    employer_calc_method: null,
    reduces_federal: true,
    reduces_state: true,
    reduces_fica: false,
    sequence: 100,
    is_active: true,
    burden_routing: 'fringe_pool',
    tracks_balance: false,
    current_rate: null,
};

function fixture(jurisdiction, lookupError = null) {
    const context = {
        API: {
            get: async url => {
                if (url.startsWith('/benefits/codes')) return [manualCode];
                if (lookupError) throw lookupError;
                return jurisdiction;
            },
        },
        escapeHtml: value => String(value ?? '').replace(/[&<>"']/g, character => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        })[character]),
        formatCurrency: value => `$${value}`,
    };
    vm.createContext(context);
    const source = fs.readFileSync(
        path.join(__dirname, '../../app/static/js/benefits.js'), 'utf8'
    );
    vm.runInContext(`${source}\nthis.page = BenefitsPage;`, context);
    return context.page;
}

const hasSeedButton = html => /onclick="BenefitsPage\.seedStandard\(\)">Seed standard codes/.test(html);

test('active Canadian jurisdiction hides US presets and gives an accessible notice', async () => {
    const page = fixture({ country_code: 'CA', province_code: 'ON', history: [] });
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="status"/);
    assert.match(html, /not Canadian-reviewed/);
    assert.match(html, /not available for Canadian companies/);
    assert.match(html, />\+ Add Code</);
    assert.match(html, /MANUAL/);
});

test('no active jurisdiction preserves the US seed action and existing code list', async () => {
    const page = fixture({ country_code: null, province_code: null, history: [] });
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), true);
    assert.match(html, /MANUAL/);
    assert.doesNotMatch(html, /Canadian-reviewed/);
});

test('future-only Canadian jurisdiction preserves the US seed action', async () => {
    const page = fixture({
        country_code: null,
        province_code: null,
        history: [{ country_code: 'CA', effective_from: '2999-01-01' }],
    });

    assert.equal(hasSeedButton(await page._codesTab()), true);
});

test('jurisdiction lookup failure hides seeding and explains the limitation', async () => {
    const page = fixture(null, new Error('lookup unavailable'));
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="alert"/);
    assert.match(html, /could not be verified/);
    assert.match(html, /Standard benefit presets are unavailable/);
    assert.match(html, /MANUAL/);
});

test('null country with a non-null province fails closed without hiding manual codes', async () => {
    const page = fixture({ country_code: null, province_code: 'ON', history: [] });
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="alert"/);
    assert.match(html, /payroll jurisdiction response is unsupported/);
    assert.match(html, /MANUAL/);
});

test('missing province in a null-country response fails closed', async () => {
    const page = fixture({ country_code: null, history: [] });
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="alert"/);
    assert.match(html, /payroll jurisdiction response is unsupported/);
});

test('unknown jurisdiction response fails closed without hiding manual codes', async () => {
    const page = fixture({ country_code: 'ZZ', province_code: 'XX', history: [] });
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="alert"/);
    assert.match(html, /unsupported payroll jurisdiction/);
    assert.match(html, /MANUAL/);
});
