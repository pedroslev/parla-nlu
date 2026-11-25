// Usuarios: iniciar sesión, el botón «Usuarios» de la pantalla de inicio y la administración (solo el dueño). Ver auth.py.
document.head.append(h('style', {}, `
  dialog.us { width: min(600px, calc(100vw - 24px)); padding: 22px; }
  .us-body { display: flex; flex-direction: column; gap: 14px; }
  .us-head { display: flex; align-items: flex-start; gap: 12px; justify-content: space-between; }
  .us-user { border: 1px solid var(--line); border-radius: 14px; padding: 14px; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
  .us-user strong { font: 700 17px var(--display); flex: 1; min-width: 120px; overflow-wrap: anywhere; }
  .us-user details summary { cursor: pointer; color: var(--muted); font-size: 14px; }
  .us-user details[open] summary { margin-bottom: 8px; }
  .us-key { display: flex; align-items: center; gap: 8px; font-size: 14px; padding: 4px 0; border-bottom: 1px solid var(--line); }
  .us-key:last-child { border-bottom: 0; }
  .us-secret { font-family: ui-monospace, monospace; font-size: 13px; background: var(--soft); border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; overflow-wrap: anywhere; }
  .us-roles { display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
  .us-roles label { display: flex; gap: 8px; align-items: flex-start; cursor: pointer; }
  .us-roles small { display: block; color: var(--muted); }
  .us-msg:empty { display: none; }
  .us-bots { padding-left: 26px; max-height: 220px; overflow-y: auto; }
  .us-user [hidden] { display: none; }
`));

const US_ROLES = {
  owner: ['Dueño', 'Puede hacer todo, incluso crear y borrar usuarios.'],
  editor: ['Editor', 'Arma y cambia los bots, prueba y publica. No maneja usuarios.'],
  analyst: ['Analista', 'Solo mira: conversaciones, reportes y bandeja. No puede cambiar nada.'],
  agent: ['Atención', 'Solo la Bandeja: lee y responde las charlas que el bot pasa a una persona.'],
};
window.me = null;
window.authEnabled = false;

async function usApi(method, path, body) {     // fuera de /api/agents: fetch directo
  const r = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.status);
  return data;
}
const usMsg = () => h('p', { class: 'us-msg notice warn', role: 'alert' });
const usFail = (box, e) => { box.textContent = e.message; };

let usLogin = null;

// Pantalla de entrada: a la izquierda, Parla haciendo lo suyo (entiende «dame una de muzza»); a la derecha, entrar.
document.head.append(h('style', {}, `
  dialog.lg { width: 100vw; height: 100dvh; max-width: none; max-height: none; margin: 0; padding: 0; border: 0; border-radius: 0;
    background: var(--bg); color: var(--ink); }
  dialog.lg[open] { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(360px, 1fr); }
  dialog.lg::backdrop { background: var(--bg); }
  .lg-stage { position: relative; overflow: hidden; color: #fff; padding: clamp(28px, 5vw, 64px); display: flex; flex-direction: column;
    justify-content: space-between; gap: 32px;
    background: radial-gradient(120% 90% at 0% 0%, #6A4CF5 0%, transparent 55%), radial-gradient(90% 80% at 100% 100%, #1FB8C9 0%, transparent 50%),
                radial-gradient(70% 60% at 85% 10%, #FF7AB8 0%, transparent 45%), #2A36B8; }
  .lg-stage::after { content: ""; position: absolute; inset: 0; pointer-events: none; opacity: .5;
    background-image: radial-gradient(rgba(255,255,255,.18) 1px, transparent 1.4px); background-size: 22px 22px;
    mask-image: linear-gradient(160deg, #000 10%, transparent 70%); }
  .lg-mark { font: 800 clamp(56px, 8vw, 104px)/.9 var(--display); letter-spacing: -.045em; position: relative; z-index: 1; }
  .lg-mark span { color: #FFD166; }
  .lg-lead { font: 500 clamp(18px, 1.6vw, 22px)/1.35 var(--display); max-width: 30ch; opacity: .92; margin-top: 14px; position: relative; z-index: 1; }
  .lg-chat { position: relative; z-index: 1; display: flex; flex-direction: column; gap: 10px; max-width: 420px; }
  .lg-b { padding: 10px 14px; border-radius: 18px; font-size: 15px; line-height: 1.4; max-width: 85%; opacity: 0; transform: translateY(8px);
    animation: lg-in .5s cubic-bezier(.2,.7,.2,1) forwards; }
  .lg-b.user { align-self: flex-end; background: #fff; color: #1B2160; border-bottom-right-radius: 6px; }
  .lg-b.bot { align-self: flex-start; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.25); backdrop-filter: blur(6px);
    border-bottom-left-radius: 6px; }
  .lg-b mark { background: #FFD166; color: #1B2160; border-radius: 6px; padding: 0 5px; font-weight: 600; }
  .lg-sense { align-self: flex-end; display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; opacity: 0; animation: lg-in .5s ease forwards; }
  .lg-sense span { font-size: 12.5px; padding: 3px 9px; border-radius: 999px; background: rgba(15,20,70,.35); border: 1px solid rgba(255,255,255,.22); }
  .lg-sense b { font-weight: 700; color: #FFD166; }
  .lg-b:nth-child(1) { animation-delay: .25s; } .lg-sense { animation-delay: 1s; } .lg-b:nth-child(3) { animation-delay: 1.7s; }
  .lg-b:nth-child(4) { animation-delay: 2.6s; }
  @keyframes lg-in { to { opacity: 1; transform: none; } }
  .lg-side { display: flex; align-items: center; justify-content: center; padding: 32px clamp(20px, 5vw, 64px); overflow-y: auto; }
  .lg-form { width: min(380px, 100%); display: flex; flex-direction: column; gap: 18px; }
  .lg-form h2 { font: 700 34px/1.1 var(--display); letter-spacing: -.02em; }
  .lg-form > p { color: var(--muted); margin-top: -8px; }
  .lg-field { display: flex; flex-direction: column; gap: 6px; font-weight: 600; font-size: 14px; }
  .lg-field input { padding: 12px 14px; font-size: 16px; border-radius: 12px; border: 1.5px solid var(--line); transition: border-color .15s, box-shadow .15s; }
  .lg-field input:focus { outline: none; border-color: var(--brand); box-shadow: 0 0 0 4px color-mix(in srgb, var(--brand) 18%, transparent); }
  .lg-go { justify-content: center; padding: 13px 18px; font-size: 16px; border-radius: 12px; margin-top: 4px;
    background: linear-gradient(135deg, #6A4CF5, #3346D3); color: #fff; box-shadow: 0 10px 24px -12px rgba(51, 70, 211, .8);
    transition: transform .15s, box-shadow .15s; }
  .lg-go:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 14px 28px -12px rgba(51, 70, 211, .95); }
  .lg-go:disabled { opacity: .7; }
  .lg-form .us-msg { margin: 0; }
  .lg-foot { color: var(--muted); font-size: 13px; }
  @media (max-width: 820px) {
    dialog.lg[open] { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
    .lg-stage { padding: 28px 20px 24px; gap: 18px; } .lg-chat { display: none; } .lg-mark { font-size: 56px; }
    .lg-side { align-items: flex-start; }
  }
  @media (prefers-reduced-motion: reduce) { .lg-b, .lg-sense { animation: none; opacity: 1; transform: none; } .lg-go { transition: none; } }
`));

window.showLogin = () => usLogin || (usLogin = new Promise((resolve) => {
  let last = '';
  try { last = localStorage.getItem('parla-user') || ''; } catch {}
  const name = h('input', { autocomplete: 'username', required: true, value: last, autocapitalize: 'none', spellcheck: 'false' });
  const pass = h('input', { type: 'password', autocomplete: 'current-password', required: true });
  const msg = usMsg(), go = h('button', { class: 'btn lg-go' }, 'Entrar');
  const field = (text, input) => h('label', { class: 'lg-field' }, text, input);
  const d = h('dialog', { class: 'lg', 'aria-labelledby': 'us-login' },
    h('section', { class: 'lg-stage', 'aria-hidden': 'true' },
      h('div', {}, h('div', { class: 'lg-mark' }, 'Parla', h('span', {}, '.')), h('p', { class: 'lg-lead' }, 'Bots que entienden cómo habla tu gente.')),
      h('div', { class: 'lg-chat' },
        h('div', { class: 'lg-b user' }, 'dame una de ', h('mark', {}, 'muzza'), ' para ', h('mark', {}, 'Palermo')),
        h('div', { class: 'lg-sense' }, h('span', {}, 'quiere ', h('b', {}, 'Pedir pizza')), h('span', {}, 'gusto ', h('b', {}, 'muzzarella')), h('span', {}, 'barrio ', h('b', {}, 'Palermo'))),
        h('div', { class: 'lg-b bot' }, '¡Sale una muzzarella para Palermo! 🍕 ¿A qué dirección te la mando?'),
        h('div', { class: 'lg-b user' }, 'Gorriti 4500'))),
    h('div', { class: 'lg-side' }, h('form', { class: 'lg-form', onsubmit: async (e) => {
      e.preventDefault(); go.disabled = true; go.textContent = 'Entrando…'; msg.textContent = '';
      try {
        const r = await usApi('POST', '/api/auth/login', { name: name.value.trim(), password: pass.value });
        try { localStorage.setItem('parla-user', name.value.trim()); } catch {}
        window.me = r.user; window.authEnabled = true; usLogin = null;
        d.close(); d.remove(); resolve(r.user);
      } catch (err) { usFail(msg, err); pass.select(); }
      go.disabled = false; go.textContent = 'Entrar';
    } }, h('h2', { id: 'us-login' }, 'Hola de nuevo'),
      h('p', {}, 'Entrá para seguir armando tus agentes.'),
      field('Usuario', name), field('Contraseña', pass), msg, go,
      h('p', { class: 'lg-foot' }, 'Todo corre en esta compu: tus conversaciones no salen a internet.'))));
  d.oncancel = (e) => e.preventDefault();        // sin sesión no hay a dónde volver
  document.body.append(d); d.showModal(); (last ? pass : name).focus();
}));

async function usLogout() {
  try { await usApi('POST', '/api/auth/logout'); } catch {}
  location.reload();
}

function usRolePicker(current) {
  const box = h('div', { class: 'us-roles', role: 'radiogroup', 'aria-label': 'Rol' });
  const id = 'r' + Math.random().toString(36).slice(2, 7);
  for (const [role, [title, text]] of Object.entries(US_ROLES))
    box.append(h('label', {}, h('input', { type: 'radio', name: id, value: role, checked: role === current }), h('span', {}, h('strong', {}, title), h('small', {}, text))));
  box.value = () => box.querySelector('input:checked')?.value;
  return box;
}

// Qué agentes ve: todos (null) o solo algunos (lista de ids). El dueño siempre ve todos.
function usScope(u, agents) {
  if (u.role === 'owner' || u.bots == null) return 'Ve todos los agentes';
  const names = agents.filter((a) => u.bots.includes(a.id)).map((a) => a.name);     // los borrados no cuentan
  return names.length ? 'Ve ' + names.length + (names.length === 1 ? ' agente: ' : ' agentes: ') + names.join(', ') : 'No ve ningún agente';
}

function usBotsPicker(agents, current) {
  const id = 'b' + Math.random().toString(36).slice(2, 7);
  const all = h('input', { type: 'radio', name: id, checked: current == null }), some = h('input', { type: 'radio', name: id, checked: current != null });
  const list = h('div', { class: 'us-roles us-bots', hidden: current == null },
    agents.length ? agents.map((a) => h('label', {}, h('input', { type: 'checkbox', value: a.id, checked: (current || []).includes(a.id) }), h('span', {}, a.name)))
      : h('small', {}, 'Todavía no hay agentes.'));
  all.onchange = some.onchange = () => { list.hidden = !some.checked; };
  const box = h('div', { class: 'us-roles', role: 'radiogroup', 'aria-label': 'Qué agentes ve' },
    h('label', {}, all, h('span', {}, h('strong', {}, 'Todos'), h('small', {}, 'Ve todos los agentes, también los que se creen más adelante.'))),
    h('label', {}, some, h('span', {}, h('strong', {}, 'Solo estos'), h('small', {}, 'Los demás ni le aparecen en la lista. Si crea un agente, ese también lo ve.'))),
    list);
  box.value = () => all.checked ? null : [...list.querySelectorAll('input:checked')].map((i) => i.value);
  return box;
}

function usPasswordFields() {
  const a = h('input', { type: 'password', autocomplete: 'new-password', minlength: 5, required: true });
  const b = h('input', { type: 'password', autocomplete: 'new-password', minlength: 5, required: true });
  const check = () => { if (a.value !== b.value) throw new Error('Las dos contraseñas no coinciden.'); return a.value; };
  return { nodes: [lab('Contraseña (5 caracteres o más)', a), lab('Repetila', b)], check };
}

function usKeyShown(key) {
  const done = h('span', { class: 'help', role: 'status' }), pre = h('div', { class: 'us-secret' }, key);
  const copy = async () => {
    try { await navigator.clipboard.writeText(key); done.textContent = 'Copiada'; }
    catch { getSelection().selectAllChildren(pre); done.textContent = 'Quedó seleccionada: copiala con Ctrl+C (o ⌘C)'; }
  };
  return h('div', { class: 'notice', style: 'flex-direction:column;align-items:stretch' },
    h('strong', {}, 'Copiala ahora: no se vuelve a mostrar.'), pre,
    h('p', { class: 'help', style: 'font-size:13px' }, 'Se usa en la API o el MCP con el encabezado «Authorization: Bearer <clave>» (en el MCP, la variable PARLA_TOKEN).'),
    h('div', { class: 'row' }, h('button', { class: 'btn quiet small', type: 'button', onclick: copy }, 'Copiar'), done));
}

function usUserCard(u, owners, redraw, agents) {
  const msg = usMsg(), extra = h('div', { class: 'us-body' });
  const act = async (fn) => { msg.textContent = ''; try { await fn(); } catch (e) { usFail(msg, e); } };
  const base = '/api/users/' + encodeURIComponent(u.name);
  const lastOwner = u.role === 'owner' && owners === 1;
  const role = pick(Object.entries(US_ROLES).map(([k, [t]]) => [k, t]), u.role,
    (v) => act(async () => { await usApi('PUT', base, { role: v }); await redraw(); }).then(() => { role.value = u.role; }), 'Rol de ' + u.name);
  const resetForm = () => {
    const pw = usPasswordFields();
    extra.replaceChildren(h('form', { class: 'us-body', onsubmit: (e) => { e.preventDefault(); act(async () => {
      await usApi('PUT', base, { password: pw.check() }); extra.replaceChildren(h('p', { class: 'notice' }, 'Listo: la contraseña cambió. Avisale a ' + u.name + '.'));
    }); } }, pw.nodes, h('div', { class: 'row' }, h('button', { class: 'btn small' }, 'Guardar contraseña'),
      h('button', { class: 'btn quiet small', type: 'button', onclick: () => extra.replaceChildren() }, 'Cancelar'))));
  };
  const scope = u.role === 'owner' ? h('p', { class: 'help', style: 'font-size:13px' }, 'Ve todos los agentes')
    : (() => {
      const bots = usBotsPicker(agents, u.bots ?? null);
      return h('details', {}, h('summary', {}, usScope(u, agents)),
        h('form', { class: 'us-body', onsubmit: (e) => { e.preventDefault(); act(async () => { await usApi('PUT', base, { bots: bots.value() }); await redraw(); }); } },
          h('span', { class: 'help', style: 'font-size:13px' }, '¿Qué agentes ve?'), bots, h('div', { class: 'row' }, h('button', { class: 'btn small' }, 'Guardar'))));
    })();
  const shown = h('div');
  const label = h('input', { placeholder: 'Para qué es, por ejemplo: MCP de mi compu', 'aria-label': 'Para qué es la clave', class: 'grow' });
  const keys = h('details', { open: u.keys.length > 0 || undefined },
    h('summary', {}, 'Claves de API (' + u.keys.length + ')'),
    h('p', { class: 'help', style: 'font-size:13px' }, 'Sirven para que un programa (la API o tu asistente de IA por MCP) entre como ' + u.name + ', con sus mismos permisos.'),
    u.keys.map((k) => h('div', { class: 'us-key' }, h('span', { class: 'grow' }, k.label), h('small', { class: 'help' }, k.created.slice(0, 10)),
      iconBtn('trash', 'Revocar clave «' + k.label + '»', () => confirmBox('Revocar la clave', 'Lo que use «' + k.label + '» deja de entrar a Parla.', 'Revocar',
        () => act(async () => { await usApi('DELETE', base + '/keys/' + k.id); await redraw(); }))))),
    h('form', { class: 'row', style: 'margin-top:8px', onsubmit: (e) => { e.preventDefault(); act(async () => {
      const r = await usApi('POST', base + '/keys', { label: label.value });
      await redraw(u.name, usKeyShown(r.key));
    }); } }, label, h('button', { class: 'btn small' }, icon('key'), 'Crear clave')), shown);
  const card = h('div', { class: 'us-user' },
    h('div', { class: 'row' }, h('strong', {}, u.name, u.name === window.me?.name ? h('small', { class: 'help', style: 'font:400 13px var(--body, inherit)' }, ' (vos)') : null), role),
    h('p', { class: 'help', style: 'font-size:13px' }, US_ROLES[u.role]?.[1] || ''), scope,
    h('div', { class: 'row' }, h('button', { class: 'btn quiet small', type: 'button', onclick: resetForm }, 'Cambiar contraseña'),
      lastOwner ? null : h('button', { class: 'btn danger small', type: 'button', onclick: () => confirmBox('Borrar el usuario', 'Se borra «' + u.name + '» y sus claves de API. No se puede deshacer.', 'Borrar usuario',
        () => act(async () => { await usApi('DELETE', base); await redraw(); })) }, 'Borrar')),
    extra, keys, msg);
  card.showKey = (node) => { keys.open = true; shown.replaceChildren(node); };
  return card;
}

function usNewUser(redraw, agents) {
  const name = h('input', { required: true, maxlength: 40, autocomplete: 'off' }), roles = usRolePicker('editor'), pw = usPasswordFields(), msg = usMsg();
  const bots = usBotsPicker(agents, null), owner = h('p', { class: 'help', style: 'font-size:13px', hidden: true }, 'Ve todos los agentes');
  const scope = h('div', { class: 'us-roles' }, h('span', { class: 'help', style: 'font-size:13px' }, '¿Qué agentes ve?'), bots, owner);
  roles.onchange = () => { const isOwner = roles.value() === 'owner'; bots.hidden = isOwner; owner.hidden = !isOwner; };
  return h('form', { class: 'us-user', onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = '';
    const role = roles.value();
    try { await usApi('POST', '/api/users', { name: name.value, role, password: pw.check(), bots: role === 'owner' ? null : bots.value() }); await redraw(); }
    catch (err) { usFail(msg, err); }
  } }, h('strong', {}, 'Nuevo usuario'), lab('Nombre', name), h('div', { class: 'us-roles' }, h('span', { class: 'help', style: 'font-size:13px' }, '¿Qué puede hacer?'), roles), scope, pw.nodes, msg,
    h('div', { class: 'row' }, h('button', { class: 'btn small' }, 'Crear usuario'), h('button', { class: 'btn quiet small', type: 'button', onclick: () => redraw() }, 'Cancelar')));
}

function usFirstOwner(body) {
  const name = h('input', { required: true, maxlength: 40, autocomplete: 'username' }), pw = usPasswordFields(), msg = usMsg();
  return [
    h('p', { class: 'help' }, 'Ahora Parla está abierto: cualquiera que lo abra en esta compu puede usarlo todo. Si lo comparten varias personas, creá usuarios para que cada una entre con su contraseña y vea solo lo que le toca.'),
    h('p', { class: 'help' }, 'El primer usuario es el dueño: puede todo y es quien crea a los demás. Desde que lo crees, para entrar a Parla hay que iniciar sesión.'),
    h('form', { class: 'us-body', onsubmit: async (e) => {
      e.preventDefault(); msg.textContent = '';
      try {
        const u = await usApi('POST', '/api/users', { name: name.value, password: pw.check() });
        window.authEnabled = true; window.me = { name: u.name, role: u.role };
        usDraw(body);
      } catch (err) { usFail(msg, err); }
    } }, lab('Tu nombre de usuario', name), pw.nodes, msg, h('div', { class: 'row' }, h('button', { class: 'btn' }, 'Crear usuario dueño')))];
}

async function usDraw(body, focus, keyNode) {
  const me = window.me;
  if (!window.authEnabled) return body.replaceChildren(...usFirstOwner(body));
  const mine = h('div', { class: 'row' }, h('span', { class: 'grow' }, 'Entraste como ', h('strong', {}, me?.name || '—'), ' · ', US_ROLES[me?.role]?.[0] || ''),
    h('button', { class: 'btn quiet small', type: 'button', onclick: usLogout }, 'Cerrar sesión'));
  if (me?.role !== 'owner') return body.replaceChildren(mine, h('p', { class: 'help' }, US_ROLES[me?.role]?.[1] || ''),
    h('p', { class: 'help', style: 'font-size:13px' }, 'Para cambiar tu rol o tu contraseña, pedíselo al dueño de este Parla.'));
  const redraw = (f, k) => usDraw(body, f, k);
  try {
    const [{ users }, agents] = await Promise.all([usApi('GET', '/api/users'), usApi('GET', '/api/agents')]);
    const owners = users.filter((u) => u.role === 'owner').length;
    const cards = users.map((u) => usUserCard(u, owners, redraw, agents));
    const list = h('div', { class: 'us-body' }, cards);
    body.replaceChildren(mine,
      h('div', { class: 'row' }, h('p', { class: 'help grow' }, 'Cada persona entra con su usuario y ve solo lo que le permite su rol.'),
        h('button', { class: 'btn small', type: 'button', onclick: () => list.prepend(usNewUser(redraw, agents)) }, icon('plus'), 'Nuevo usuario')),
      list);
    if (focus && keyNode) cards[users.findIndex((u) => u.name === focus)]?.showKey(keyNode);
  } catch (e) { body.replaceChildren(mine, h('p', { class: 'notice warn' }, 'No pude traer los usuarios: ' + e.message)); }
}

// Usuarios es una pantalla (#/usuarios), con el mismo marco que «Tus agentes»: es demasiado para un modal.
document.head.append(h('style', {}, `
  .home-hero.home-hero-sm { padding-bottom: 30px; }
  .home-hero-sm h1 { font-size: clamp(36px, 5vw, 52px); }
  .home-back { gap: 6px; }
  .us-page { gap: 18px; }
  .us-page > .row:first-child { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 12px 16px; }
  .us-page > .row:nth-child(2) { justify-content: space-between; }
  .us-page > .us-body { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(400px, 100%), 1fr)); gap: 16px; align-items: start; }
  .us-page .us-user { background: var(--surface); border-radius: 18px; padding: 18px; box-shadow: 0 14px 30px -24px rgba(23, 32, 51, .5); }
  :root[data-theme="color"] .us-page > .row:nth-child(2) .help { color: rgba(255,255,255,.85); }
`));
function usOpen() { window.usersPage(); }
window.usersPage = async () => {
  if (typeof agent !== 'undefined' && agent) { await saveNow(); agent = null; }
  history.replaceState(null, '', '#/usuarios');               // F5 vuelve a esta pantalla
  const body = h('div', { class: 'us-body us-page' }, h('p', { class: 'help' }, 'Cargando…'));
  const app = $('#app');
  app.className = 'home';
  app.replaceChildren(
    h('header', { class: 'home-hero home-hero-sm' }, h('div', { class: 'home-in' },
      h('div', { class: 'home-top' }, h('button', { class: 'btn quiet home-back', onclick: () => home() }, icon('back'), 'Tus agentes'),
        h('div', { class: 'row' }, window.themeSwitcher?.(), h('span', { 'data-me-slot': '' }, window.userAvatar()))),
      h('h1', {}, 'Usuarios'),
      h('p', { class: 'home-lead' }, 'Quién entra a Parla, qué puede hacer cada uno y qué agentes ve.'))),
    h('main', { class: 'home-in home-body' }, body));
  usDraw(body);
};
window.usersButton = () => h('button', { class: 'btn quiet', onclick: usOpen }, icon('users'), window.me ? window.me.name : 'Usuarios');

// Avatar de arriba a la derecha (inicio y editor): quién soy, usuarios y cerrar sesión sin volver a ningún lado.
document.head.append(h('style', {}, `
  .us-av { width: 34px; height: 34px; border-radius: 50%; display: inline-grid; place-items: center; flex: none; color: #fff; font: 800 15px var(--display);
    background: linear-gradient(135deg, #6A4CF5, #3346D3); box-shadow: 0 0 0 2px var(--surface), 0 0 0 3px color-mix(in srgb, #6A4CF5 40%, transparent);
    transition: transform .15s, box-shadow .15s; }
  .us-av:hover { transform: translateY(-1px); box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px #6A4CF5; }
  .us-who { display: flex; align-items: center; gap: 10px; padding: 8px 10px 10px; border-bottom: 1px solid var(--line); margin-bottom: 4px; }
  .us-who strong { display: block; font: 700 15px var(--display); }
  .us-who small { color: var(--muted); }
`));
window.userAvatar = () => {
  if (!window.authEnabled || !window.me) return window.usersButton();      // sin usuarios: el botón para crear el primero
  const me = window.me, initial = (me.name.trim()[0] || '?').toUpperCase();
  return h('button', { class: 'us-av', 'aria-label': 'Tu usuario: ' + me.name, title: me.name, 'aria-haspopup': 'menu',
    onclick: (e) => openPop(e.currentTarget.getBoundingClientRect(), [
      h('div', { class: 'us-who' }, h('span', { class: 'us-av', 'aria-hidden': 'true' }, initial), h('span', {}, h('strong', {}, me.name), h('small', {}, (US_ROLES[me.role] || [me.role])[0]))),
      h('button', { class: 'opt', onclick: () => { closePop(); usOpen(); } }, icon('users'), h('span', {}, me.role === 'owner' ? 'Administrar usuarios' : 'Mi usuario')),
      h('button', { class: 'opt', onclick: () => { closePop(); usLogout(); } }, icon('back'), h('span', {}, 'Cerrar sesión')),
    ]) }, initial);
};

(async () => {      // al abrir: ¿hay usuarios? ¿quién soy? (index.html ya pudo dibujar el inicio sin este botón)
  try {
    const r = await usApi('GET', '/api/auth/me');
    window.authEnabled = r.enabled; window.me = r.user;
    if (r.enabled && !r.user) await window.showLogin();
  } catch {}
  if (location.hash === '#/usuarios') window.usersPage();      // ya sabemos quién es: redibujar con sus permisos
  else if (typeof agent !== 'undefined' && !agent && $('#app')?.classList.contains('home')) home();
  document.querySelectorAll('[data-me-slot]').forEach((el) => el.replaceChildren(window.userAvatar()));   // el editor ya estaba abierto (F5)
})();
