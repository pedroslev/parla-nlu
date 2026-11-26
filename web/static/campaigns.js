// Campañas: mensajes salientes a una lista (WhatsApp con plantilla aprobada, Telegram o llamadas). La cola, el ritmo,
// el horario de silencio y las bajas los maneja el servidor; acá se arma la campaña, se inicia y se miran los resultados.
document.head.append(h('style', {}, `
  .cp-row { display: grid; grid-template-columns: minmax(0, 1fr) 160px auto; gap: 6px 14px; align-items: center; text-align: left; padding: 12px 16px; border-bottom: 1px solid var(--line); width: 100%; }
  .cp-row:last-child { border-bottom: 0; }
  .cp-row:hover { background: var(--soft); }
  .cp-row strong { overflow-wrap: anywhere; }
  .cp-row small { color: var(--muted); font-size: 13px; }
  .cp-st { font-size: 12px; font-weight: 600; border-radius: 999px; padding: 2px 10px; background: var(--soft); color: var(--muted); white-space: nowrap; justify-self: start; }
  .cp-st.running { background: color-mix(in srgb, var(--ok) 16%, var(--surface)); color: var(--ok); }
  .cp-st.paused, .cp-st.wait { background: var(--brand-soft); color: var(--brand); }
  .cp-st.canceled { background: var(--warn-soft); color: var(--warn); }
  .cp-scroll { overflow-x: auto; }
  .cp-table { width: 100%; border-collapse: collapse; font-size: 14px; }
  .cp-table th { text-align: left; color: var(--muted); font-weight: 600; font-size: 13px; padding: 6px 8px; border-bottom: 1px solid var(--line); }
  .cp-table td { padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; overflow-wrap: anywhere; }
  @media (max-width: 600px) { .cp-row { grid-template-columns: minmax(0, 1fr) auto; } .cp-row .rp-track { grid-column: 1 / -1; grid-row: 2; } }
`));

const CP_STATUS = { draft: t('Borrador'), running: t('Enviando'), paused: t('En pausa'), done: t('Terminada'), canceled: t('Cancelada') };
const CP_WAIT = { schedule: t('Programada'), quiet_hours: t('En horario de silencio') };
const CP_REC = { queued: t('En cola'), sending: t('Enviando'), sent: t('Enviado'), delivered: t('Entregado'), read: t('Leído'), replied: t('Respondió'),
  failed: t('Falló'), opted_out: t('Se dio de baja'), canceled: t('Cancelado') };
const CP_CH = { whatsapp: 'WhatsApp', telegram: 'Telegram', phone: t('Teléfono (llamada)') };
const CP_KW = { es: 'stop, baja, no me escriban, no me escribas, desuscribir', en: 'stop, unsubscribe, opt out', pt: 'parar, sair, descadastrar' };   // los de fábrica del servidor
let cpFor = null, cpTab = 'list', cpList = null, cpSel = null, cpCur = null, cpRecs = null, cpFilter = '', cpOffset = 0;
let cpError = '', cpNote = '', cpWiz = null, cpOpt = null, cpTimer = null, cpRoot = null, cpBusy = false;

const cpApi = (method, path, body) => api(method, '/' + agent.id + path, body);
const cpHelp = (text, style) => h('p', { class: 'help', style }, text);
const cpDone = (s) => (s.sent || 0) + (s.delivered || 0) + (s.read || 0) + (s.replied || 0) + (s.failed || 0);
const cpWhen = (iso) => (iso || '').replace('T', ' ').slice(0, 16);
function cpStatus(c) {
  const w = c.status === 'running' && CP_WAIT[c.waiting];
  return h('span', { class: 'cp-st ' + (w ? 'wait' : c.status) }, w || CP_STATUS[c.status] || c.status);
}
function cpBar(s) {
  const n = s.total || 0, d = cpDone(s);
  return h('span', { class: 'rp-track', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': n, 'aria-valuenow': d, title: d + ' / ' + n },
    h('span', { style: 'width:' + (n ? (d / n) * 100 : 0) + '%;background:var(--brand)' }));
}
const cpLegal = () => h('div', { class: 'notice' }, icon('lightbulb'), h('span', { class: 'grow' },
  t('Antes de mandar: escribile solo a quien te dio permiso (opt-in), usá plantillas aprobadas y seguí la política de WhatsApp Business. En llamadas, respetá el horario de silencio y las leyes de tu país (por ejemplo, los registros de «no llame»). Es una guía, no asesoramiento legal.')));

// redibuja solo esta sección: el refresco cada 3 s no toca el resto de la pantalla
function cpPaint() { if (cpRoot?.isConnected) cpRoot.replaceChildren(...cpBody().flat(Infinity).filter(Boolean)); }
async function cpRefresh() {
  const myAgent = agent;
  try {
    if (cpTab === 'detail' && cpSel) {
      const q = new URLSearchParams({ status: cpFilter, offset: cpOffset, limit: 50 });
      [cpCur, cpRecs] = await Promise.all([cpApi('GET', '/campaigns/' + cpSel), cpApi('GET', '/campaigns/' + cpSel + '/recipients?' + q)]);
    } else if (cpTab === 'optouts') cpOpt = (await cpApi('GET', '/optouts')).optouts;
    else if (cpTab === 'list') cpList = (await cpApi('GET', '/campaigns')).campaigns;
    cpError = '';
  } catch (e) { cpError = e.message; }
  if (agent === myAgent) cpPaint();
}
function cpGo(tab, sel) {
  cpTab = tab; cpError = cpNote = '';
  if (sel !== undefined) { cpSel = sel; cpCur = cpRecs = null; cpFilter = ''; cpOffset = 0; }
  cpPaint();
  if (tab !== 'new') cpRefresh();
}
function cpTick() {                      // mientras hay una campaña enviando y la sección está abierta
  clearInterval(cpTimer);
  const myAgent = agent;
  cpTimer = setInterval(() => {
    if (section !== 'campaigns' || agent !== myAgent || !cpRoot?.isConnected) { clearInterval(cpTimer); cpTimer = null; return; }
    const live = cpTab === 'detail' ? cpCur?.status === 'running' : cpTab === 'list' && cpList?.some((c) => c.status === 'running');
    if (live && !document.hidden && !cpBusy) cpRefresh();
  }, 3000);
}

window.campaignsView = () => {
  if (cpFor !== agent.id) { cpFor = agent.id; cpTab = 'list'; cpList = cpCur = cpRecs = cpOpt = cpSel = cpWiz = null; cpError = cpNote = ''; }
  cpRoot = h('div', { class: 'page' }, cpBody());
  if (cpTab !== 'new') cpRefresh();
  cpTick();
  return cpRoot;
};

function cpBody() {
  const tabs = h('div', { class: 'pills', role: 'group', 'aria-label': t('Qué ver') }, [['list', t('Campañas')], ['optouts', t('Bajas')]].map(([k, txt]) =>
    h('button', { type: 'button', class: 'pill', 'aria-pressed': String(k === 'optouts' ? cpTab === 'optouts' : cpTab !== 'optouts'), onclick: () => cpGo(k) }, txt)));
  return [
    h('div', { class: 'page-head' }, h('h1', {}, t('Campañas')),
      canEdit() && cpTab !== 'new' ? h('button', { class: 'btn', onclick: cpNew }, icon('plus'), t('Nueva campaña')) : null),
    tabs,
    cpError ? h('p', { class: 'notice warn', role: 'alert' }, cpError) : null,
    cpNote ? h('p', { class: 'notice', role: 'status' }, cpNote) : null,
    cpTab === 'new' ? cpWizard() : cpTab === 'detail' ? cpDetail() : cpTab === 'optouts' ? cpOptouts() : cpListView()];
}

// ---------- lista ----------
function cpListView() {
  return [
    cpHelp(t('Mandale un mensaje o hacele una llamada a una lista de personas: un recordatorio, una encuesta, un aviso. Cuando responden, sigue el flujo que elijas.')),
    !cpList ? cpHelp(t('Cargando…')) : cpList.length ? h('div', { class: 'panel', style: 'padding:0;gap:0;overflow:hidden' }, cpList.map((c) => {
      const s = c.stats || {};
      return h('button', { class: 'cp-row', type: 'button', onclick: () => cpGo('detail', c.id) },
        h('span', { class: 'stack', style: 'gap:2px;min-width:0' }, h('strong', {}, c.name),
          h('small', {}, [CP_CH[c.channel] || c.channel, t('{done} de {total} enviados', { done: cpDone(s), total: s.total || 0 }),
            s.replied ? t.plural(s.replied, '{n} respondió', '{n} respondieron') : null, s.failed ? t.plural(s.failed, '{n} falló', '{n} fallaron') : null,
            s.conversions ? t.plural(s.conversions, '{n} conversión', '{n} conversiones') : null].filter(Boolean).join(' · '))),
        cpBar(s), cpStatus(c));
    })) : h('div', { class: 'empty' }, icon('megaphone'), h('h2', {}, t('Todavía no hay campañas')),
      h('p', {}, t('Subí una planilla CSV con los números, elegí qué mandar y a qué ritmo.'))),
    cpLegal()];
}

// ---------- nueva campaña ----------
function cpNew() {
  cpWiz = { name: '', channel: 'whatsapp', template: '', flow: '', csv: '', file: '', preview: null, mapping: {}, when: 'now', at: '',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, rate: { count: 20, per: 'minute' }, quiet: true, qh: { start: '21:00', end: '09:00' }, conv: '', convValue: '' };
  cpGo('new');
}
async function cpCsv(e) {
  const f = e.target.files[0], w = cpWiz;
  if (!f) return;
  try {
    w.csv = await f.text(); w.file = f.name;
    w.preview = await cpApi('POST', '/campaigns/preview', { csv: w.csv });
    w.mapping = { ...w.preview.mapping }; cpError = '';
  } catch (err) { w.preview = null; w.csv = ''; cpError = t('No se pudo leer la planilla: {error}', { error: err.message }); }
  cpPaint();
}
function cpProblem(w) {
  const to = Object.values(w.mapping).filter((v) => v === 'to').length;
  return !w.name.trim() ? t('Ponele un nombre a la campaña.')
    : w.channel === 'whatsapp' && !w.template ? t('Elegí una plantilla aprobada: WhatsApp no deja escribir primero sin una.')
    : w.channel !== 'whatsapp' && !w.flow ? t('Elegí el flujo que corre con cada persona.')
    : !w.csv ? t('Subí la planilla con las personas.')
    : to !== 1 ? t('Elegí una sola columna como destinatario.')
    : w.when === 'later' && !w.at ? t('Elegí la fecha y hora de inicio.')
    : w.conv && !w.convValue ? t('Completá qué cuenta como éxito, o elegí «Nada».') : '';
}
async function cpCreate() {
  const w = cpWiz, problem = cpProblem(w);
  if (problem) { cpError = problem; cpPaint(); cpRoot?.querySelector('[role="alert"]')?.scrollIntoView({ block: 'nearest' }); return; }
  cpBusy = true; cpError = ''; cpPaint();
  try {
    const c = await cpApi('POST', '/campaigns', {
      name: w.name.trim(), channel: w.channel, flow: w.flow || null, template: w.channel === 'whatsapp' ? { name: w.template } : null,
      csv: w.csv, mapping: w.mapping, schedule: { at: w.when === 'later' ? w.at : null, timezone: w.timezone }, rate: w.rate,
      quiet_hours: w.quiet ? w.qh : null, conversion: w.conv ? { [w.conv]: w.conv === 'csat' ? Number(w.convValue) : w.convValue } : null });
    const im = c.imported || {};
    cpBusy = false; cpWiz = null;
    cpGo('detail', c.id);
    cpCur = c;
    cpNote = t('Campaña creada en borrador. Cargadas: {added}. Repetidas: {duplicates}. Destinatario inválido: {invalid}. Dadas de baja: {opted_out}. Revisala e iniciala cuando quieras.',
      { added: im.added ?? 0, duplicates: im.duplicates ?? 0, invalid: im.invalid ?? 0, opted_out: im.opted_out ?? 0 });
    cpPaint();
  } catch (e) { cpBusy = false; cpError = e.message; cpPaint(); }
}
function cpWizard() {
  const w = cpWiz, p = w.preview;
  const step = (n, title, ...kids) => h('section', { class: 'panel' }, h('h2', {}, n + '. ' + title), kids);
  const val = (k) => (e) => { w[k] = e.target.value; };
  const tpls = agent.channels?.whatsapp?.templates || [], tpl = tpls.find((x) => x.name === w.template);
  const tz = Intl.supportedValuesOf?.('timeZone') || [];
  const toCount = Object.values(w.mapping).filter((v) => v === 'to').length;
  return [
    cpLegal(),
    step(1, t('Nombre y canal'),
      lab(t('Nombre de la campaña'), h('input', { value: w.name, oninput: val('name'), placeholder: t('Por ejemplo: Recordatorio de turnos de marzo') })),
      lab(t('Canal'), pick(Object.entries(CP_CH), w.channel, (v) => { w.channel = v; cpPaint(); })),
      agent.channels?.[w.channel]?.enabled ? null : cpHelp(t('Este canal está apagado. Prendelo en Canales antes de iniciar la campaña.'), 'color:var(--warn)')),
    step(2, t('Qué se manda'),
      w.channel === 'whatsapp' ? [
        tpls.length ? lab(t('Plantilla aprobada'), pick([['', t('Elegí una plantilla…')], ...tpls.map((x) => [x.name, x.name + (x.language ? ' (' + x.language + ')' : '')])], w.template, (v) => { w.template = v; cpPaint(); }))
          : cpHelp(t('Todavía no cargaste plantillas. Agregalas en Canales → WhatsApp → Plantillas aprobadas.'), 'color:var(--warn)'),
        tpl?.params?.length ? cpHelp(t('Se completa con: {params}.', { params: tpl.params.map((x, i) => '{{' + (i + 1) + '}} = ' + x).join(', ') })) : null,
        cpHelp(t('WhatsApp solo deja escribirle primero a alguien con una plantilla aprobada por Meta. El flujo corre cuando la persona responde.'))]
        : cpHelp(w.channel === 'phone' ? t('Parla llama a cada número y, cuando atienden, corre el flujo.')
          : t('Parla le escribe a cada persona y corre el flujo enseguida. En Telegram solo se puede escribir a quien ya le habló a tu bot (el destinatario es su chat id).')),
      lab(w.channel === 'whatsapp' ? t('Flujo cuando responde (opcional)') : t('Flujo'),
        pick([['', w.channel === 'whatsapp' ? t('Ninguno: lo atiende el bot como siempre') : t('Elegí un flujo…')], ...agent.flows.map((f) => [f.name, f.name])], w.flow, (v) => { w.flow = v; }))),
    step(3, t('A quién'),
      cpHelp(t('Una planilla CSV con una fila por persona: una columna con el número (o el chat id en Telegram) y, si querés, otras con datos que se guardan en slots y se usan en la plantilla y el flujo.')),
      h('input', { type: 'file', accept: '.csv,text/csv,text/plain', 'aria-label': t('Planilla CSV'), onchange: cpCsv }),
      w.file ? cpHelp(t('Cargada: {name}', { name: w.file })) : null,
      p ? [h('strong', {}, t.plural(p.count, '{n} fila', '{n} filas')),
        h('div', { class: 'cp-scroll' }, h('table', { class: 'cp-table' },
          h('tr', {}, h('th', {}, t('Columna')), h('th', {}, t('Se usa como')), h('th', {}, t('Primeras filas'))),
          p.columns.map((col, i) => h('tr', {}, h('td', {}, h('strong', {}, col)),
            h('td', {}, pick([['', t('No usar')], ['to', t('Destinatario')], ...agent.slots.map((v) => [v.name, t('Slot {name}', { name: v.name })])], w.mapping[col] || '',
              (v) => { w.mapping[col] = v; cpPaint(); }, t('Uso de la columna {name}', { name: col }))),
            h('td', {}, p.rows.map((r) => r[i]).filter((x) => x != null && x !== '').join(' · ')))))),
        toCount === 1 ? null : cpHelp(t('Elegí una sola columna como destinatario.'), 'color:var(--warn)')] : null,
      cpHelp(t('Las personas que se dieron de baja no se cargan. Los números van con código de país, por ejemplo +5491112345678.'), 'font-size:13px')),
    step(4, t('Cuándo y a qué ritmo'),
      h('div', { class: 'row', style: 'align-items:flex-end' },
        lab(t('Empieza'), pick([['now', t('Apenas la inicies')], ['later', t('En una fecha y hora')]], w.when, (v) => { w.when = v; cpPaint(); })),
        w.when === 'later' ? lab(t('Fecha y hora'), h('input', { type: 'datetime-local', value: w.at, oninput: val('at') })) : null,
        lab(t('Zona horaria'), h('input', { value: w.timezone, list: 'cp-tz', oninput: val('timezone'), spellcheck: 'false' })),
        h('datalist', { id: 'cp-tz' }, tz.map((z) => h('option', { value: z })))),
      h('div', { class: 'row', style: 'align-items:flex-end' },
        lab(t('Cuántos'), h('input', { type: 'number', min: 1, max: 1000, value: w.rate.count, style: 'width:100px', oninput: (e) => { w.rate.count = Math.max(1, parseInt(e.target.value) || 1); } })),
        lab(t('Por'), pick([['second', t('segundo')], ['minute', t('minuto')]], w.rate.per, (v) => { w.rate.per = v; }))),
      cpHelp(t('Mensajes o llamadas por segundo o por minuto. Ir despacio cuida la reputación del número.'), 'font-size:13px'),
      h('label', { class: 'toggle' }, h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: w.quiet, onchange: (e) => { w.quiet = e.target.checked; cpPaint(); } }),
        t('No mandar en horario de silencio')),
      w.quiet ? [h('div', { class: 'row' },
        lab(t('Desde'), h('input', { type: 'time', value: w.qh.start, oninput: (e) => { w.qh.start = e.target.value; } })),
        lab(t('Hasta'), h('input', { type: 'time', value: w.qh.end, oninput: (e) => { w.qh.end = e.target.value; } }))),
        cpHelp(t('En la zona horaria de arriba. Lo que cae en ese horario espera a que termine.'), 'font-size:13px')] : null),
    step(5, t('Qué cuenta como éxito (opcional)'),
      h('div', { class: 'row' },
        pick([['', t('Nada, solo medir las respuestas')], ['classification', t('Una clasificación')], ['intent', t('Una intención')], ['csat', t('Una nota de satisfacción')]], w.conv,
          (v) => { w.conv = v; w.convValue = v === 'csat' ? '4' : ''; cpPaint(); }, t('Qué cuenta como éxito')),
        w.conv === 'classification' ? pick([['', t('Elegí una clasificación…')], ...agent.classifications.map((c) => [c.name, c.name])], w.convValue, (v) => { w.convValue = v; }, t('Clasificación')) : null,
        w.conv === 'intent' ? pick([['', t('Elegí una intención…')], ...agent.intents.map((i) => [i.name, i.name])], w.convValue, (v) => { w.convValue = v; }, t('Intención')) : null,
        w.conv === 'csat' ? [t('de al menos'), h('input', { type: 'number', min: 1, max: 5, value: w.convValue, style: 'width:80px', 'aria-label': t('Nota mínima'), oninput: val('convValue') })] : null),
      cpHelp(t('Las conversaciones que llegan a esto suman en «Conversiones».'), 'font-size:13px')),
    h('div', { class: 'row' },
      h('button', { class: 'btn', disabled: cpBusy, onclick: cpCreate }, cpBusy ? t('Creando…') : t('Crear campaña')),
      h('button', { class: 'btn quiet', onclick: () => { cpWiz = null; cpGo('list'); } }, t('Cancelar'))),
    cpHelp(t('Se crea en borrador: ves cuántas personas quedaron cargadas y después la iniciás.'), 'font-size:13px')];
}

// ---------- detalle ----------
async function cpAct(what) {
  cpBusy = true; cpPaint();
  try { cpCur = await cpApi('POST', '/campaigns/' + cpSel + '/' + what); cpError = ''; } catch (e) { cpError = e.message; }
  cpBusy = false; cpRefresh();
}
const cpOpenSession = (id) => { svSel = id; svQuery = ''; section = 'sessions'; render(); $('#center').scrollTop = 0; };   // svSel, svQuery: /static/sessions.js
function cpDetail() {
  const c = cpCur;
  if (!c) return cpHelp(t('Cargando…'));
  const s = c.stats || {}, st = c.status, r = cpRecs, total = r?.total || 0;
  const tile = (label, n, cls) => h('div', { class: 'rp-stat ' + (cls || '') }, h('small', {}, label), h('b', {}, n ?? 0));
  const btn = (label, onclick, cls) => h('button', { class: 'btn small ' + (cls || ''), disabled: cpBusy, onclick }, label);
  const sure = (title, text, cta, what) => () => confirmBox(title, text, cta, () => cpAct(what));
  const conv = c.conversion || {};
  const info = [CP_CH[c.channel] || c.channel,
    c.template ? t('plantilla «{name}»', { name: c.template.name }) : null, c.flow ? t('flujo «{name}»', { name: c.flow }) : null,
    c.schedule?.at ? t('empieza el {when} ({tz})', { when: cpWhen(c.schedule.at), tz: c.schedule.timezone || '' }) : null,
    c.rate ? t('{count} por {per}', { count: c.rate.count, per: c.rate.per === 'second' ? t('segundo') : t('minuto') }) : null,
    c.quiet_hours ? t('no manda de {start} a {end}', c.quiet_hours) : null,
    conv.classification ? t('éxito: clasificada como «{name}»', { name: conv.classification }) : conv.intent ? t('éxito: intención «{name}»', { name: conv.intent })
      : conv.csat ? t('éxito: nota de {n} o más', { n: conv.csat }) : null].filter(Boolean).join(' · ');
  const remove = () => confirmBox(t('Borrar la campaña'), t('Se borra «{name}» con sus resultados. No se puede deshacer.', { name: c.name }), t('Borrar campaña'), async () => {
    try { await cpApi('DELETE', '/campaigns/' + c.id); cpGo('list'); } catch (e) { cpError = e.message; cpPaint(); }
  });
  const exp = h('a', { class: 'btn quiet small', href: '/api/agents/' + encodeURIComponent(agent.id) + '/campaigns/' + encodeURIComponent(c.id) + '/export', download: '', style: 'text-decoration:none' }, icon('down'), t('Exportar CSV'));
  const page = (d) => () => { cpOffset = Math.max(0, cpOffset + d); cpRefresh(); };
  return [
    h('div', {}, h('button', { class: 'link', onclick: () => cpGo('list') }, t('Volver a las campañas'))),
    h('div', { class: 'row' }, h('h2', { style: 'font:700 22px var(--display);overflow-wrap:anywhere' }, c.name), cpStatus(c)),
    cpHelp(info),
    h('div', { class: 'stack' }, cpBar(s), h('small', { class: 'help' }, t('{done} de {total} procesados', { done: cpDone(s), total: s.total || 0 }))),
    h('div', { class: 'rp-stats' }, tile(t('Personas'), s.total), tile(t('Enviados'), s.sent), tile(t('Entregados'), s.delivered), tile(t('Leídos'), s.read),
      tile(t('Respondieron'), s.replied, s.replied ? 'good' : ''), tile(t('Fallaron'), s.failed, s.failed ? 'warn' : ''), tile(t('Se dieron de baja'), s.opted_out),
      tile(t('Conversiones'), s.conversions, s.conversions ? 'good' : '')),
    h('div', { class: 'row' }, canEdit() ? [
      st === 'draft' ? btn(t('Iniciar'), sure(t('Iniciar la campaña'), t.plural(s.total || 0, 'Se empieza a mandar a {n} persona, de verdad.', 'Se empieza a mandar a {n} personas, de verdad.'), t('Iniciar'), 'start')) : null,
      st === 'running' ? btn(t('Pausar'), () => cpAct('pause'), 'quiet') : null,
      st === 'paused' ? btn(t('Seguir'), () => cpAct('resume')) : null,
      st === 'running' || st === 'paused' ? btn(t('Cancelar campaña'), sure(t('Cancelar la campaña'), t('A los que todavía no se les mandó no se les manda. No se puede retomar.'), t('Cancelar campaña'), 'cancel'), 'quiet') : null,
      st !== 'running' ? btn(t('Borrar'), remove, 'danger') : null] : null, exp),
    h('section', { class: 'panel' },
      h('div', { class: 'row' }, h('h2', { class: 'grow' }, t('Resultados')),
        pick([['', t('Todos los estados')], ...Object.entries(CP_REC)], cpFilter, (v) => { cpFilter = v; cpOffset = 0; cpRefresh(); }, t('Estado'))),
      !r ? cpHelp(t('Cargando…')) : !r.recipients.length ? cpHelp(t('No hay personas con ese estado.')) : h('div', { class: 'cp-scroll' }, h('table', { class: 'cp-table' },
        h('tr', {}, [t('Destinatario'), t('Estado'), t('Datos'), t('Último cambio'), ''].map((x) => h('th', {}, x))),
        r.recipients.map((x) => h('tr', {},
          h('td', {}, x.to),
          h('td', { title: x.attempts ? t.plural(x.attempts, '{n} intento', '{n} intentos') : null }, CP_REC[x.status] || x.status,
            x.error ? h('small', { style: 'display:block;color:var(--warn)' }, x.error) : null),
          h('td', {}, Object.entries(x.data || {}).map(([k, v]) => k + ': ' + v).join(' · ')),
          h('td', { style: 'white-space:nowrap' }, cpWhen(x.updated)),
          h('td', {}, x.sessionId ? h('button', { class: 'link', onclick: () => cpOpenSession(x.sessionId) }, t('Ver conversación')) : null))))),
      total > 50 ? h('div', { class: 'row' },
        h('button', { class: 'btn quiet small', disabled: !cpOffset, onclick: page(-50) }, t('Anteriores')),
        h('span', { class: 'help' }, t('{from} a {to} de {total}', { from: cpOffset + 1, to: Math.min(cpOffset + 50, total), total })),
        h('button', { class: 'btn quiet small', disabled: cpOffset + 50 >= total, onclick: page(50) }, t('Siguientes'))) : null)];
}

// ---------- bajas (opt-outs) ----------
async function cpOptCall(method, address) {
  try { cpOpt = (await cpApi(method, '/optouts', { address })).optouts; cpError = ''; } catch (e) { cpError = e.message; }
  cpPaint();
}
function cpOptouts() {
  const kw = agent.outbound?.optout_keywords || {};
  const add = h('input', { class: 'grow', placeholder: '+5491112345678', 'aria-label': t('Número o chat id'), spellcheck: 'false' });
  const setKw = (l) => (e) => {
    const k = ((agent.outbound ||= {}).optout_keywords ||= {}), list = e.target.value.split(',').map((x) => x.trim()).filter(Boolean);
    if (list.length) k[l] = list; else delete k[l];
    touch();
  };
  return [
    cpHelp(t('Las personas que pidieron no recibir más mensajes: ninguna campaña ni recordatorio les vuelve a escribir. Se suman solas cuando alguien responde con una palabra de baja.')),
    canEdit() ? h('form', { class: 'row', onsubmit: (e) => { e.preventDefault(); if (add.value.trim()) cpOptCall('POST', add.value.trim()); } },
      add, h('button', { class: 'btn small' }, t('Agregar a mano'))) : null,
    !cpOpt ? cpHelp(t('Cargando…')) : !cpOpt.length ? h('div', { class: 'empty' }, t('Nadie se dio de baja todavía.'))
      : h('div', { class: 'panel cp-scroll' }, h('table', { class: 'cp-table' },
        h('tr', {}, [t('Número o chat id'), t('Canal'), t('Palabra'), t('Cuándo'), ''].map((x) => h('th', {}, x))),
        cpOpt.map((o) => h('tr', {}, h('td', {}, o.address), h('td', {}, CP_CH[o.channel] || o.channel || '—'), h('td', {}, o.keyword || t('a mano')), h('td', {}, cpWhen(o.at)),
          h('td', {}, canEdit() ? iconBtn('trash', t('Sacar de las bajas'), () => cpOptCall('DELETE', o.address)) : null))))),
    h('section', { class: 'panel' }, h('h2', {}, t('Palabras de baja')),
      cpHelp(t('Si alguien responde solo con una de estas palabras, queda dado de baja y el bot se lo confirma. Separalas con comas; vacío usa las de siempre.'), 'font-size:14px'),
      ['es', 'en', 'pt'].map((l) => lab(LANGS[l], h('input', { value: (kw[l] || []).join(', '), placeholder: CP_KW[l], disabled: !canEdit(), onchange: setKw(l) })))),
    cpLegal()];
}
