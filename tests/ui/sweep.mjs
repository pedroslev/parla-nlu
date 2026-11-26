// Barrido de un rol en Chrome sin ventana, por CDP (sin dependencias: Node 22+ trae WebSocket).
//   node tests/ui/sweep.mjs <rol> <usuario>     con BASE, AGENTS (ids con coma), PASSWORD, CHROME y LANGS (es,en,pt)
// Lo arma y lo corre tests/ui/run.py. Para cada idioma x agente x sección del menú: excepciones de JS, errores de consola,
// HTTP >= 400, avisos [role=alert], «null»/«undefined»/«NaN»/«[object …]» a la vista, palabras en español en en/pt (solo
// en la interfaz: lo del bot va marcado con data-content) y que el enlace a Auditoría no abra para quien no es dueño.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, existsSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [ROLE, USER] = process.argv.slice(2);
const { BASE, PASSWORD } = process.env, AGENTS = process.env.AGENTS.split(','), LANGS = (process.env.LANGS || 'es,en,pt').split(',');
const profile = mkdtempSync(join(tmpdir(), 'parla-ui-'));
const chrome = spawn(process.env.CHROME || 'google-chrome', ['--headless=new', '--remote-debugging-port=0', '--user-data-dir=' + profile,
  '--window-size=' + (process.env.WIDTH || 1440) + ',900', '--no-first-run', '--disable-gpu', '--disable-dev-shm-usage', ...(process.env.CI ? ['--no-sandbox'] : []), 'about:blank'],
{ stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const annotate = (msg) => { if (process.env.GITHUB_ACTIONS) console.log(`::error title=UI sweep ${ROLE}::${String(msg).replace(/\r?\n/g, '%0A')}`); };   // visible en GitHub sin abrir el log
const die = (msg) => { console.log(`[${ROLE}] ${msg}`); annotate(msg); chrome.kill(); process.exit(2); };

let port;
for (let i = 0; i < 100 && !port; i++) {   // Chrome elige el puerto y lo anota en el perfil: varios roles en paralelo no chocan
  await sleep(100);
  const file = join(profile, 'DevToolsActivePort');
  if (existsSync(file)) port = readFileSync(file, 'utf8').split('\n')[0];
}
if (!port) die('Chrome no arrancó (CHROME=' + (process.env.CHROME || 'google-chrome') + ')');
const page = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });

let id = 0, where = 'login', recording = false;
const wait = {}, inflight = new Map(), problems = [], requested = [];
let lastNet = Date.now();
ws.onmessage = (m) => {
  const d = JSON.parse(m.data), p = d.params;
  if (wait[d.id]) { wait[d.id](d); delete wait[d.id]; return; }
  if (d.method === 'Network.requestWillBeSent') {
    requested.push(p.request.url);
    if (['Fetch', 'XHR', 'Document', 'Script'].includes(p.type)) { inflight.set(p.requestId, { method: p.request.method, at: Date.now() }); lastNet = Date.now(); }
  }
  if (d.method === 'Network.loadingFinished' || d.method === 'Network.loadingFailed') { inflight.delete(p.requestId); lastNet = Date.now(); }
  if (!recording) return;           // antes de entrar, un 401 es lo esperado
  if (d.method === 'Runtime.exceptionThrown') problems.push([where, 'JS', p.exceptionDetails.exception?.description?.split('\n')[0] || p.exceptionDetails.text]);
  if (d.method === 'Runtime.consoleAPICalled' && p.type === 'error') problems.push([where, 'consola', p.args.map((a) => a.value ?? a.description).join(' ').slice(0, 200)]);
  if (d.method === 'Network.responseReceived' && p.response.status >= 400) {
    problems.push([where, 'HTTP ' + p.response.status, (inflight.get(p.requestId)?.method || '') + ' ' + p.response.url.replace(BASE, '')]);
  }
};
const send = (method, params = {}) => new Promise((r) => { wait[++id] = r; ws.send(JSON.stringify({ id, method, params })); });
const ev = async (js) => {
  const r = await send('Runtime.evaluate', { expression: `(async () => { ${js} })()`, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(where + ': ' + (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text));
  return r.result?.result?.value;
};
// Listo = la condición se cumple y la red lleva 150 ms quieta (sin esperas fijas). Tope: 10 s.
async function ready(cond = 'true') {
  const until = Date.now() + 10000;
  while (Date.now() < until) {
    const busy = [...inflight.values()].some((r) => Date.now() - r.at < 5000);   // más de 5 s abierto: un stream, no cuenta
    if (!busy && Date.now() - lastNet > 150 && await ev(`return !!(${cond})`)) return true;
    await sleep(50);
  }
  problems.push([where, 'lento', 'no quedó lista en 10 s: ' + cond]);
  return false;
}
await send('Runtime.enable'); await send('Network.enable'); await send('Page.enable');
const go = async (url, cond = 'true') => { await send('Page.navigate', { url }); await ready(`document.readyState === 'complete' && (${cond})`); };

// Lo que se revisa en cada pantalla. Texto a la vista, sin <pre>/<code> ni lo que es del bot ([data-content]).
const CHECK = `
  const lang = document.documentElement.lang || 'es';
  const skip = 'pre, code, script, style, textarea, [data-content], .msg, q';   // globos del chat y citas: lo que dijo alguien
  const texts = [], walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = walker.nextNode());) {
    const el = n.parentElement;
    if (!n.textContent.trim() || el.closest(skip) || !el.checkVisibility()) continue;
    texts.push(n.textContent);
  }
  const all = texts.join('\\n');
  const broken = all.match(/(^|[^\\w])(null|undefined|NaN|\\[object [A-Za-z]+\\])([^\\w]|$)/);
  const near = broken ? all.slice(Math.max(0, broken.index - 40), broken.index + 40).replace(/\\s+/g, ' ') : '';
  const es = lang === 'en' ? /\\b(conversación|conversaciones|está|todavía|también|después|acá|elegí|tocá|escribí|guardá|cargando|intenciones|flujos|reportes|probar|entrenar|guardar|borrar|agregar)\\b|[¿¡]/gi
    : lang === 'pt' ? /\\b(conversación|conversaciones|todavía|también|después|acá|elegí|tocá|escribí|guardá|cargando|intenciones|flujos|reportes|probar|entrenar|borrar|agregar)\\b|[¿¡]/gi : null;
  const spanish = es ? [...new Set(texts.filter((x) => x.match(es)).map((x) => x.trim().slice(0, 60)))].slice(0, 4) : [];
  const alerts = [...document.querySelectorAll('[role=alert]')].filter((e) => e.checkVisibility()).map((e) => e.textContent.trim()).filter(Boolean);
  return { broken: broken ? broken[2] + ' en «…' + near + '…»' : '', spanish: spanish.map((x) => '«' + x + '»').join(' '), alerts: alerts.slice(0, 3),
           empty: !!document.querySelector('#center') && !document.querySelector('#center').innerText.trim() };`;
async function check() {
  if (process.env.SHOTS) {          // SHOTS=carpeta: una captura por pantalla, para mirar a ojo
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(process.env.SHOTS, `${ROLE}-${where.replaceAll(':', '-')}.png`), Buffer.from(shot.result.data, 'base64'));
  }
  const r = await ev(CHECK);
  if (r.broken) problems.push([where, 'texto roto', r.broken]);
  if (r.spanish) problems.push([where, 'español en la interfaz', r.spanish]);
  for (const a of r.alerts) problems.push([where, 'aviso', a.slice(0, 200)]);
  if (r.empty) problems.push([where, 'vacía', 'la sección no muestra nada']);
}
const hash = async (h, cond) => { await ev(`location.hash = ${JSON.stringify(h)}`); await ready(cond); };

const started = Date.now();
let pages = 0;
await go(BASE + '/');
const login = await ev(`const r = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: ${JSON.stringify(USER)}, password: ${JSON.stringify(PASSWORD)} }) }); return r.status`);
if (login !== 200) die('no pudo entrar como ' + USER + ' (' + login + ')');
recording = true;
for (const lang of LANGS) {
  where = `${lang}:inicio`;
  await go(`${BASE}/?lang=${lang}`);
  await ready(`window.me && document.querySelector('.home')`);
  await check(); pages++;
  where = `${lang}:usuarios`;
  await hash('#/usuarios', `document.querySelector('.us-page') && document.querySelector('.us-page').childElementCount > 1`);
  await check(); pages++;
  where = `${lang}:auditoría`;
  const before = requested.length;
  await hash('#/auditoria', ROLE === 'owner' ? `location.hash === '#/auditoria' && document.querySelector('main')` : `document.querySelector('.home button.agent')`);
  if (ROLE !== 'owner') {
    if (requested.slice(before).some((u) => u.includes('/api/audit'))) problems.push([where, 'permisos', 'quien no es dueño llegó a pedir /api/audit']);
    if (await ev(`return location.hash === '#/auditoria' || !!document.querySelector('.au-table')`)) problems.push([where, 'permisos', 'la Auditoría abrió para ' + ROLE]);
  } else await check();
  pages++;
  for (const ag of AGENTS) {
    where = `${lang}:${ag}`;
    await hash(`#/${ag}`, `agent?.id === '${ag}' && document.querySelector('#nav [data-section]')`);
    await ready(`document.querySelector('#nav [data-section]')`);
    const sections = await ev(`return [...document.querySelectorAll('#nav [data-section]')].map((b) => b.dataset.section)`);
    if (!sections?.length) { problems.push([where, 'menú', 'sin secciones']); continue; }
    for (const s of sections) {
      where = `${lang}:${ag}:${s}`;
      const t0 = Date.now();
      await hash(`#/${ag}/${s}`, `document.querySelector('#nav [aria-current=page]')?.dataset.section === '${s}' && !document.querySelector('#center .empty[role=status]')`);
      await check(); pages++;
      if (process.env.DEBUG) console.log(`[${ROLE}] ${where} ${Date.now() - t0} ms`);
    }
  }
}
const seen = new Set();
for (const p of problems) { const k = p.join('  '); if (!seen.has(k)) { seen.add(k); console.log(`[${ROLE}] ${k}`); } }
if (seen.size) annotate([...seen].slice(0, 15).join('\n'));
console.log(`[${ROLE}] ${pages} pantallas en ${((Date.now() - started) / 1000).toFixed(0)}s: ${seen.size ? seen.size + ' problemas' : 'ok'}`);
chrome.kill();
await sleep(200);
try { rmSync(profile, { recursive: true, force: true }); } catch {}
process.exit(seen.size ? 1 : 0);
