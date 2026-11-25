// Auditoría (#/auditoria, solo el dueño): quién hizo qué. GET /api/audit, ver Handler.audit en parla/server.py.
document.head.append(h('style', {}, `
  .au-filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 12px 16px; }
  .au-filters label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--muted); }
  .au-scroll { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; }
  .au-table { border-collapse: collapse; width: 100%; font-size: 14px; }
  .au-table th { text-align: left; color: var(--muted); font-weight: 500; font-size: 13px; padding: 8px 12px; border-bottom: 1px solid var(--line); }
  .au-table td { padding: 8px 12px; border-bottom: 1px solid var(--line); vertical-align: top; overflow-wrap: anywhere; }
  .au-table tr:last-child td { border-bottom: 0; }
  .au-table td:first-child { white-space: nowrap; color: var(--muted); }
  .au-table code { font-size: 13px; }
`));
const AU_ACTIONS = {
  login: 'Entró', logout: 'Salió', 'user.create': 'Creó un usuario', 'user.update': 'Cambió un usuario', 'user.role': 'Cambió el rol',
  'user.delete': 'Borró un usuario', 'key.create': 'Creó una clave de API', 'key.revoke': 'Revocó una clave de API',
  'agent.create': 'Creó el agente', 'agent.import': 'Importó el agente', 'agent.save': 'Editó el agente', 'agent.delete': 'Borró el agente',
  'agent.train': 'Entrenó', 'agent.publish': 'Publicó', 'agent.deploy': 'Pasó a un entorno', 'agent.restore': 'Volvió a una versión',
  'secret.set': 'Guardó un secreto', 'secret.delete': 'Borró un secreto', 'file.upload': 'Subió un archivo', 'file.delete': 'Borró un archivo',
  'channel.update': 'Cambió los canales', 'channel.telegram': 'Telegram', 'inbox.take': 'Tomó una charla', 'inbox.release': 'Devolvió una charla al bot',
  'inbox.reply': 'Respondió en la Bandeja', 'session.delete': 'Borró una conversación',
};
window.auditPage = async () => {
  if (typeof agent !== 'undefined' && agent) { await saveNow(); agent = null; }
  history.replaceState(null, '', '#/auditoria');              // F5 vuelve a esta pantalla
  const filters = { agent: '', user: '', since: '' };
  const list = h('div', {}, h('p', { class: 'help' }, 'Cargando…'));
  let names = {};
  const field = (key, label, input) => h('label', {}, label, input);
  const load = async () => {
    const qs = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString();
    try {
      const { entries } = await usApi('GET', '/api/audit' + (qs ? '?' + qs : ''));
      list.replaceChildren(entries.length ? h('div', { class: 'au-scroll' }, h('table', { class: 'au-table' },
        h('tr', {}, h('th', {}, 'Cuándo'), h('th', {}, 'Quién'), h('th', {}, 'Qué'), h('th', {}, 'Agente'), h('th', {}, 'Detalle')),
        entries.map((e) => h('tr', {}, h('td', {}, e.at.replace('T', ' ')), h('td', {}, e.user || '—', e.role ? h('small', { class: 'help' }, ' ' + ((US_ROLES[e.role] || [e.role])[0])) : null),
          h('td', {}, AU_ACTIONS[e.action] || e.action), h('td', {}, e.agent_id ? names[e.agent_id] || h('code', {}, e.agent_id) : '—'), h('td', {}, e.detail || ''))))) :
        h('p', { class: 'help' }, 'No hay nada registrado con esos filtros.'));
    } catch (e) { list.replaceChildren(h('p', { class: 'notice warn' }, 'No pude traer la auditoría: ' + e.message)); }
  };
  const agentPick = h('select', { onchange: (e) => { filters.agent = e.target.value; load(); } }, h('option', { value: '' }, 'Todos'));
  const app = $('#app');
  app.className = 'home';
  app.replaceChildren(
    h('header', { class: 'home-hero home-hero-sm' }, h('div', { class: 'home-in' },
      h('div', { class: 'home-top' }, h('button', { class: 'btn quiet home-back', onclick: () => home() }, icon('back'), 'Tus agentes'),
        h('div', { class: 'row' }, window.themeSwitcher?.(), h('span', { 'data-me-slot': '' }, window.userAvatar()))),
      h('h1', {}, 'Auditoría'),
      h('p', { class: 'home-lead' }, 'Quién cambió qué: agentes, publicaciones, secretos, usuarios, claves, canales, la Bandeja y cada intento de entrar. Nunca guarda contraseñas ni valores de secretos.'))),
    h('main', { class: 'home-in home-body' }, h('div', { class: 'us-body us-page' },
      h('div', { class: 'au-filters' },
        field('agent', 'Agente', agentPick),
        field('user', 'Usuario', h('input', { type: 'text', placeholder: 'Todos', oninput: (e) => { filters.user = e.target.value.trim(); clearTimeout(load.t); load.t = setTimeout(load, 300); } })),
        field('since', 'Desde', h('input', { type: 'date', onchange: (e) => { filters.since = e.target.value; load(); } }))),
      list)));
  try {
    const agents = await usApi('GET', '/api/agents');
    names = Object.fromEntries(agents.map((a) => [a.id, a.name]));
    agentPick.append(...agents.map((a) => h('option', { value: a.id }, a.name)));
  } catch {}
  load();
};
