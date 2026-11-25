/* Phase 3 browser smoke: seeds a real reservation through the API, then drives
   the student and administrator pages. Uses an isolated test database/service. */
const fs = require('node:fs');
const path = require('node:path');
const { chromium, request } = require('playwright');

const base = (process.env.STUDYSEAT_TEST_URL || 'http://127.0.0.1:5057').replace(/\/$/, '');
const channel = process.env.STUDYSEAT_BROWSER_CHANNEL || 'msedge';
const out = process.env.STUDYSEAT_EVIDENCE_DIR
  ? path.resolve(process.env.STUDYSEAT_EVIDENCE_DIR)
  : path.join(__dirname, '..', 'evidence', 'phase3', 'browser');
const shots = path.join(out, 'screenshots');
fs.mkdirSync(shots, { recursive: true });
const results = { target: base, checks: [], pageErrors: [] };

function check(name, passed, detail = '') {
  results.checks.push({ name, passed: Boolean(passed), detail });
  if (!passed) throw new Error(`check failed: ${name} ${detail}`);
}

function beijing(offsetMinutes) {
  const stamp = new Date(Date.now() + offsetMinutes * 60000 + 8 * 3600 * 1000);
  return `${stamp.toISOString().slice(0, 19)}+08:00`;
}

function tomorrow(hour) {
  const stamp = new Date(Date.now() + 24 * 3600 * 1000 + 8 * 3600 * 1000);
  return `${stamp.toISOString().slice(0, 10)}T${String(hour).padStart(2, '0')}:00:00+08:00`;
}

async function seed() {
  const api = await request.newContext({ baseURL: base });
  let session = await (await api.get('/api/v1/auth/session')).json();
  let csrf = session.data.csrf_token;
  const login = await (
    await api.post('/api/v1/auth/login', {
      data: { username: '832402116', password: '123456' },
      headers: { 'X-CSRF-Token': csrf },
    })
  ).json();
  csrf = login.data.csrf_token;
  const headers = { 'X-CSRF-Token': csrf };
  const create = async body => {
    const response = await api.post('/api/v1/reservations', { data: body, headers });
    if (response.status() !== 201) throw new Error(`seed create failed: ${await response.text()}`);
    return (await response.json()).data;
  };
  const inUse = await create({
    seat_id: 'lib-a101:A01',
    start_at: beijing(2),
    end_at: beijing(42),
    idempotency_key: `browser-use-${Date.now()}`,
  });
  const checked = await api.post(`/api/v1/reservations/${inUse.id}/check-in`, { headers });
  if (checked.status() !== 200) throw new Error(`seed check-in failed: ${await checked.text()}`);
  const pending = await create({
    seat_id: 'lib-a101:A03',
    start_at: tomorrow(10),
    end_at: tomorrow(11),
    idempotency_key: `browser-pending-${Date.now()}`,
  });
  return { api, pending };
}

(async () => {
  const { api, pending } = await seed();
  const browser = await chromium.launch({ channel, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  page.on('pageerror', error => results.pageErrors.push(String(error)));
  await page.goto(`${base}/`, { waitUntil: 'networkidle' });

  await page.fill('#username', '832402116');
  await page.fill('#password', '123456');
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#dashboard:not([hidden])');
  await page.waitForSelector('#reservations li');
  check('student dashboard', (await page.locator('#welcome').textContent()).includes('申子衡'));

  const inUse = page.locator('#reservations li', { hasText: '使用中' }).first();
  check('attendance actions visible', (await inUse.locator('button', { hasText: '暂离' }).count()) === 1);
  await inUse.locator('button', { hasText: '暂离' }).click();
  await page.waitForSelector('#reservations li:has-text("暂离中")');
  check('leave transition', (await page.locator('#status').textContent()).includes('已暂离'));
  await page.locator('#reservations li', { hasText: '暂离中' }).first()
    .locator('button', { hasText: '返回' }).click();
  await page.waitForSelector('#reservations li:has-text("使用中")');
  check('return transition', (await page.locator('#status').textContent()).includes('已返回'));
  check('pending actions', (await page.locator('#reservations li', { hasText: '待签到' })
    .first().locator('button', { hasText: '签到' }).count()) === 1);
  await page.screenshot({ path: path.join(shots, 'student-dashboard.png'), fullPage: true });

  await page.click('#logout');
  await page.waitForSelector('#login-view:not([hidden])');
  await page.fill('#username', 'admin01');
  await page.fill('#password', 'Admin1234');
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#admin:not([hidden])');
  check('admin panel', await page.locator('#admin').isVisible());

  await page.selectOption('#closure-scope', 'room');
  await page.selectOption('#closure-target', 'lib-a101');
  await page.fill('#closure-reason', '设备检修');
  await page.click('#closure-preview');
  await page.waitForSelector('#closure-impact:not([hidden])');
  check('in-use closure blocked', (await page.locator('#closure-impact').textContent()).includes('阻止关闭'));
  check('apply disabled while blocked', await page.locator('#closure-apply').isDisabled());
  await page.screenshot({ path: path.join(shots, 'admin-closure-blocked.png'), fullPage: true });

  await page.selectOption('#closure-scope', 'seat');
  await page.selectOption('#closure-target', pending.seat_id);
  await page.fill('#closure-reason', '座位检修');
  await page.click('#closure-preview');
  await page.waitForSelector('#closure-impact:not([hidden])');
  check('closure preview ready', !(await page.locator('#closure-apply').isDisabled()));
  await page.click('#closure-apply');
  await page.waitForSelector('#closures li:has-text("关闭中")');
  check('closure applied', (await page.locator('#status').textContent()).includes('资源已关闭'));
  check('apply stays disabled', await page.locator('#closure-apply').isDisabled());
  await page.screenshot({ path: path.join(shots, 'admin-closure-applied.png'), fullPage: true });

  await page.locator('#closures li', { hasText: '关闭中' }).first()
    .locator('button', { hasText: '重新开放' }).click();
  await page.waitForSelector('#closures li:has-text("已重开")');
  await page.waitForTimeout(600);
  check('reopen', (await page.locator('#status').textContent()).includes('不会恢复'));
  await page.screenshot({ path: path.join(shots, 'admin-reopened.png'), fullPage: true });

  check('no page errors', results.pageErrors.length === 0, results.pageErrors.join('; '));
  results.passed = results.checks.filter(item => item.passed).length;
  fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(results, null, 2));
  await browser.close();
  await api.dispose();
  console.log(JSON.stringify({ checks: results.passed, pageErrors: results.pageErrors.length }));
})().catch(async error => {
  results.error = String(error);
  fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(results, null, 2));
  console.error(error);
  process.exit(1);
});
