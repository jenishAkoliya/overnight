// Frontend smoke test via Chrome DevTools Protocol (no deps; Node >= 22 built-in WebSocket).
// Usage: node tests/frontend_smoke.mjs   (starts its own server on :8011 and headless Chrome)
import { spawn } from 'node:child_process';
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 8011, DBG = 9233, URL = `http://localhost:${PORT}/`;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const procs = [];
const done = (code, msg) => { if (msg) console.log(msg); procs.forEach(p => { try { p.kill('SIGKILL') } catch {} }); process.exit(code); };
const fail = (m) => done(1, 'SMOKE FAIL: ' + m);
setTimeout(() => fail('timeout'), 60000);

const srv = spawn('.venv/bin/python', ['-m', 'uvicorn', 'backend.app:app', '--port', String(PORT)], { env: { ...process.env, DISABLE_SCHEDULER: '1' }, stdio: 'ignore' });
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
const typeText = (t) => ev(`(()=>{const i=document.getElementById('task-input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,${JSON.stringify(t)});i.dispatchEvent(new Event('input',{bubbles:true}));return true})()`);

await send('Page.enable'); await send('Page.navigate', { url: URL });
await waitFor(`!!document.getElementById('task-input')`, 'page render');

// 1. empty submit -> inline error
await ev(`document.getElementById('task-add').click()`);
await waitFor(`!!document.getElementById('task-error')`, 'inline error on empty submit');

// 2. click Add
await typeText('book dentist, I prefer mornings'); await sleep(200);
await ev(`document.getElementById('task-add').click()`);
await waitFor(`document.getElementById('toast')?.textContent.includes('Saved to memory')`, 'toast');
await waitFor(`document.getElementById('your-tasks').textContent.includes('book dentist')`, 'Your tasks entry');
await waitFor(`document.getElementById('your-tasks').textContent.includes('queued for tonight')`, 'queued status');
await waitFor(`[...document.querySelectorAll('.chip-pref')].some(e=>e.textContent.includes('mornings'))`, 'preference chip');
if ((await ev(`document.getElementById('task-input').value`)) !== '') fail('input not cleared');

// 3. Enter variant
await typeText('renew passport'); await sleep(200);
await ev(`document.getElementById('task-input').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))`);
await waitFor(`document.getElementById('your-tasks').textContent.includes('renew passport')`, 'Enter-submitted task');

// 4. Simulate tonight -> planned in morning
await ev(`fetch('/run-night?sync=true',{method:'POST'}).then(r=>r.json())`);
await waitFor(`document.getElementById('your-tasks').textContent.includes('planned')`, 'planned status after run', 10000);
await waitFor(`document.getElementById('your-tasks').textContent.includes('You asked for this')`, 'why note');
const shot = await send('Page.captureScreenshot', { format: 'png' });
import('node:fs').then(fs => fs.writeFileSync('/tmp/ov-smoke.png', Buffer.from(shot.result.data, 'base64')));
await sleep(300);
done(0, 'SMOKE OK (empty error, Add click, Enter, toast, chip, Your tasks, planned status)');
