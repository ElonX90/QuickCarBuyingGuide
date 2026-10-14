'use strict';
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');

// This server serves only the calculator directory on an ephemeral loopback port.
// The checks use a virtual car and artificial notes, never repository model data.
const calculatorRoot = path.resolve(__dirname, '..');
const artifacts = path.join(__dirname, 'artifacts');
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml' };
function createServer() {
  return http.createServer(async (request, response) => {
    try {
      if (!['GET', 'HEAD'].includes(request.method)) { response.writeHead(405); response.end(); return; }
      const pathname = decodeURIComponent(new URL(request.url, 'http://127.0.0.1').pathname);
      const filename = path.resolve(calculatorRoot, '.' + (pathname === '/' ? '/web/index.html' : pathname));
      const relative = path.relative(calculatorRoot, filename);
      if (relative.startsWith('..' + path.sep) || relative === '..' || path.isAbsolute(relative)) { response.writeHead(403); response.end(); return; }
      const content = await fs.readFile(filename);
      response.writeHead(200, { 'Content-Type': mime[path.extname(filename)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
      response.end(request.method === 'HEAD' ? undefined : content);
    } catch (error) {
      response.writeHead(error.code === 'ENOENT' || error.code === 'EISDIR' ? 404 : 400);
      response.end('Unavailable');
    }
  });
}
function listen(server) {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', reject);
      resolve('http://127.0.0.1:' + server.address().port);
    });
  });
}
function closeServer(server) {
  return new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
}
async function textEquals(page, selector, value) {
  // Rendering follows input/change events synchronously; waiting avoids event timing races.
  await page.waitForFunction(({ selector, value }) => {
    const element = document.querySelector(selector);
    return element && element.textContent.trim() === value;
  }, { selector, value });
  assert.equal((await page.locator(selector).innerText()).trim(), value);
}
async function noOverflow(page, width) {
  await page.setViewportSize({ width, height: 900 });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const layout = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  assert.ok(layout.document <= layout.viewport && layout.body <= layout.viewport, 'Horizontal overflow at ' + width + 'px: ' + JSON.stringify(layout));
}

(async () => {
  const server = createServer();
  let browser;
  let page;
  const errors = [];
  const checks = [];
  await fs.mkdir(artifacts, { recursive: true });
  try {
    const origin = await listen(server);
    browser = await chromium.launch({ headless: true });
    page = await browser.newPage({ viewport: { width: 1280, height: 1024 }, deviceScaleFactor: 1, acceptDownloads: true });
    page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.message));
    const response = await page.goto(origin + '/web/index.html', { waitUntil: 'networkidle' });
    assert.equal(response.status(), 200);
    await textEquals(page, '#score-value', '—');
    assert.equal(await page.locator('#form-error').isVisible(), false);

    await page.locator('button[type="submit"]').click();
    await textEquals(page, '#score-value', '0–100');
    await textEquals(page, '#coverage-value', '0%');
    assert.match(await page.locator('#next-evidence').innerText(), /开发周期.*40分/);
    checks.push('All unknown inputs preserve full range');

    await page.locator('#example').click();
    await textEquals(page, '#score-value', '29.7–44.7');
    await textEquals(page, '#coverage-value', '85%');
    assert.equal(await page.locator('#breakdown .dimension').count(), 5);
    assert.match(await page.locator('#interpretation').innerText(), /不是.*速成概率/);
    checks.push('Virtual example and five dimension contributions');

    await page.locator('#development').fill('48');
    await page.locator('#insurance').selectOption('full');
    await page.locator('#outsourcing').selectOption('absent');
    await page.locator('#sku').fill('3');
    await textEquals(page, '#score-value', '0');
    await textEquals(page, '#coverage-value', '100%');
    await page.locator('#outsourcing').selectOption('present');
    await page.locator('#insurance').selectOption('unknown');
    await textEquals(page, '#score-value', '15');
    assert.match(await page.locator('#objections').innerText(), /不建议购买/);
    assert.match(await page.locator('#next-evidence').innerText(), /五险一金/);
    checks.push('Labor maximum retains independent preference conflict and raw unknown');

    await page.locator('#development').fill('0');
    await textEquals(page, '#score-value', '—');
    assert.equal(await page.locator('#form-error').isVisible(), true);
    await page.locator('#development').fill('24');
    await page.locator('#sku').fill('2.5');
    assert.equal(await page.locator('#form-error').isVisible(), true);
    await textEquals(page, '#score-value', '—');
    checks.push('Zero duration and fractional SKU rejected');

    await page.locator('#example').click();
    const injection = '<img src=x onerror="window.bad=1">';
    const notes = '虚拟测试来源笔记，不涉及任何真实企业或员工资料';
    await page.locator('#car-name').fill(injection);
    await page.locator('.evidence > summary').click();
    await page.locator('#evidence-notes').fill(notes);
    assert.equal(await page.evaluate(() => window.bad), undefined);
    assert.equal(await page.locator('#result-car img').count(), 0);
    assert.equal(await page.locator('#result-car').innerText(), injection);
    checks.push('User content renders as text without injected DOM');

    await page.locator('#save-draft').click();
    assert.notEqual(await page.evaluate(() => localStorage.getItem('quickcar-calculator-draft-v1')), null);
    await page.locator('#reset').click();
    await textEquals(page, '#score-value', '—');
    await page.locator('#restore-draft').click();
    await textEquals(page, '#score-value', '29.7–44.7');
    assert.equal(await page.locator('#car-name').inputValue(), injection);
    assert.equal(await page.locator('#evidence-notes').inputValue(), notes);
    assert.equal(await page.locator('#result-car img').count(), 0);

    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
    await page.locator('#copy-result').click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('结果已复制'));
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    assert.match(copied, /用户输入，未经核验/);
    assert.match(copied, /29\.7–44\.7/);
    assert.ok(!copied.includes(notes), 'Evidence notes must not enter the copied summary');
    checks.push('Clipboard summary labels unverified input and excludes notes');

    const downloadEvent = page.waitForEvent('download');
    await page.locator('#export-result').click();
    const download = await downloadEvent;
    assert.equal(download.suggestedFilename(), 'quickcar-calculation.json');
    assert.equal(await download.failure(), null);
    const record = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
    assert.equal(record.evidenceStatus, 'user_reported_unreviewed');
    assert.equal(record.evidenceNotes, notes);
    assert.equal(record.car, injection);
    assert.equal(record.inputs.developmentMonths, 24);
    assert.equal(record.result.lower, 29.666667);
    assert.equal(record.result.upper, 44.666667);
    assert.equal(record.result.knownWeight, 85);
    checks.push('Local draft restore and valid JSON download');

    await page.locator('#delete-draft').click();
    assert.equal(await page.evaluate(() => localStorage.getItem('quickcar-calculator-draft-v1')), null);
    checks.push('Local draft deletion');

    // Screenshots contain only the virtual example, not the text injection or user data.
    await page.locator('#example').click();
    await page.screenshot({ path: path.join(artifacts, 'desktop.png'), fullPage: true });
    for (const width of [320, 375, 390, 430, 768, 1024, 1280]) await noOverflow(page, width);
    await noOverflow(page, 390);
    await page.screenshot({ path: path.join(artifacts, 'mobile.png'), fullPage: true });
    checks.push('320–1280px responsive layouts without horizontal overflow');
    assert.deepEqual(errors, []);
    await fs.writeFile(path.join(artifacts, 'checks.json'), JSON.stringify({ ok: true, checks, browserErrors: errors, screenshots: ['desktop.png', 'mobile.png'] }, null, 2) + '\n');
    console.log(JSON.stringify({ ok: true, checks, browserErrors: errors }));
  } catch (error) {
    if (page && !page.isClosed()) await page.screenshot({ path: path.join(artifacts, 'failure.png'), fullPage: true }).catch(() => {});
    await fs.writeFile(path.join(artifacts, 'failure.json'), JSON.stringify({ ok: false, completedChecks: checks, browserErrors: errors, error: error.message }, null, 2) + '\n').catch(() => {});
    throw error;
  } finally {
    try { if (browser) await browser.close(); }
    finally { if (server.listening) await closeServer(server); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
