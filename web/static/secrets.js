// Claves: contraseñas y API keys del agente. Se guardan aparte (agents/<id>.secrets.json, ver vault.py) y nunca vuelven a la interfaz.
let scNames = null, scFor = null, scError = '';      // nombres cargados, de qué agente y el último error

async function scLoad() {
  try { scNames = (await api('GET', '/' + agent.id + '/secrets')).secrets; }
  catch (e) { scNames = []; scError = e.message; }
  if (section === 'secrets') render();
}

function scForm(name, done) {          // nombre (si es nueva) + valor; reemplaza si ya existía
  const nameIn = h('input', { placeholder: t('Por ejemplo: API_KEY_CLIMA'), 'aria-label': t('Nombre de la clave'), required: true, value: name || '', disabled: !!name,
    oninput: (e) => { e.target.value = e.target.value.toUpperCase().replace(/[^A-Z0-9_]+/g, '_'); } });
  const value = h('input', { type: 'password', autocomplete: 'new-password', placeholder: name ? t('Valor nuevo') : t('Valor'), 'aria-label': t('Valor de la clave'), required: true });
  const msg = h('p', { class: 'notice warn', role: 'alert', hidden: true });
  return h('form', { class: 'panel', onsubmit: async (e) => {
    e.preventDefault(); msg.hidden = true;
    try { scNames = (await api('PUT', '/' + agent.id + '/secrets', { name: nameIn.value, value: value.value })).secrets; done(); }
    catch (err) { msg.textContent = err.message; msg.hidden = false; }
  } }, name ? h('strong', {}, t('Cambiar el valor de {name}', { name })) : h('strong', {}, t('Nueva clave')),
    name ? null : lab(t('Nombre (mayúsculas, números y _)'), nameIn), lab(t('Valor'), value), msg,
    h('div', { class: 'row' }, h('button', { class: 'btn small' }, t('Guardar')), h('button', { class: 'btn quiet small', type: 'button', onclick: done }, t('Cancelar'))));
}

let scEditing = null;      // '' = nueva, 'NOMBRE' = reemplazando esa
window.secretsView = () => {
  if (scFor !== agent.id) { scFor = agent.id; scNames = null; scEditing = null; scError = ''; scLoad(); }
  const close = () => { scEditing = null; render(); };
  const row = (n) => scEditing === n ? scForm(n, close) : h('div', { class: 'phrase-row' },
    h('span', { class: 'phrase' }, h('code', {}, n), h('span', { class: 'help', style: 'margin-left:10px' }, '••••••••')),
    h('button', { class: 'btn quiet small', onclick: () => { scEditing = n; render(); } }, t('Cambiar valor')),
    iconBtn('trash', t('Borrar la clave {name}', { name: n }), () => confirmBox(t('Borrar la clave'), t('Se borra {name}. Las consultas y funciones que usan {{ secret.{name} }} van a dejar de andar hasta que la vuelvas a cargar.', { name: n }), t('Borrar clave'),
      async () => { try { scNames = (await api('DELETE', '/' + agent.id + '/secrets', { name: n })).secrets; } catch (e) { scError = e.message; } render(); })));
  return h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('h1', {}, t('Claves')), h('button', { class: 'btn', onclick: () => { scEditing = ''; render(); } }, icon('plus'), t('Nueva clave'))),
    h('p', { class: 'help' }, t('Guardá acá contraseñas y API keys que el bot necesita para hablar con otros sistemas. Usalas como '),
      h('code', {}, t('{{ secret.NOMBRE }}')), t(' en las consultas HTTP y en las funciones.')),
    h('p', { class: 'help' }, t('Una vez guardadas no se pueden volver a ver (solo cambiar o borrar), no viajan cuando exportás el agente y nunca se le muestran a quien chatea con el bot.')),
    scError ? h('p', { class: 'notice warn', role: 'alert' }, scError) : null,
    scEditing === '' ? scForm('', close) : null,
    scNames === null ? h('p', { class: 'help' }, t('Cargando…'))
      : scNames.length ? h('div', { class: 'panel phrases' }, scNames.map(row))
      : scEditing === '' ? null : h('div', { class: 'empty' }, h('h2', {}, t('Todavía no hay claves')), h('p', {}, t('Creá una con «Nueva clave» cuando una consulta necesite una contraseña o API key.'))));
};
