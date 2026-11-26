// Bandeja (charlas que atiende una persona) y Para enseñar (lo que el bot no entendió).
let ibSel = null, ibTimer = null;

document.head.append(h('style', {}, `
  .ib { max-width: 1040px; display: flex; flex-direction: column; gap: 18px; }
  .ib-grid { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 24px; align-items: start; }
  .ib-list { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .ib-item { text-align: left; padding: 10px 12px; border-radius: 10px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .ib-item:hover { background: var(--surface); }
  .ib-item[aria-current="true"] { background: var(--surface); box-shadow: inset 3px 0 0 var(--brand); }
  .ib-item strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ib-item small, .ib-who { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
  .ib-log { display: flex; flex-direction: column; gap: 6px; max-height: 56vh; overflow-y: auto; overscroll-behavior: contain; padding: 2px; }
  .ib-log .msg.human { align-self: flex-start; background: var(--brand-soft); color: var(--ink); border: 1px solid var(--brand); border-bottom-left-radius: 4px; }
  .ib-who { margin-top: -2px; }
  .ib-who.user { align-self: flex-end; }
  .ib-reply { display: flex; gap: 8px; align-items: flex-end; }
  .ib-reply textarea { flex: 1; min-height: 44px; resize: vertical; }
  .ib-group { gap: 10px; }
  .ib-group h2 { font: 700 18px/1.3 var(--display); overflow-wrap: anywhere; }
  .ib-ex { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: 14px; }
  .ib-ex li { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .ib-ex q { color: var(--ink); overflow-wrap: anywhere; }
  .ib-ex small { color: var(--muted); }
  .ib-teach { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .ib-teach select { min-width: 180px; }
  @media (max-width: 900px) { .ib-grid { grid-template-columns: 1fr; } }
`));

const ibTime = (iso) => (iso || '').slice(11, 16);
const ibDate = (iso) => iso ? iso.slice(8, 10) + '/' + iso.slice(5, 7) + ' ' + ibTime(iso) : '';
async function ibSession(sid) {          // la conversación completa (misma ruta que usa Conversaciones)
  const r = await fetch('/api/v1/bots/' + encodeURIComponent(agent.id) + '/sessions/' + encodeURIComponent(sid));
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || t('el servidor respondió {status}', { status: r.status }));
  return data;
}
function ibOpenInSessions(sid) {         // abre esa charla en Conversaciones (estado de /static/sessions.js)
  try { svSel = sid; svQuery = ''; svChannel = 'all'; svClass = 'all'; svEnv = 'all'; } catch { /* sessions.js no cargó */ }
  section = 'sessions'; render(); $('#center').scrollTop = 0;
}

// ---------- Bandeja ----------
window.inboxView = () => {
  clearInterval(ibTimer);
  const myAgent = agent;
  const list = h('div', { class: 'ib-list', role: 'list', 'aria-label': t('Conversaciones con una persona') });
  const detail = h('div', { class: 'panel', 'aria-live': 'polite' });
  const body = h('div', {}, h('div', { class: 'empty', role: 'status' }, t('Cargando la bandeja…')));
  const root = h('div', { class: 'ib' },
    h('div', { class: 'page-head' }, h('h1', {}, t('Bandeja')), h('button', { class: 'btn quiet small', onclick: () => refresh() }, icon('redo'), t('Actualizar'))),
    h('p', { class: 'help' }, t('Las conversaciones que el bot pasó a una persona. Desde acá las leés, contestás y, cuando terminás, se las devolvés al bot.')),
    body);
  let items = [], openSig = '';
  const log = h('div', { class: 'ib-log' });
  const text = h('textarea', { placeholder: t('Escribí tu respuesta…'), 'aria-label': t('Tu respuesta'), rows: 2,
    onkeydown: (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } } });
  const head = h('div', { class: 'sv-head row', style: 'flex-wrap:wrap;row-gap:8px' });
  const note = h('p', { class: 'help', role: 'status', style: 'font-size:13px' });

  const act = async (what, payload) => {
    note.textContent = '';
    try { await api('POST', '/' + agent.id + '/sessions/' + encodeURIComponent(ibSel) + '/' + what, payload); await refresh(); return true; }
    catch (e) { note.textContent = t('No se pudo: {error}.', { error: e.message }); return false; }
  };
  async function send() {
    const t = text.value.trim();
    if (!t) return;
    if (await act('reply', { text: t })) text.value = '';
  }

  function drawList() {
    if (!items.length) {
      ibSel = null;
      body.replaceChildren(h('div', { class: 'empty' }, icon('inbox'), h('strong', {}, t('No hay conversaciones esperando a una persona')),
        h('p', { class: 'help' }, t('Una conversación llega acá cuando un flujo usa el paso «Pasar a una persona», o cuando el cliente pide hablar con alguien (por ejemplo «quiero hablar con una persona»). Mientras tanto, el bot no contesta esa charla.'))));
      return;
    }
    if (!items.some((s) => s.sessionId === ibSel)) ibSel = items[0].sessionId;
    list.replaceChildren(...items.map((s) => h('div', { role: 'listitem' }, h('button', {
      class: 'ib-item', 'aria-current': String(s.sessionId === ibSel),
      onclick: () => { ibSel = s.sessionId; openSig = ''; delete log.dataset.once; drawList(); drawDetail(); },
    }, h('strong', {}, s.sessionId),
      h('span', { class: 'sv-preview' }, s.last_message ? t('«{text}»', { text: s.last_message }) : ''),
      h('small', {}, [s.handoff?.reason ? t('Motivo: {reason}', { reason: s.handoff.reason }) : null, s.handoff?.by ? t('Atiende {name}', { name: s.handoff.by }) : t('Sin tomar'), ibDate(s.handoff?.since || s.updated)].filter(Boolean).join(' · '))))));
    if (!body.contains(list)) body.replaceChildren(h('div', { class: 'ib-grid' }, list, detail));
  }

  async function drawDetail() {
    const id = ibSel;
    if (!id) return;
    try {
      const s = await ibSession(id);
      if (id !== ibSel) return;
      const sig = JSON.stringify([s.history?.length, s.handoff]);
      if (sig === openSig) return;                       // nada nuevo: no tocar lo que se está escribiendo
      openSig = sig;
      const item = items.find((x) => x.sessionId === id) || {};
      const ho = s.handoff || item.handoff || {};
      const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
      log.replaceChildren(...(s.history || []).flatMap((m) => {
        if (m.from === 'user') return [h('div', { class: 'msg user' }, m.text), h('div', { class: 'ib-who user' }, t('Cliente') + ' · ' + ibTime(m.at))];
        if (m.from === 'human') return [h('div', { class: 'msg human' }, m.text), h('div', { class: 'ib-who' }, (m.by || t('Persona')) + ' · ' + ibTime(m.at))];
        if (m.from === 'bot') return [h('div', { class: 'msg bot' }, m.file && m.text === m.file.name ? null : m.text, m.file ? window.fileCard(m.file) : null), h('div', { class: 'ib-who' }, t('Bot') + ' · ' + ibTime(m.at))];
        return h('div', { class: 'msg event' }, m.text + ' · ' + ibTime(m.at));
      }));
      if (stick || !log.dataset.once) { log.scrollTop = log.scrollHeight; log.dataset.once = '1'; }
      head.replaceChildren(h('div', { class: 'grow stack', style: 'gap:2px;min-width:min(220px,100%)' }, h('h2', {}, id),
        h('span', { class: 'help', style: 'font-size:14px' }, [ho.reason ? t('Motivo: {reason}', { reason: ho.reason }) : null, ho.by ? t('La atiende {name}', { name: ho.by }) : t('Nadie la tomó todavía')].filter(Boolean).join(' · '))),
        ho.by ? null : h('button', { class: 'btn quiet small', onclick: () => act('take') }, icon('hand'), t('Tomar conversación')),
        h('button', { class: 'btn small', onclick: () => act('release') }, icon('back'), t('Devolver al bot')));
      const call = String(s.channel === 'phone');      // una llamada no tiene caja para escribir
      if (!detail.contains(log) || detail.dataset.call !== call) (detail.dataset.call = call, detail.replaceChildren(head, log, s.channel === 'phone'
        ? h('p', { class: 'help' }, t('Es una llamada: no se le puede escribir. Al tomarla, Parla la transfiere al número de «Transferir a una persona» (Canales → Teléfono) apenas la persona deje de hablar.'))
        : h('div', { class: 'ib-reply' }, text, h('button', { class: 'btn', onclick: send }, icon('arrow'), t('Enviar'))), note,
        h('button', { class: 'link', style: 'align-self:flex-start;font-size:13px', onclick: () => ibOpenInSessions(id) }, t('Ver en Conversaciones'))));
    } catch (e) {
      if (id === ibSel) detail.replaceChildren(h('div', { class: 'notice warn', role: 'alert' }, t('No se pudo abrir la conversación: {error}.', { error: e.message })));
    }
  }

  async function refresh() {
    try {
      const data = await api('GET', '/' + myAgent.id + '/inbox');
      if (agent !== myAgent || !root.isConnected) return;
      items = Array.isArray(data) ? data : data.sessions || data.conversations || data.inbox || [];
      drawList(); await drawDetail();
    } catch (e) {
      if (root.isConnected) body.replaceChildren(h('div', { class: 'notice warn', role: 'alert' }, t('No se pudo cargar la bandeja: {error}.', { error: e.message })));
    }
  }

  // se actualiza sola cada 3 s, solo mientras la sección está a la vista
  ibTimer = setInterval(() => { if (!root.isConnected || agent !== myAgent) clearInterval(ibTimer); else if (!document.hidden) refresh(); }, 3000);
  refresh();
  return root;
};

// ---------- Para enseñar ----------
window.improveView = () => {
  agent.ignored_phrases ||= [];
  const myAgent = agent;
  const intents = agent.intents.filter((i) => !i.name.startsWith('__'));
  const notice = h('div', { 'aria-live': 'polite' });
  const body = h('div', { class: 'stack', style: 'gap:14px' }, h('div', { class: 'empty', role: 'status' }, t('Buscando lo que el bot no entendió…')));
  const root = h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('h1', {}, t('Para enseñar')), h('button', { class: 'btn quiet small', onclick: () => render() }, icon('redo'), t('Actualizar'))),
    h('p', { class: 'help' }, t('Lo que la gente escribió y el bot no entendió, agrupado por frases parecidas. Enseñale a qué intención corresponde cada una, o ignorala si no hace falta.')),
    notice, body);

  const done = (msg, train) => notice.replaceChildren(h('div', { class: 'notice' }, icon('check'), h('span', { class: 'grow' }, msg),
    train ? h('button', { class: 'btn small', onclick: async () => { await trainNow(); notice.replaceChildren(); } }, icon('spark'), t('Entrenar ahora')) : null));

  function card(g, groups) {
    const texts = g.texts || [...new Set(g.examples.map((e) => e.text))];
    const choice = h('select', { 'aria-label': t('Intención') }, h('option', { value: '' }, t('Elegí una intención…')),
      intents.map((i) => h('option', { value: i.name }, i.name)));
    choice.value = intents.some((i) => i.name === g.suggested_intent) ? g.suggested_intent : '';
    const gone = () => { groups.splice(groups.indexOf(g), 1); draw(groups); };
    const teach = () => {
      const it = agent.intents.find((i) => i.name === choice.value);
      if (!it) { choice.focus(); return; }
      const have = new Set(it.examples.map((e) => e.trim().toLowerCase()));
      const fresh = texts.filter((t) => !have.has(t.trim().toLowerCase()));
      it.examples.push(...fresh);
      touch(); gone();
      done(t.plural(fresh.length, 'Listo: sumaste {n} frase a «{name}». Para que el bot lo aprenda hay que entrenarlo de nuevo.', 'Listo: sumaste {n} frases a «{name}». Para que el bot lo aprenda hay que entrenarlo de nuevo.', { name: it.name }), true);
    };
    const ignore = () => {
      agent.ignored_phrases.push(...texts.filter((t) => !agent.ignored_phrases.includes(t)));
      touch(); gone();
      done(t('Listo: no vamos a mostrarte más «{label}».', { label: g.label }));
    };
    return h('div', { class: 'panel ib-group' },
      h('div', { class: 'row' }, h('h2', { class: 'grow' }, t('«{text}»', { text: g.label })),
        h('span', { class: 'help', style: 'font-size:14px' }, t.plural(g.count, 'lo escribió {n} vez', 'lo escribieron {n} veces'))),
      h('ul', { class: 'ib-ex' }, g.examples.slice(0, 5).map((e) => h('li', {}, h('q', {}, e.text), h('small', {}, ibDate(e.at)),
        e.sessionId ? h('button', { class: 'link', style: 'font-size:13px', onclick: () => ibOpenInSessions(e.sessionId) }, t('Ver conversación')) : null))),
      g.examples.length > 5 ? h('small', { class: 'help' }, t('y {n} más', { n: g.count - 5 })) : null,
      intents.length ? h('div', { class: 'ib-teach' }, choice, h('button', { class: 'btn small', onclick: teach }, icon('lightbulb'), t('Enseñar')),
        h('button', { class: 'btn quiet small', onclick: ignore }, t('Ignorar')),
        g.suggested_intent && choice.value ? h('small', { class: 'help' }, t('Te sugerimos la que más se parece.')) : null)
        : h('p', { class: 'help', style: 'font-size:14px' }, t('Creá una intención primero para poder enseñarle esta frase.')));
  }

  function draw(groups) {
    body.replaceChildren(...(groups.length ? groups.map((g) => card(g, groups))
      : [h('div', { class: 'empty' }, icon('lightbulb'), h('strong', {}, t('No hay nada para enseñar')),
        h('p', { class: 'help' }, t('Cuando alguien escriba algo que el bot no entiende, va a aparecer acá para que le enseñes qué quiso decir.')))]));
  }

  (async () => {
    try {
      await saveNow();                    // así no vuelve a mostrar lo que se acaba de enseñar o ignorar
      const { groups } = await api('GET', '/' + myAgent.id + '/insights/unrecognized');
      if (agent === myAgent && root.isConnected) draw(groups || []);
    } catch (e) {
      body.replaceChildren(h('div', { class: 'notice warn', role: 'alert' }, t('No se pudo cargar: {error}.', { error: e.message }),
        h('button', { class: 'link', onclick: render }, t('Probar de nuevo'))));
    }
  })();
  return root;
};
