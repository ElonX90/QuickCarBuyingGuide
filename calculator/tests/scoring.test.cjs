'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { calculateIndex, WEIGHTS, INPUT_OPTIONS } = require('../shared/scoring.js');
let passed = 0;
function test(name, run) {
  try { run(); passed += 1; console.log('ok - ' + name); }
  catch (error) { console.error('not ok - ' + name); throw error; }
}
const favorable = Object.freeze({ developmentMonths: 36, globalization: 'international_family', recall: 'history', socialInsurance: 'full', outsourcing: 'absent', skuCount: 3 });
function score(changes) { return calculateIndex(Object.assign({}, favorable, changes)); }
function dim(result, id) { return result.dimensions.find(entry => entry.id === id); }
function close(actual, expected) { assert.ok(Math.abs(actual - expected) < 0.000002, actual + ' != ' + expected); }

test('unknown defaults preserve full bounds and all six missing fields', () => {
  const result = calculateIndex();
  assert.equal(result.lower, 0); assert.equal(result.upper, 100); assert.equal(result.score, null);
  assert.equal(result.knownWeight, 0); assert.equal(result.inputsComplete, false);
  assert.equal(result.unknowns.length, 6); assert.equal(result.largestGap.id, 'development');
  assert.deepEqual(result.objections, []);
});
test('fully specified favorable inputs produce zero without claiming safety', () => {
  const result = score({});
  assert.equal(result.score, 0); assert.equal(result.upper, 0); assert.equal(result.knownWeight, 100);
  assert.equal(result.inputsComplete, true); assert.equal(result.largestGap, null);
  assert.equal(result.evidenceStatus, 'user_input_unverified'); assert.match(result.notice, /不表示事故/);
});
test('fully specified opposite inputs reach 100 and preserve independent objections', () => {
  const result = score({ developmentMonths: 18, globalization: 'china_only', recall: 'no_history', socialInsurance: 'shortfall', outsourcing: 'present', skuCount: 9 });
  assert.equal(result.score, 100);
  assert.deepEqual(result.objections.map(x => x.code), ['social_insurance_shortfall', 'outsourcing_present', 'no_recall_history', 'china_only', 'many_skus']);
});
test('development clamp respects positive short spans, 18-month and 36-month endpoints', () => {
  for (const months of [0.1, 1, 18]) assert.equal(dim(score({ developmentMonths: months }), 'development').lower, 100);
  for (const months of [36, 40, Number.MAX_VALUE]) assert.equal(dim(score({ developmentMonths: months }), 'development').lower, 0);
  close(score({ developmentMonths: 27 }).score, 20);
  close(score({ developmentMonths: 24 }).score, 26.666667);
});
test('development contribution is monotonic for fractional months', () => {
  let previous = 101;
  for (let months = 0.125; months <= 48; months += 0.125) {
    const current = dim(score({ developmentMonths: months }), 'development').lower;
    assert.ok(current >= 0 && current <= 100); assert.ok(current <= previous); previous = current;
  }
});
test('globalization values have distinct scores; a plan stays unknown', () => {
  for (const [value, points] of [['international_family', 0], ['derived_family', 50], ['global_design', 80], ['china_only', 100]]) {
    assert.equal(dim(score({ globalization: value }), 'globalization').lower, points);
  }
  const result = score({ globalization: 'planned' });
  assert.equal(result.lower, 0); assert.equal(result.upper, 20); assert.equal(result.knownWeight, 80);
  assert.match(result.unknowns[0].reason, /计划/);
});
test('not finding a recall is unknown, distinct from an asserted absence', () => {
  const missing = score({ recall: 'unknown' });
  assert.equal(missing.lower, 0); assert.equal(missing.upper, 15); assert.deepEqual(missing.objections, []);
  const none = score({ recall: 'no_history' });
  assert.equal(none.score, 15); assert.equal(none.objections[0].code, 'no_recall_history');
  assert.equal(score({ recall: 'documented_failure' }).score, 15);
});
test('SKU bands include both ends and safe integer counts', () => {
  for (const [count, expected] of [[1, 0], [3, 0], [4, 30], [5, 30], [6, 60], [8, 60], [9, 100], [Number.MAX_SAFE_INTEGER, 100]]) {
    assert.equal(dim(score({ skuCount: count }), 'sku').lower, expected);
  }
});
test('labor max prevents double counting two objections', () => {
  const result = score({ socialInsurance: 'shortfall', outsourcing: 'present' });
  assert.equal(result.score, 15); assert.equal(result.objections.length, 2);
  assert.equal(dim(result, 'labor').contributionUpper, 15);
});
test('known maximum labor fixes its contribution but retains the missing subinput', () => {
  const result = score({ socialInsurance: 'unknown', outsourcing: 'present' });
  assert.equal(result.score, 15); assert.equal(result.isExact, true); assert.equal(result.inputsComplete, false);
  assert.equal(result.knownWeight, 100); assert.equal(result.unknowns[0].field, 'socialInsurance');
  assert.equal(dim(result, 'labor').known, true); assert.deepEqual(dim(result, 'labor').unknownInputs, ['socialInsurance']);
  assert.equal(result.objections[0].code, 'outsourcing_present');
});
test('one favorable labor subinput cannot erase the unknown other half', () => {
  for (const changes of [{ socialInsurance: 'full', outsourcing: 'unknown' }, { socialInsurance: 'unknown', outsourcing: 'absent' }]) {
    const result = score(changes);
    assert.equal(result.lower, 0); assert.equal(result.upper, 15); assert.equal(result.knownWeight, 85);
  }
});
test('interval width equals unresolved weighted contributions; partial data never uses midpoint', () => {
  const result = score({ developmentMonths: 15, globalization: 'unknown', socialInsurance: 'unknown', outsourcing: 'unknown', skuCount: null });
  assert.equal(result.lower, 40); assert.equal(result.upper, 85); assert.equal(result.knownWeight, 55);
  assert.equal(result.score, null); assert.equal(result.largestGap.id, 'globalization');
  close(result.upper - result.lower, result.dimensions.reduce((sum, entry) => sum + entry.contributionUpper - entry.contributionLower, 0));
});
test('invalid or coercible numeric inputs cannot silently score', () => {
  for (const value of [NaN, Infinity, -Infinity, '18', '', ' ', 'x', true, [], {}]) assert.throws(() => score({ developmentMonths: value }), TypeError);
  for (const value of [0, -0, -0.1]) assert.throws(() => score({ developmentMonths: value }), RangeError);
  for (const value of [0, -1, 2.5, Number.MAX_SAFE_INTEGER + 1]) assert.throws(() => score({ skuCount: value }), RangeError);
  for (const value of ['4', '', Infinity, NaN]) assert.throws(() => score({ skuCount: value }), TypeError);
});
test('invalid enum values including prototype property names are rejected', () => {
  for (const field of ['globalization', 'recall', 'socialInsurance', 'outsourcing']) {
    for (const value of ['typo', '', 'toString', '__proto__', 0, true, {}]) assert.throws(() => score({ [field]: value }), TypeError);
  }
  assert.throws(() => calculateIndex(null), TypeError); assert.throws(() => calculateIndex([]), TypeError);
});
test('explicit nulls act as unknown, and calculations do not mutate input', () => {
  const input = Object.freeze({ developmentMonths: null, globalization: null, recall: null, socialInsurance: null, outsourcing: null, skuCount: null });
  assert.deepEqual(calculateIndex(input).unknowns.map(x => x.field), ['developmentMonths', 'globalization', 'recall', 'socialInsurance', 'outsourcing', 'skuCount']);
  assert.equal(Object.keys(input).length, 6); assert.equal(score({}).inputs.developmentMonths, 36);
});
test('enum options exposed to UIs all have valid core values and weights total 100', () => {
  assert.equal(Object.values(WEIGHTS).reduce((sum, value) => sum + value, 0), 100);
  for (const [field, options] of Object.entries(INPUT_OPTIONS)) {
    assert.equal(new Set(options.map(x => x.value)).size, options.length);
    for (const entry of options) assert.doesNotThrow(() => score({ [field]: entry.value }));
  }
});
test('browser global and CommonJS use the same self-contained implementation', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../shared/scoring.js'), 'utf8'), context);
  assert.equal(typeof context.QuickCarScoring.calculateIndex, 'function');
  assert.equal(context.QuickCarScoring.calculateIndex(favorable).score, 0);
  assert.equal(context.QuickCarScoring.calculateIndex({}).upper, 100);
});
console.log(passed + ' scoring tests passed');
