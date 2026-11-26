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
  login: t('Entró'), logout: t('Salió'), 'user.create': t('Creó un usuario'), 'user.update': t('Cambió un usuario'), 'user.role': t('Cambió el rol'),
  'user.delete': t('Borró un usuario'), 'key.create': t('Creó una clave de API'), 'key.revoke': t('Revocó una clave de API'),
  'agent.create': t('Creó el agente'), 'agent.import': t('Importó el agente'), 'agent.save': t('Editó el agente'), 'agent.delete': t('Borró el agente'),
  'agent.train': t('Entrenó'), 'agent.publish': t('Publicó'), 'agent.deploy': t('Pasó a un entorno'), 'agent.restore': t('Volvió a una versión'),
  'secret.set': t('Guardó un secreto'), 'secret.delete': t('Borró un secreto'), 'file.upload': t('Subió un archivo'), 'file.delete': t('Borró un archivo'),
  'channel.update': t('Cambió los canales'), 'channel.telegram': 'Telegram', 'inbox.take': t('Tomó una charla'), 'inbox.release': t('Devolvió una charla al bot'),
  'inbox.reply': t('Respondió en la Bandeja'), 'session.delete': t('Borró una conversación'),
};
window.auditPage = async () => {
  if (window.authEnabled !== false && window.me?.role !== 'owner') return home();   // solo el dueño (o sin usuarios): el enlace escondido tampoco abre
  if (typeof agent !== 'undefined' && agent) { await saveNow(); agent = null; }
  history.replaceState(null, '', '#/auditoria');              // F5 vuelve a esta pantalla
  const filters = { agent: '', user: '', since: '' };
  const list = h('div', {}, h('p', { class: 'help' }, t('Cargando…')));
  let names = {};
  const field = (key, label, input) => h('label', {}, label, input);
  const load = async () => {
    const qs = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString();
    try {
      const { entries } = await usApi('GET', '/api/audit' + (qs ? '?' + qs : ''));
      list.replaceChildren(entries.length ? h('div', { class: 'au-scroll' }, h('table', { class: 'au-table' },
        h('tr', {}, h('th', {}, t('Cuándo')), h('th', {}, t('Quién')), h('th', {}, t('Qué')), h('th', {}, t('Agente')), h('th', {}, t('Detalle'))),
        entries.map((e) => h('tr', {}, h('td', {}, e.at.replace('T', ' ')), h('td', {}, e.user || '—', e.role ? h('small', { class: 'help' }, ' ' + ((US_ROLES[e.role] || [e.role])[0])) : null),
          h('td', {}, AU_ACTIONS[e.action] || e.action), h('td', {}, e.agent_id ? names[e.agent_id] || h('code', {}, e.agent_id) : '—'), h('td', {}, e.detail || ''))))) :
        h('p', { class: 'help' }, t('No hay nada registrado con esos filtros.')));
    } catch (e) { list.replaceChildren(h('p', { class: 'notice warn' }, t('No pude traer la auditoría: {error}', { error: e.message }))); }
  };
  const agentPick = h('select', { onchange: (e) => { filters.agent = e.target.value; load(); } }, h('option', { value: '' }, t('Todos')));
  const app = $('#app');
  app.className = 'home';
  app.replaceChildren(
    h('header', { class: 'home-hero home-hero-sm' }, h('div', { class: 'home-in' },
      h('div', { class: 'home-top' }, h('button', { class: 'btn quiet home-back', onclick: () => home() }, icon('back'), t('Tus agentes')),
        h('div', { class: 'row' }, window.langSwitcher?.(), window.themeSwitcher?.(), h('span', { 'data-me-slot': '' }, window.userAvatar()))),
      h('h1', {}, t('Auditoría')),
      h('p', { class: 'home-lead' }, t('Quién cambió qué: agentes, publicaciones, secretos, usuarios, claves, canales, la Bandeja y cada intento de entrar. Nunca guarda contraseñas ni valores de secretos.')))),
    h('main', { class: 'home-in home-body' }, h('div', { class: 'us-body us-page' },
      h('div', { class: 'au-filters' },
        field('agent', t('Agente'), agentPick),
        field('user', t('Usuario'), h('input', { type: 'text', placeholder: t('Todos'), oninput: (e) => { filters.user = e.target.value.trim(); clearTimeout(load.t); load.t = setTimeout(load, 300); } })),
        field('since', t('Desde'), h('input', { type: 'date', onchange: (e) => { filters.since = e.target.value; load(); } }))),
      list)));
  try {
    const agents = await usApi('GET', '/api/agents');
    names = Object.fromEntries(agents.map((a) => [a.id, a.name]));
    agentPick.append(...agents.map((a) => h('option', { value: a.id }, a.name)));
  } catch {}
  load();
};
