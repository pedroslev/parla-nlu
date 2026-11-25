// Clasificaciones: las formas en que puede terminar una conversación (las aplica el paso «Clasificar» de un flujo). El conteo está en Reportes.
document.head.append(h('style', {}, `
  .cl-uses { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 14px; color: var(--muted); }
`));

const clOf = (name) => agent.classifications.find((c) => c.name === name);
function clUses(name) {                  // flujos que tienen un paso «Clasificar» con esta clasificación
  return agent.flows.filter((f) => { let used = false; walkSteps((s) => { if (s.type === 'classify' && s.classification === name) used = true; }, f.steps); return used; });
}
function clRename(c, raw) {
  const name = raw.trim().slice(0, 80);
  if (!name || name === c.name || clOf(name)) return render();
  walkSteps((s) => { if (s.type === 'classify' && s.classification === c.name) s.classification = name; });
  c.name = name; touch(); render();
}
function clRemove(c) {
  const flows = clUses(c.name), list = flows.map((f) => t('«{name}»', { name: f.name })).join(', ');
  confirmBox(t('Borrar la clasificación'), t('Se borra «{name}».', { name: c.name }) + ' ' + (flows.length
    ? t.plural(flows.length, 'La usa el flujo {list}: esos pasos van a quedar sin clasificación hasta que elijas otra.', 'La usan los flujos {list}: esos pasos van a quedar sin clasificación hasta que elijas otra.', { list })
    : t('Ningún flujo la usa.')) + ' ' + t('Las conversaciones que ya la tenían la siguen mostrando en Reportes.'), t('Borrar clasificación'), () => {
    walkSteps((s) => { if (s.type === 'classify' && s.classification === c.name) s.classification = ''; });
    agent.classifications.splice(agent.classifications.indexOf(c), 1); touch(); render();
  });
}
const clOpenFlow = (f) => { section = 'flows'; sel.flows = agent.flows.indexOf(f); render(); $('#center').scrollTop = 0; };

const clAdd = (e) => openPop(e.currentTarget.getBoundingClientRect(), nameForm(t('Por ejemplo: Turno agendado'), t('Crear'), (raw) => { createClassification(raw); touch(); render(); }));
function clManage() {
  const card = (c) => {
    const flows = clUses(c.name);
    return h('div', { class: 'panel' },
      h('div', { class: 'row', style: 'flex-wrap:nowrap' },
        h('input', { class: 'grow', value: c.name, 'aria-label': t('Nombre de la clasificación'), style: 'font-weight:600', onchange: (e) => clRename(c, e.target.value) }),
        colorField(c, t('Color de la clasificación')),
        iconBtn('trash', t('Borrar clasificación'), () => clRemove(c))),
      lab(t('Cuándo se usa (opcional)'), h('input', { ...bind(c, 'description'), placeholder: t('Por ejemplo: la persona confirmó día y horario') })),
      h('div', { class: 'cl-uses' }, flows.length
        ? [t.plural(flows.length, 'La aplica el flujo', 'La aplican los flujos'), flows.map((f) => h('button', { class: 'link', onclick: () => clOpenFlow(f) }, f.name))]
        : t('Todavía no la aplica ningún flujo. En un flujo, sumá el paso «Clasificar la conversación».')));
  };
  return agent.classifications.length ? agent.classifications.map(card)
    : h('div', { class: 'empty' }, h('h2', {}, t('Todavía no hay clasificaciones')), h('p', {}, t('Creá una por cada forma en que puede terminar una conversación.')));
}

window.classificationsView = () => h('div', { class: 'page' },
  h('div', { class: 'page-head' }, h('h1', {}, t('Clasificaciones')), h('button', { class: 'btn', onclick: clAdd }, icon('plus'), t('Nueva clasificación'))),
  h('p', { class: 'help' }, t('Las clasificaciones dicen cómo terminó cada conversación: «Turno agendado», «Cancelación», «Consulta de precios». Las aplicás desde un flujo con el paso «Clasificar la conversación».'),
    agent.classifications.length ? [' ', h('button', { class: 'link', onclick: () => { section = 'reports'; render(); $('#center').scrollTop = 0; } }, t('Ver reportes'))] : null),
  clManage());
