// Conectar con IA: registra el servidor MCP de Parla en Claude Code, Codex, Claude Desktop o Cursor (ver connect.py).
document.head.append(h('style', {}, `
  dialog.cx { width: min(580px, calc(100vw - 24px)); padding: 22px; }
  .cx-body { display: flex; flex-direction: column; gap: 14px; }
  .cx-head { display: flex; align-items: flex-start; gap: 12px; justify-content: space-between; }
  .cx-list { display: flex; flex-direction: column; gap: 10px; }
  .cx-client { border: 1px solid var(--line); border-radius: 14px; padding: 14px; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
  .cx-top { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .cx-top strong { font: 700 17px var(--display); flex: 1; min-width: 120px; }
  .cx-state { font-size: 13px; color: var(--muted); display: inline-flex; align-items: center; gap: 5px; }
  .cx-state.on { color: var(--ok); font-weight: 600; }
  .cx-msg:empty { display: none; }
  .cx-msg { overflow-wrap: anywhere; }
  .cx-client details summary { cursor: pointer; color: var(--muted); font-size: 14px; }
  .cx-client details[open] summary { margin-bottom: 8px; }
  .cx-manual { display: flex; flex-direction: column; gap: 8px; font-size: 14px; }
  .cx-manual p { overflow-wrap: anywhere; }
  .cx-manual pre { margin: 0; background: var(--soft); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; font-size: 12.5px; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow: auto; }
  .cx-manual .btn { align-self: flex-start; }
  @media (max-width: 760px) { .top { flex-wrap: wrap; padding-top: 8px; padding-bottom: 8px; } }
`));

async function cxApi(method, path, body) {
  const r = await fetch('/api/connect' + path, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.status);
  return data;
}

function cxManual(c) {
  const pre = h('pre', {}, c.manual.text), done = h('span', { class: 'help', role: 'status' });
  const copy = async () => {
    try { await navigator.clipboard.writeText(c.manual.text); done.textContent = t('Copiado'); }
    catch { getSelection().selectAllChildren(pre); done.textContent = t('Quedó seleccionado: copialo con Ctrl+C (o ⌘C)'); }
  };
  return h('details', { open: !c.installed },
    h('summary', {}, t('Hacerlo a mano')),
    h('div', { class: 'cx-manual' }, h('p', { class: 'help' }, c.manual.how), pre,
      h('div', { class: 'row' }, h('button', { class: 'btn quiet small', type: 'button', onclick: copy }, t('Copiar')), done)));
}

function cxClient(c, redraw) {
  const msg = h('div', { class: 'cx-msg', role: 'status' });
  const act = async (button, path, verb) => {
    button.disabled = true; button.textContent = verb;
    try {
      const r = await cxApi('POST', path, { client: c.id });
      await redraw(c.id, r.message, false);
    } catch (e) { await redraw(c.id, t('No se pudo: {error}', { error: e.message }), true); }
  };
  const btn = c.connected
    ? h('button', { class: 'btn quiet small', type: 'button', onclick: (e) => act(e.currentTarget, '/remove', t('Desconectando…')) }, t('Desconectar'))
    : h('button', { class: 'btn small', type: 'button', onclick: (e) => act(e.currentTarget, '', t('Conectando…')) }, t('Conectar'));
  const state = c.connected ? h('span', { class: 'cx-state on' }, icon('check'), t('Ya conectado'))
    : h('span', { class: 'cx-state' }, c.installed ? t('Lo encontré en esta compu') : t('No lo encontré en esta compu'));
  return { el: h('div', { class: 'cx-client' }, h('div', { class: 'cx-top' }, h('strong', {}, c.name), state, btn), msg, cxManual(c)), msg };
}

window.connectView = async () => {
  const list = h('div', { class: 'cx-list' }, h('p', { class: 'help' }, t('Buscando tus asistentes…')));
  const d = h('dialog', { class: 'cx', 'aria-labelledby': 'cx-title' }, h('div', { class: 'cx-body' },
    h('div', { class: 'cx-head' }, h('h2', { id: 'cx-title' }, t('Conectar con IA')), iconBtn('x', t('Cerrar'), () => d.close())),
    h('p', { class: 'help' }, t('Conectá Parla con tu asistente de IA y pedile que te arme bots. Tocás «Conectar» una vez y después le escribís, por ejemplo: «armame un bot que tome pedidos de pizza».')),
    list,
    h('p', { class: 'help', style: 'font-size:13px' }, t('Parla tiene que estar abierto en esta compu mientras el asistente trabaja. Antes de cambiar la configuración de un asistente guardamos una copia (termina en .parla-backup).'))));
  d.onclose = () => d.remove();
  document.body.append(d); d.showModal();
  const draw = async (id, text, bad) => {
    try {
      const rows = (await cxApi('GET', '')).map((c) => ({ c, ...cxClient(c, draw) }));
      list.replaceChildren(...rows.map((r) => r.el));
      const row = rows.find((r) => r.c.id === id);
      if (row) { row.msg.className = 'cx-msg notice' + (bad ? ' warn' : ''); row.msg.textContent = text; }
    } catch (e) { list.replaceChildren(h('p', { class: 'notice warn' }, t('No pude ver tus asistentes: {error}', { error: e.message }))); }
  };
  draw();
};
