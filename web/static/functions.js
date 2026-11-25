// Funciones: código propio (Python o JavaScript) que un paso «Ejecutar una función» corre con los slots que elijas.
// Lo que devuelve con nombre de slot se guarda solo. Corre en el servidor (runner.py), con 5 s de límite.
document.head.append(h('style', {}, `
  .fn-intro { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
  .fn-intro p { margin: 0; }
  .fn-note { font-size: 13px; color: var(--muted); }
  .fn-form { display: flex; flex-direction: column; gap: 14px; }
  .fn-langs { display: inline-flex; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; align-self: flex-start; }
  .fn-langs button { padding: 6px 14px; font-weight: 600; color: var(--muted); }
  .fn-langs button[aria-pressed="true"] { background: var(--brand-soft); color: var(--brand); }
  .fn-chip { display: inline-flex; align-items: center; gap: 2px; background: var(--brand-soft); color: var(--brand); border-radius: 999px; padding: 2px 4px 2px 10px; font-size: 13px; font-weight: 600; }
  .fn-chip .icon-btn { width: 22px; height: 22px; color: inherit; }
  .fn-code { display: flex; border: 1px solid var(--line); border-radius: 10px; background: var(--soft); overflow: hidden; }
  .fn-code:focus-within { border-color: var(--brand); }
  .fn-code pre, .fn-code textarea, .fn-json { font: 13.5px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; tab-size: 4; }
  .fn-code .fn-gutter { margin: 0; padding: 10px 8px 10px 10px; text-align: right; color: var(--muted); user-select: none; border-right: 1px solid var(--line); min-width: 36px; opacity: .7; }
  .fn-edit { flex: 1; min-width: 0; display: grid; }
  .fn-edit > * { grid-area: 1 / 1; }
  .fn-code .fn-hl { margin: 0; padding: 10px 12px; white-space: pre; overflow: hidden; color: var(--ink); pointer-events: none; }
  .fn-code textarea { min-width: 0; border: 0; border-radius: 0; background: transparent; color: transparent; caret-color: var(--ink); padding: 10px 12px; resize: none; white-space: pre; overflow-x: auto; overflow-y: hidden; min-height: 140px; outline: none; }
  .fn-code textarea::selection { background: color-mix(in srgb, var(--brand) 28%, transparent); }
  :root { --code-fn: #8A3FC0; }
  :root[data-theme="dark"] { --code-fn: #D7A2FF; }
  .tk-k { color: var(--brand); }   /* sin negrita: cambiaría el ancho y el cursor quedaría corrido */
  .tk-s { color: var(--ok); }
  .tk-c { color: var(--muted); font-style: italic; }
  .tk-n { color: var(--warn); }
  .tk-b, .tk-f { color: var(--code-fn); }
  .fn-test { display: flex; flex-direction: column; gap: 10px; }
  .fn-ok { color: var(--ok); font-weight: 600; }
  .fn-bad { color: var(--warn); font-weight: 600; }
  .fn-json { margin: 0; padding: 10px 12px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; overflow-x: auto; white-space: pre; color: var(--ink); }
  .fn-json mark { background: var(--brand-soft); color: var(--brand); border-radius: 4px; padding: 0 2px; }
  .fn-json .fn-to { font-family: system-ui, sans-serif; font-size: 12px; color: var(--muted); }
  .fn-json .fn-to button { font-size: 12px; }
  .fn-logs { margin: 0; padding: 8px 10px; background: var(--surface); border: 1px dashed var(--line); border-radius: 8px; white-space: pre-wrap; overflow-wrap: anywhere; font: 12.5px/1.5 ui-monospace, Menlo, Consolas, monospace; color: var(--muted); }
  .fn-examples { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; width: 100%; max-width: 680px; }
  .fn-example { text-align: left; border: 1px solid var(--line); background: var(--surface); border-radius: 12px; padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; color: var(--ink); }
  .fn-example:hover { border-color: var(--brand); }
  .fn-example small { color: var(--muted); }
  .fn-uses { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 14px; color: var(--muted); }
  .badge.function { background: var(--ink); color: var(--surface); }
  @media (max-width: 760px) { .fn-code pre { min-width: 28px; padding-left: 6px; } }
`));

const FN_TEMPLATES = {
  python: `def run(inputs):
    # inputs trae los slots que elegiste arriba, por ejemplo inputs["dni"]
    # devolvé un objeto: lo que se llame igual que un slot se guarda solo
    return {"resultado": "ok"}
`,
  javascript: `async function run(inputs) {
  // inputs trae los slots que elegiste arriba, por ejemplo inputs.dni
  // devolvé un objeto: lo que se llame igual que un slot se guarda solo
  return { resultado: "ok" };
}
`,
};
const FN_LANGS = [['python', 'Python'], ['javascript', 'JavaScript']];

// Ejemplos listos para usar. outputs = slots que se crean para que lo que devuelve se guarde solo.
const FN_EXAMPLES = [
  { name: 'validar_cuit', title: 'Validar CUIT', sub: 'Revisa el dígito verificador y lo deja con guiones', language: 'python', inputs: ['cuit'], outputs: ['cuit_valido'],
    description: 'Revisa si un CUIT/CUIL es válido (11 números y dígito verificador). Devuelve cuit_valido (true/false) y el cuit con guiones.',
    code: `import re

def run(inputs):
    numeros = re.sub(r"\\D", "", str(inputs.get("cuit") or ""))
    if len(numeros) != 11:
        return {"cuit_valido": False}
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    resto = sum(int(n) * p for n, p in zip(numeros, pesos)) % 11
    digito = 0 if resto == 0 else 11 - resto
    if digito == 10 or digito != int(numeros[10]):
        return {"cuit_valido": False}
    return {"cuit_valido": True, "cuit": numeros[:2] + "-" + numeros[2:10] + "-" + numeros[10]}
` },
  { name: 'total_pedido', title: 'Calcular total del pedido', sub: 'Cantidad × precio, con 10% off desde 6 unidades', language: 'javascript', inputs: ['cantidad', 'precio'], outputs: ['total', 'total_texto'],
    description: 'Multiplica cantidad por precio y aplica 10% de descuento desde 6 unidades. Devuelve total (número) y total_texto (como «$ 51.300»).',
    code: `// acepta números escritos como "9.500" o "9500,50"
const numero = (x) => Number(String(x ?? "").replace(/\\./g, "").replace(",", ".")) || 0;

async function run(inputs) {
  const cantidad = numero(inputs.cantidad);
  const subtotal = cantidad * numero(inputs.precio);
  const descuento = cantidad >= 6 ? subtotal * 0.1 : 0;
  const total = Math.round(subtotal - descuento);
  return { total, descuento: Math.round(descuento), total_texto: "$ " + total.toLocaleString("es-AR") };
}
` },
  { name: 'dias_habiles', title: 'Días hábiles hasta una fecha', sub: 'Cuenta de lunes a viernes, sin feriados fijos', language: 'python', inputs: ['fecha'], outputs: ['dias_habiles'],
    description: 'Cuenta los días hábiles desde mañana hasta la fecha (dd/mm/aaaa), sin sábados, domingos ni feriados fijos. Devuelve dias_habiles y fecha_valida.',
    code: `from datetime import date, datetime, timedelta

# feriados nacionales de fecha fija (mes, día); sumá los móviles de cada año si los necesitás
FERIADOS = {(1, 1), (3, 24), (4, 2), (5, 1), (5, 25), (7, 9), (12, 8), (12, 25)}

def run(inputs):
    try:
        hasta = datetime.strptime(str(inputs.get("fecha") or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return {"fecha_valida": False}
    dia, cuenta = date.today() + timedelta(days=1), 0
    while dia <= hasta:
        if dia.weekday() < 5 and (dia.month, dia.day) not in FERIADOS:
            cuenta += 1
        dia += timedelta(days=1)
    return {"fecha_valida": True, "dias_habiles": cuenta}
` },
];

const fnState = new WeakMap();   // estado de la prueba por función (no se guarda)
const fnOf = (name) => (agent.functions || []).find((f) => f.name === name);
function fnName(raw, except) {   // nombre tipo identificador y único
  const base = slug(raw) || 'funcion';
  let name = base, i = 2;
  while ((agent.functions || []).some((f) => f !== except && f.name === name)) name = base + '_' + i++;
  return name;
}
function fnUses(name) {
  return agent.flows.filter((f) => { let used = false; walkSteps((s) => { if (s.type === 'function' && s.function === name) used = true; }, f.steps); return used; });
}
function fnCreate(def) {         // agrega la función (con sus slots) y la deja elegida
  agent.functions ||= [];
  const fn = { name: fnName(def.name || 'mi_funcion'), description: def.description || '', language: def.language || 'python',
    inputs: (def.inputs || []).map((n) => ensureSlot(n)), code: def.code ?? FN_TEMPLATES[def.language || 'python'] };
  (def.outputs || []).forEach((n) => ensureSlot(n));
  agent.functions.push(fn);
  sel.functions = agent.functions.length - 1;
  touch();
  return fn;
}
function fnOpen(fn) { section = 'functions'; sel.functions = agent.functions.indexOf(fn); render(); $('#center').scrollTop = 0; }
const fnOpenFlow = (f) => { section = 'flows'; sel.flows = agent.flows.indexOf(f); render(); $('#center').scrollTop = 0; };

// ---------- editor de código ----------
function codeEditor(fn, onRun) {
  const gutter = h('pre', { class: 'fn-gutter', 'aria-hidden': 'true' });
  const hl = h('pre', { class: 'fn-hl', 'aria-hidden': 'true' });
  const lines = () => { gutter.textContent = Array.from({ length: ta.value.split('\n').length }, (_, i) => i + 1).join('\n'); };
  const paint = () => { hl.innerHTML = highlightCode(ta.value, fn.language); };
  const ta = h('textarea', { spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off', wrap: 'off', 'aria-label': 'Código de la función',
    ...bind(fn, 'code', (e) => { grow(e.target); lines(); paint(); }) });
  const put = (text) => {        // inserta como si se tipeara: así Cmd/Ctrl+Z lo deshace
    if (!document.execCommand('insertText', false, text)) { ta.setRangeText(text, ta.selectionStart, ta.selectionEnd, 'end'); ta.dispatchEvent(new Event('input')); }
  };
  ta.onkeydown = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); return onRun(); }
    const unit = fn.language === 'javascript' ? '  ' : '    ';
    const v = ta.value, a = ta.selectionStart, b = ta.selectionEnd;
    if (e.key === 'Tab') {
      e.preventDefault();
      if (a === b && !e.shiftKey) return put(unit);
      const start = v.lastIndexOf('\n', a - 1) + 1;
      const end = a === b ? (v.indexOf('\n', a) + 1 || v.length + 1) - 1 : v[b - 1] === '\n' ? b - 1 : b;
      const block = v.slice(start, end).split('\n').map((l) => e.shiftKey ? l.replace(new RegExp('^ {1,' + unit.length + '}'), '') : unit + l).join('\n');
      ta.setSelectionRange(start, end); put(block); ta.setSelectionRange(start, start + block.length);
    } else if (e.key === 'Enter' && !e.shiftKey && a === b) {     // mantiene la sangría, y suma una después de «:» o «{»
      e.preventDefault();
      const line = v.slice(v.lastIndexOf('\n', a - 1) + 1, a);
      put('\n' + line.match(/^\s*/)[0] + (/[:{[(]\s*$/.test(line) ? unit : ''));
    }
  };
  ta.addEventListener('scroll', () => { hl.scrollLeft = ta.scrollLeft; });
  lines(); paint();
  return h('div', { class: 'fn-code' }, gutter, h('div', { class: 'fn-edit' }, hl, ta));
}

// Colores del código: un <pre> pintado debajo de un textarea transparente (el textarea sigue siendo el editor).
const CODE_WORDS = {
  python: ['False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield',
    'print len int str float bool dict list set tuple range sorted min max sum abs round enumerate zip isinstance type any all map filter self'],
  javascript: ['async await break case catch class const continue default delete do else export extends false finally for function if import in instanceof let new null of return switch this throw true try typeof undefined var void while yield',
    'console Math JSON Object Array String Number Boolean Date Promise require module exports parseInt parseFloat'],
};
const CODE_TOKENS = {   // 1 comentario, 2 texto, 3 número, 4 palabra
  python: /(#.*)|([rRbBfFuU]{0,2}(?:'''[\s\S]*?(?:'''|$)|"""[\s\S]*?(?:"""|$)|'(?:\\.|[^'\\\n])*'?|"(?:\\.|[^"\\\n])*"?))|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)/g,
  javascript: /(\/\/.*|\/\*[\s\S]*?(?:\*\/|$))|(`(?:\\[\s\S]|[^`\\])*`?|'(?:\\.|[^'\\\n])*'?|"(?:\\.|[^"\\\n])*"?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_$][\w$]*)/g,
};
function highlightCode(code, language) {
  const lang = CODE_TOKENS[language] ? language : 'python';
  const [kw, bi] = CODE_WORDS[lang].map((w) => new Set(w.split(' ')));
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
  let out = '', last = 0;
  for (const m of code.matchAll(CODE_TOKENS[lang])) {
    const [t, comment, text, number, word] = m;
    const cls = comment ? 'c' : text ? 's' : number ? 'n' : kw.has(word) ? 'k' : bi.has(word) ? 'b'
      : /^\s*\(/.test(code.slice(m.index + t.length, m.index + t.length + 40)) ? 'f' : '';
    out += esc(code.slice(last, m.index)) + (cls ? '<span class="tk-' + cls + '">' + esc(t) + '</span>' : esc(t));
    last = m.index + t.length;
  }
  return out + esc(code.slice(last)) + '\n';     // el \n final: que la última línea vacía también ocupe lugar
}

// ---------- probar ----------
function resultView(r) {
  const names = new Set(agent.slots.map((v) => v.name));
  if (r.result === null || typeof r.result !== 'object' || Array.isArray(r.result))
    return [h('pre', { class: 'fn-json' }, JSON.stringify(r.result, null, 2) ?? 'undefined'),
      h('p', { class: 'fn-bad', style: 'font-size:14px' }, 'Devolvé un objeto (por ejemplo {"total": 100}) para que se pueda guardar en slots.')];
  const keys = Object.keys(r.result);
  return h('pre', { class: 'fn-json' }, '{', keys.length ? '\n' : '', keys.map((k, i) => {
    const value = JSON.stringify(r.result[k], null, 2).replace(/\n/g, '\n  ');
    return ['  ', names.has(k) ? h('mark', {}, JSON.stringify(k)) : JSON.stringify(k), ': ', value, i < keys.length - 1 ? ',' : '',
      h('span', { class: 'fn-to' }, names.has(k) ? '   ← se guarda en el slot ' + k : slug(k) !== k ? null
        : ['   ', h('button', { class: 'link', title: 'Crear el slot ' + slug(k) + ' para que se guarde solo', onclick: () => { ensureSlot(k); touch(); render(); } }, 'crear slot «' + slug(k) + '»')]), '\n'];
  }), '}');
}
function testView(fn) {
  const u = fnState.get(fn) || {}; fnState.set(fn, u); u.vars ||= {};
  const value = (n) => u.vars[n] ?? lastSlots[n] ?? '';
  const r = u.result;
  return h('div', { class: 'panel fn-test' },
    h('h2', { style: 'font-size:16px' }, 'Probar'),
    fn.inputs.length ? [h('p', { class: 'help', style: 'font-size:14px' }, 'Poné un valor de ejemplo para cada slot' + (Object.keys(lastSlots).length ? ' (traemos los del chat de prueba).' : '.')),
      fn.inputs.map((n) => lab(n, h('input', { value: typeof value(n) === 'string' ? value(n) : JSON.stringify(value(n)), oninput: (e) => { u.vars[n] = e.target.value; },
        onkeydown: (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') fnRun(fn); } })))]
      : h('p', { class: 'help', style: 'font-size:14px' }, 'No recibe slots: corre con inputs vacío.'),
    h('div', { class: 'row' }, h('button', { class: 'btn small', onclick: () => fnRun(fn), disabled: u.loading }, u.loading ? 'Ejecutando…' : 'Ejecutar'),
      h('span', { class: 'fn-note' }, navigator.platform.includes('Mac') ? '⌘ + Enter' : 'Ctrl + Enter')),
    u.error ? h('p', { class: 'fn-bad' }, 'No se pudo probar: ' + u.error) : null,
    r ? [h('div', { class: 'row' }, h('span', { class: r.ok ? 'fn-ok' : 'fn-bad' }, r.ok ? 'Anduvo bien' : 'Falló: ' + r.error), h('span', { class: 'fn-note' }, r.ms + ' ms')),
      r.ok ? [h('span', { class: 'fn-note' }, 'Devolvió:'), resultView(r)] : null,
      r.traceback ? h('details', {}, h('summary', { class: 'fn-note' }, 'Detalle del error'), h('pre', { class: 'fn-logs' }, r.traceback)) : null,
      r.logs ? [h('span', { class: 'fn-note' }, 'Lo que imprimió (print / console.log):'), h('pre', { class: 'fn-logs' }, r.logs)] : null] : null);
}
async function fnRun(fn) {
  const u = fnState.get(fn) || {}; fnState.set(fn, u); u.vars ||= {};
  if (u.loading) return;
  const typing = document.activeElement?.closest?.('.fn-code') ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
  u.loading = true; u.error = u.result = null; render();
  const inputs = Object.fromEntries(fn.inputs.map((n) => [n, u.vars[n] ?? lastSlots[n] ?? '']));
  try { u.result = await api('POST', '/' + agent.id + '/functions/test', { function: fn, inputs }); } catch (e) { u.error = e.message; }
  u.loading = false;
  if (section !== 'functions') return;
  render();
  const ta = typing && $('.fn-code textarea');   // Cmd/Ctrl+Enter desde el código: seguir escribiendo donde estabas
  if (ta) { ta.focus({ preventScroll: true }); ta.setSelectionRange(...typing); }
}

// ---------- pantalla ----------
const fnIntro = () => h('div', { class: 'fn-intro' },
  h('p', { class: 'help' }, 'Una función es un pedacito de código tuyo que el bot corre en un paso del flujo. Sirve para cálculos, validaciones (CUIT, CBU, fechas), dar formato, combinar varias APIs o lógica que con pasos queda muy larga. Para traer o mandar datos a un solo servicio alcanza con «Consultar un servicio».'),
  h('p', { class: 'fn-note' }, 'El código corre en esta computadora, con un límite de 5 segundos por vez.'));
function examplesMenu(e) {
  openPop(e.currentTarget.getBoundingClientRect(), [h('div', { class: 'pop-title' }, 'Empezar desde un ejemplo'), FN_EXAMPLES.map((x) =>
    h('button', { class: 'opt', onclick: () => { closePop(); fnCreate(x); render(); } }, h('span', { class: 'badge function' }, icon('braces')), h('span', {}, x.title, h('small', {}, x.sub))))]);
}
window.functionsView = function () {
  agent.functions ||= [];
  const fns = agent.functions;
  if (!fns.length) return h('div', { class: 'page' }, h('h1', {}, 'Funciones'), fnIntro(),
    h('div', { class: 'empty' }, h('h2', {}, 'Todavía no hay funciones'),
      h('button', { class: 'btn', onclick: () => { fnCreate({}); render(); $('.title')?.select(); } }, icon('plus'), 'Crear función'),
      h('p', {}, 'O empezá desde un ejemplo que ya anda:'),
      h('div', { class: 'fn-examples' }, FN_EXAMPLES.map((x) => h('button', { class: 'fn-example', onclick: () => { fnCreate(x); render(); } },
        h('strong', {}, x.title), h('small', {}, x.sub), h('small', {}, FN_LANGS.find(([k]) => k === x.language)[1]))))));
  sel.functions = Math.min(sel.functions || 0, fns.length - 1);
  const fn = fns[sel.functions];
  fn.inputs ||= [];
  // el link va DENTRO de la lista: la lista es sticky y, si queda afuera, se le monta encima al hacer scroll
  const list = side('functions', fns, (f) => (f.language === 'javascript' ? 'JavaScript' : 'Python') + ' · ' + ((f.inputs || []).length ? f.inputs.join(', ') : 'sin slots'),
    'Nueva función', () => ({ name: fnName('mi_funcion'), description: '', language: 'python', inputs: [], code: FN_TEMPLATES.python }));
  list.append(h('button', { class: 'link', style: 'font-size:14px;margin:4px 12px;align-self:flex-start', onclick: examplesMenu }, 'Desde un ejemplo'));
  const rename = (e) => {
    const name = fnName(e.target.value, fn);
    if (!slug(e.target.value) || name === fn.name) return render();
    walkSteps((s) => { if (s.type === 'function' && s.function === fn.name) s.function = name; });
    fn.name = name; touch(); render();
  };
  const setLang = (lang) => {
    if (lang === fn.language) return;
    const untouched = !fn.code?.trim() || fn.code === FN_TEMPLATES[fn.language || 'python'];
    fn.language = lang;
    if (untouched) fn.code = FN_TEMPLATES[lang];     // solo si nadie tocó la plantilla: nunca se pisa código propio
    touch(); render();
  };
  const otherLang = fn.code && fn.code !== FN_TEMPLATES[fn.language] && Object.entries(FN_TEMPLATES).some(([k, t]) => k !== fn.language && t === fn.code);
  const adder = { get slot() { return ''; }, set slot(n) { if (n && !fn.inputs.includes(n)) fn.inputs.push(n); } };   // slotPicker escribe acá y suma el slot
  const uses = fnUses(fn.name);
  return h('div', { class: 'two' }, list, h('div', { class: 'page fn-form' },
    h('input', { class: 'title', value: fn.name, 'aria-label': 'Nombre de la función', spellcheck: 'false', onchange: rename }),
    fnIntro(),
    lab('Qué hace (lo ve quien la usa en un flujo, y la IA)', area(fn, 'description', { placeholder: 'Por ejemplo: revisa si el CUIT es válido y lo devuelve con guiones' })),
    h('div', { class: 'stack' }, h('span', { class: 'fn-note' }, 'Lenguaje'),
      h('div', { class: 'fn-langs', role: 'group', 'aria-label': 'Lenguaje' }, FN_LANGS.map(([k, t]) => h('button', { 'aria-pressed': String((fn.language || 'python') === k), onclick: () => setLang(k) }, t))),
      otherLang ? h('p', { class: 'fn-bad', style: 'font-size:14px' }, 'El código es la plantilla del otro lenguaje.', ' ',
        h('button', { class: 'link', onclick: () => { fn.code = FN_TEMPLATES[fn.language]; touch(); render(); } }, 'Usar la de ' + (fn.language === 'javascript' ? 'JavaScript' : 'Python'))) : null),
    h('div', { class: 'stack' }, h('span', { class: 'fn-note' }, 'Recibe estos slots (llegan en inputs)'),
      h('div', { class: 'row', style: 'gap:6px' }, fn.inputs.map((n, i) => h('span', { class: 'fn-chip' }, n, iconBtn('x', 'Quitar ' + n, () => { fn.inputs.splice(i, 1); touch(); render(); }))),
        slotPicker(adder, 'slot'))),
    h('div', { class: 'stack' }, h('span', { class: 'fn-note' }, 'Código: definí run(inputs) y devolvé un objeto. Tab sangra, Shift+Tab saca sangría.'),
      codeEditor(fn, () => fnRun(fn))),
    testView(fn),
    h('div', { class: 'fn-uses' }, uses.length
      ? ['La usa' + (uses.length === 1 ? ' el flujo' : 'n los flujos'), uses.map((f) => h('button', { class: 'link', onclick: () => fnOpenFlow(f) }, f.name))]
      : 'Todavía no la usa ningún flujo. En un flujo, sumá el paso «Ejecutar una función».'),
    h('div', {}, h('button', { class: 'btn danger', onclick: () => confirmBox('Borrar la función', 'Se borra «' + fn.name + '».' + (uses.length ? ' Los pasos que la usan van a quedar sin función hasta que elijas otra.' : ''), 'Borrar función', () => {
      walkSteps((s) => { if (s.type === 'function' && s.function === fn.name) s.function = ''; });
      fns.splice(fns.indexOf(fn), 1); sel.functions = 0; touch(); render();
    }) }, 'Borrar esta función'))));
};

// ---------- paso «Ejecutar una función» del flujo ----------
window.functionStepView = function (s) {
  s.saves ||= [];
  const fns = agent.functions || [];
  const fn = fnOf(s.function);
  const names = fns.map((f) => f.name);
  if (s.function && !fn) names.push(s.function);
  const select = h('select', { value: s.function ?? '', 'aria-label': 'Función', onchange: (e) => {
    if (e.target.value !== '+') { s.function = e.target.value; touch(); return render(); }
    e.target.value = s.function ?? '';
    openPop(e.target.getBoundingClientRect(), nameForm('Nombre, por ejemplo: validar_cuit', 'Crear', (raw) => { const f = fnCreate({ name: raw }); s.function = f.name; fnOpen(f); }));
  } }, h('option', { value: '' }, 'Elegí una función…'), names.map((n) => h('option', { value: n }, n)), h('option', { value: '+' }, '+ Crear una función nueva…'));
  return [
    h('div', { class: 'row' }, 'Ejecutar', select, fn ? h('button', { class: 'link', style: 'font-size:14px', onclick: () => fnOpen(fn) }, 'Ver el código') : null),
    s.function && !fn ? h('p', { class: 'help', style: 'font-size:14px;color:var(--warn)' }, '«' + s.function + '» ya no existe. Elegí otra.') : null,
    fn?.description ? h('p', { class: 'help', style: 'font-size:14px' }, fn.description) : null,
    fn ? h('p', { class: 'help', style: 'font-size:14px' }, fn.inputs?.length ? ['Le pasa ', fn.inputs.map((n, i) => [i ? ', ' : '', h('strong', {}, n)]), '.'] : 'No recibe slots (se eligen en la función).') : null,
    h('label', { class: 'row', style: 'gap:8px;font-size:14px' }, h('input', { type: 'checkbox', checked: s.auto_save !== false, onchange: (e) => { s.auto_save = e.target.checked; touch(); } }),
      'Lo que devuelva con nombre de slot se guarda solo'),
    h('div', { class: 'stack' },
      s.saves.map((x, i) => h('div', { class: 'save-row' }, h('input', { ...bind(x, 'expr'), placeholder: 'result.total', 'aria-label': 'Dato que devuelve', spellcheck: 'false' }), 'en', slotPicker(x, 'slot'),
        iconBtn('x', 'Quitar', () => { s.saves.splice(i, 1); touch(); render(); }))),
      h('div', { class: 'row' }, h('button', { class: 'link', style: 'font-size:14px', onclick: () => { s.saves.push({ expr: 'result.', slot: '' }); touch(); render(); } }, 'Guardar además…'),
        s.saves.some((x) => x.expr === 'ok') ? null : h('button', { class: 'link', style: 'font-size:14px', onclick: () => { s.saves.push({ expr: 'ok', slot: ensureSlot('funcion_ok') }); touch(); render(); } },
          'Guardar si salió bien (para tomar un camino)')),
      h('p', { class: 'help', style: 'font-size:13px' }, s.saves.some((x) => /\b(ok|error)\b/.test(x.expr || ''))
        ? 'Si falla, el flujo sigue: usá el slot de ok (true/false) o error en un «Tomar un camino».'
        : 'Si falla, el flujo se corta y avisa en el chat. Guardá ok o error para seguir y decidir qué hacer.')),
  ];
};
