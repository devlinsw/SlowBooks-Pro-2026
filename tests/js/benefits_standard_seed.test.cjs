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

const today = () => new Date().toISOString().slice(0, 10);
const addDays = (isoDate, days) => {
    const date = new Date(`${isoDate}T00:00:00.000Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
};
const jurisdictionScope = 'provincially_regulated';

function noActiveJurisdiction(overrides = {}) {
    return {
        country_code: null,
        province_code: null,
        effective_from: null,
        effective_to: null,
        regulatory_scope: jurisdictionScope,
        server_today: today(),
        minimum_effective_from: today(),
        history: [],
        ...overrides,
    };
}

function futureJurisdiction(overrides = {}) {
    return {
        country_code: 'CA',
        province_code: 'ON',
        regulatory_scope: jurisdictionScope,
        effective_from: '2999-01-01',
        effective_to: null,
        ...overrides,
    };
}

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
    const effectiveFrom = today();
    const page = fixture(noActiveJurisdiction({
        country_code: 'CA',
        province_code: 'ON',
        effective_from: effectiveFrom,
        minimum_effective_from: addDays(effectiveFrom, 1),
        history: [futureJurisdiction({ effective_from: effectiveFrom })],
    }));
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="status"/);
    assert.match(html, /not Canadian-reviewed/);
    assert.match(html, /not available for Canadian companies/);
    assert.match(html, />\+ Add Code</);
    assert.match(html, /MANUAL/);
});

test('no active jurisdiction preserves the US seed action and existing code list', async () => {
    const page = fixture(noActiveJurisdiction());
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), true);
    assert.match(html, /MANUAL/);
    assert.doesNotMatch(html, /Canadian-reviewed/);
});

test('no-history minimum is checked against server date, not browser date', async () => {
    const serverToday = addDays(today(), -1);
    const page = fixture(noActiveJurisdiction({
        server_today: serverToday,
        minimum_effective_from: serverToday,
    }));

    assert.equal(hasSeedButton(await page._codesTab()), true);
});

test('future-only Canadian jurisdiction preserves the US seed action', async () => {
    const page = fixture(noActiveJurisdiction({
        minimum_effective_from: '2999-01-02',
        history: [futureJurisdiction()],
    }));

    assert.equal(hasSeedButton(await page._codesTab()), true);
});

test('date-max history preserves null minimum and the US seed action', async () => {
    const page = fixture(noActiveJurisdiction({
        server_today: '9999-12-30',
        minimum_effective_from: null,
        history: [futureJurisdiction({ effective_from: '9999-12-31' })],
    }));

    assert.equal(hasSeedButton(await page._codesTab()), true);
});

test('inconsistent minimum date with empty history fails closed', async () => {
    const html = await fixture(noActiveJurisdiction({
        server_today: '2026-06-15',
        minimum_effective_from: '1900-01-01',
    }))._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="alert"/);
    assert.match(html, /payroll jurisdiction response is unsupported/);
});

test('inconsistent minimum date with future-only history fails closed', async () => {
    const html = await fixture(noActiveJurisdiction({
        server_today: '2026-06-15',
        minimum_effective_from: '1900-01-01',
        history: [futureJurisdiction()],
    }))._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="alert"/);
    assert.match(html, /payroll jurisdiction response is unsupported/);
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
    const page = fixture(noActiveJurisdiction({ province_code: 'ON' }));
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="alert"/);
    assert.match(html, /payroll jurisdiction response is unsupported/);
    assert.match(html, /MANUAL/);
});

test('missing province in a null-country response fails closed', async () => {
    const response = noActiveJurisdiction();
    delete response.province_code;
    const page = fixture(response);
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="alert"/);
    assert.match(html, /payroll jurisdiction response is unsupported/);
});

test('unknown jurisdiction response fails closed without hiding manual codes', async () => {
    const page = fixture(noActiveJurisdiction({
        country_code: 'ZZ',
        province_code: 'ON',
        effective_from: today(),
    }));
    const html = await page._codesTab();

    assert.equal(hasSeedButton(html), false);
    assert.match(html, /role="alert"/);
    assert.match(html, /unsupported payroll jurisdiction/);
    assert.match(html, /MANUAL/);
});

test('missing required payroll-jurisdiction fields fail closed', async t => {
    for (const field of [
        'country_code',
        'province_code',
        'effective_from',
        'effective_to',
        'regulatory_scope',
        'server_today',
        'minimum_effective_from',
        'history',
    ]) {
        await t.test(`missing ${field}`, async () => {
            const response = noActiveJurisdiction();
            delete response[field];
            const html = await fixture(response)._codesTab();

            assert.equal(hasSeedButton(html), false);
            assert.match(html, /role="alert"/);
            assert.match(html, /payroll jurisdiction response is unsupported/);
            assert.match(html, /MANUAL/);
        });
    }
});

test('null-country response with any non-null active effective date fails closed', async t => {
    for (const [field, value] of [
        ['effective_from', today()],
        ['effective_to', today()],
    ]) {
        await t.test(`${field} is non-null`, async () => {
            const html = await fixture(noActiveJurisdiction({ [field]: value }))._codesTab();

            assert.equal(hasSeedButton(html), false);
            assert.match(html, /role="alert"/);
            assert.match(html, /payroll jurisdiction response is unsupported/);
            assert.match(html, /MANUAL/);
        });
    }
});

test('unsupported scope and malformed top-level dates fail closed', async t => {
    const cases = [
        ['unsupported scope', noActiveJurisdiction({ regulatory_scope: 'federally_regulated' })],
        ['invalid minimum date', noActiveJurisdiction({ minimum_effective_from: '2026-02-30' })],
        ['malformed active date', noActiveJurisdiction({
            country_code: 'CA',
            province_code: 'ON',
            effective_from: '2026-02-30',
            history: [futureJurisdiction()],
        })],
        ['active record missing from history', noActiveJurisdiction({
            country_code: 'CA',
            province_code: 'ON',
            effective_from: today(),
        })],
        ['inverted active date range', noActiveJurisdiction({
            country_code: 'CA',
            province_code: 'ON',
            effective_from: '2026-02-02',
            effective_to: '2026-02-01',
            history: [futureJurisdiction({ effective_from: '2026-02-02', effective_to: '2026-02-01' })],
        })],
    ];

    for (const [name, response] of cases) {
        await t.test(name, async () => {
            const html = await fixture(response)._codesTab();

            assert.equal(hasSeedButton(html), false);
            assert.match(html, /role="alert"/);
            assert.match(html, /payroll jurisdiction response is unsupported/);
            assert.match(html, /MANUAL/);
        });
    }
});

test('malformed history containers and entries fail closed', async t => {
    const cases = [
        ['non-array history', noActiveJurisdiction({ history: {} })],
        ['entry missing a required field', noActiveJurisdiction({ history: [{ country_code: 'CA' }] })],
        ['unsupported history province', noActiveJurisdiction({
            history: [futureJurisdiction({ province_code: 'YT' })],
        })],
        ['invalid history date', noActiveJurisdiction({
            history: [futureJurisdiction({ effective_from: '2999-02-30' })],
        })],
        ['inverted history date range', noActiveJurisdiction({
            history: [futureJurisdiction({ effective_to: '2998-12-31' })],
        })],
        ['non-contiguous history ranges', noActiveJurisdiction({
            history: [
                futureJurisdiction({ effective_to: '2999-01-02' }),
                futureJurisdiction({ effective_from: '2999-01-04' }),
            ],
        })],
        ['unsorted history ranges', noActiveJurisdiction({
            history: [
                futureJurisdiction({ effective_from: '2999-01-03' }),
                futureJurisdiction({ effective_from: '2999-01-01' }),
            ],
        })],
        ['history with no open-ended final range', noActiveJurisdiction({
            history: [futureJurisdiction({ effective_to: '2999-01-02' })],
        })],
        ['no-active response with a currently effective history record', noActiveJurisdiction({
            minimum_effective_from: addDays(today(), 1),
            history: [futureJurisdiction({ effective_from: today() })],
        })],
    ];

    for (const [name, response] of cases) {
        await t.test(name, async () => {
            const html = await fixture(response)._codesTab();

            assert.equal(hasSeedButton(html), false);
            assert.match(html, /role="alert"/);
            assert.match(html, /payroll jurisdiction response is unsupported/);
            assert.match(html, /MANUAL/);
        });
    }
});
