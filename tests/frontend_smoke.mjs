// Frontend smoke test via Chrome DevTools Protocol (no deps; Node >= 22 built-in WebSocket).
// Usage: node tests/frontend_smoke.mjs   (starts its own server on :8011 and headless Chrome)
import { spawn } from 'node:child_process';
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 8011, DBG = 9233, URL = `http://localhost:${PORT}/`;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const procs = [];
const done = (code, msg) => { if (msg) console.log(msg); procs.forEach(p => { try { p.kill('SIGKILL') } catch {} }); process.exit(code); };
const fail = (m) => done(1, 'SMOKE FAIL: ' + m);
setTimeout(() => fail('timeout'), 150000);

const srv = spawn('.venv/bin/python', ['-m', 'uvicorn', 'backend.app:app', '--port', String(PORT)], { env: { ...process.env, DISABLE_SCHEDULER: '1', SOURCES_MOCK: '1', OVERNIGHT_OFFLINE: '1' }, stdio: 'ignore' });
procs.push(srv);
for (let i = 0; i < 40; i++) { try { if ((await fetch(URL + 'health')).ok) break } catch {} await sleep(250); if (i === 39) fail('server did not start'); }

const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${DBG}`, '--user-data-dir=/tmp/ov-smoke-profile', '--window-size=1500,1400', 'about:blank'], { stdio: 'ignore' });
procs.push(chrome);
let targets;
for (let i = 0; i < 40; i++) { try { targets = await (await fetch(`http://localhost:${DBG}/json`)).json(); if (targets.find(t => t.type === 'page')) break } catch {} await sleep(250); if (i === 39) fail('chrome did not start'); }
const ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pend = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id) } };
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) });
const ev = async (expr) => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails)); return r.result?.result?.value };
const waitFor = async (expr, what, ms = 8000) => { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(expr)) return; await sleep(150) } fail('timed out waiting for ' + what) };
// React-controlled input: set value through the native setter then dispatch input.

await send('Page.enable'); await send('Page.navigate', { url: URL + '#/overview' });
const text = () => ev(`document.body.innerText`);
const shot = async (name) => { const r = await send('Page.captureScreenshot', { format: 'png' }); (await import('node:fs')).writeFileSync(`/tmp/ov-${name}.png`, Buffer.from(r.result.data, 'base64')); };
const route = async (r) => { await ev(`location.hash='#/${r}'`); await sleep(250); };
await waitFor(`!!document.getElementById('sidebar')`, 'sidebar render');

// persistent safety strip on every page
const strip = await ev(`document.getElementById('mode-strip').innerText`);
if (!strip.includes('DRY RUN — No external changes will be made.') || !strip.includes('LIVE SOURCES') || !strip.includes('MOCK SOURCES')) fail('mode strip: ' + strip);

// empty states before any run
await waitFor(`document.getElementById('page').innerText.includes('No plan yet')`, 'overview empty state');

// run a night (demo data) via the header button
await ev(`document.getElementById('run-night').click()`);
await waitFor(`document.getElementById('page').innerText.includes('Risk summary')`, 'overview after run', 25000);
await waitFor(`document.getElementById('page').innerText.includes('Write policy')`, 'system health card loads', 10000);
await shot('overview');

// every route renders with its title
const expect = { overview: 'Overview', tasks: 'Inbox / Tasks', council: 'Council Decisions', actions: 'Actions', audit: 'Audit Log', sources: 'Sources', evals: 'Evaluations', settings: 'Settings / Safety' };
for (const [r, title] of Object.entries(expect)) {
  await ev(`document.querySelector('[data-nav="${r}"]').click()`);
  await waitFor(`document.getElementById('page-title').innerText==='${title}'`, 'route ' + r);
  if (!(await ev(`document.getElementById('mode-strip').innerText.includes('DRY RUN')`))) fail('dry-run strip missing on ' + r);
  await sleep(400); await shot(r);
}

// tasks: filters, search, drawer, add-a-task
await route('tasks');
await waitFor(`!!document.getElementById('task-table')`, 'task table');
await ev(`document.querySelector('[data-f="AUTO"]').click()`); await sleep(200);
if (!(await ev(`[...document.querySelectorAll('#task-table tbody tr')].every(r=>r.innerText.includes('AUTO'))&&document.querySelectorAll('#task-table tbody tr').length>5`))) fail('AUTO filter');
await ev(`document.querySelector('[data-f="BLOCKED"]').click()`); await sleep(200);
if (!(await ev(`[...document.querySelectorAll('#task-table tbody tr')].every(r=>r.innerText.includes('BLOCKED'))&&document.querySelectorAll('#task-table tbody tr').length>=3`))) fail('BLOCKED filter');
await ev(`document.querySelector('[data-f="ALL"]').click()`);
await ev(`(()=>{const i=document.getElementById('task-search');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,'insurance');i.dispatchEvent(new Event('input',{bubbles:true}))})()`); await sleep(250);
if ((await ev(`document.querySelectorAll('#task-table tbody tr').length`)) !== 1) fail('search');
await ev(`document.querySelector('#task-table tbody tr').click()`);
await waitFor(`!!document.getElementById('task-drawer')&&document.getElementById('task-drawer').innerText.toLowerCase().includes('policy decision')`, 'task drawer');
if ((await text()).match(/(Bearer |ya29\.|GOC.PX-)/)) fail('secret-looking string in drawer');
await shot('drawer');
await ev(`[...document.querySelectorAll('#task-drawer button')].find(b=>b.innerText.includes('council')).click()`);
await waitFor(`document.getElementById('page-title').innerText==='Council Decisions'&&document.getElementById('council-detail').innerText.includes('Final judge decision')`, 'council from drawer');
const cd = await ev(`document.getElementById('council-detail').innerText`);
for (const k of ['Problem summary', 'Evidence retrieved by Superlinked', 'Specialist opinions', 'Debate summary', 'Why this decision was selected', 'Risk Officer', 'Privacy Guard', 'Preference Keeper', 'Efficiency Agent']) if (!cd.includes(k)) fail('council missing ' + k);
await shot('council');

// add task (regression)
await route('tasks'); await waitFor(`!!document.getElementById('task-input')`, 'task input');
await ev(`document.getElementById('task-add').click()`); await waitFor(`!!document.getElementById('task-error')`, 'inline error on empty submit');
const typeText = (t) => ev(`(()=>{const i=document.getElementById('task-input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,${JSON.stringify(t)});i.dispatchEvent(new Event('input',{bubbles:true}))})()`);
await typeText('book dentist, I prefer mornings'); await sleep(200); await ev(`document.getElementById('task-add').click()`);
await waitFor(`document.getElementById('toast')?.innerText.includes('Saved to memory')`, 'toast');
await waitFor(`document.getElementById('your-tasks').innerText.includes('book dentist')`, 'Your tasks entry');
await waitFor(`[...document.querySelectorAll('.chip-pref')].some(e=>e.innerText.includes('mornings'))`, 'preference chip');

// actions: simulated labels, nothing claims real completion, confirm modal
await route('actions'); await waitFor(`!!document.getElementById('actions-table')`, 'actions table');
const at = await ev(`document.getElementById('page').innerText`);
if (!at.includes('SIMULATED') || !at.includes('Nothing here has really executed')) fail('actions simulated labels');
if (/\b(Completed|Done)\b/.test(at)) fail('actions page claims completion');
await ev(`[...document.querySelectorAll('#actions-table button')].find(b=>b.innerText.startsWith('Review')).click()`);
await waitFor(`!!document.getElementById('confirm-modal')&&document.getElementById('confirm-modal').innerText.includes('No external changes will be made')`, 'confirm modal');
await shot('confirm');
await ev(`[...document.querySelectorAll('#confirm-modal button')].find(b=>b.innerText==='Cancel').click()`);

// audit: redacted, zero external writes
await route('audit'); await waitFor(`!!document.getElementById('audit-table')`, 'audit table');
const au = await ev(`document.getElementById('page').innerText`);
if (!au.includes('EXTERNAL WRITES: 0')) fail('external writes not zero: ' + au.slice(0, 200));
if (au.match(/(Bearer |ya29\.|GOC.PX-|1\/\/0)/)) fail('secret-looking string in audit');
await ev(`[...document.querySelectorAll('#audit-tabs button')].find(b=>b.innerText.includes('Retries')).click()`);

// sources: LIVE vs MOCK
await route('sources'); await waitFor(`document.getElementById('page').innerText.includes('Hosted Superlinked')`, 'sources');
const so = await ev(`document.getElementById('page').innerText`);
if (!so.includes('MOCK SOURCES') || !so.includes('LIVE SOURCES')) fail('sources labels');

// evaluations: run simulations
await route('evals'); await waitFor(`!!document.getElementById('run-sims')`, 'evals');
await ev(`document.getElementById('run-sims').click()`);
await waitFor(`document.querySelectorAll('#scenario-table tbody tr').length>=15`, 'scenario results', 30000);
await shot('evals');

// settings: no secret values
await route('settings'); await waitFor(`document.getElementById('page').innerText.includes('Configuration status')`, 'settings');
const se = await ev(`document.getElementById('page').innerText`);
if (!se.includes('values never shown') || se.match(/(GOC.PX-|AIza|ya29\.|sk-ant|xox[bp]-)/)) fail('settings secrets');
await shot('settings');

// responsive: narrow viewport hides the sidebar behind the menu button
await send('Emulation.setDeviceMetricsOverride', { width: 700, height: 900, deviceScaleFactor: 1, mobile: false });
await sleep(300);
if (!(await ev(`getComputedStyle(document.querySelector('.menu')).display!=='none'`))) fail('menu button on narrow screens');
await shot('narrow');
done(0, 'SMOKE OK (8 routes, safety strip, filters, search, drawer, council, actions/confirm, audit redaction, sources, evals, settings, add-task, responsive)');
