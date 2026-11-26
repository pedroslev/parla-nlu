// Experimentos A/B (parla/experiments.py): en Versiones se crean, empiezan, pausan y terminan; los resultados (con
// significancia) se ven ahí y en Reportes al filtrar por un experimento. El ganador lo elige una persona.
(() => {
  const fill = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
  document.head.append(h('style', {}, `
    .ex-row { display: flex; flex-direction: column; gap: 6px; padding: 12px 0; border-bottom: 1px solid var(--line); }
    .ex-row:last-child { border-bottom: 0; }
    .ex-meta { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
    .ex-tag.running { background: var(--ok); color: var(--surface); }
    .ex-tag.paused { background: var(--brand-soft); color: var(--brand); }
    .ex-tag.draft, .ex-tag.stopped { background: var(--soft); color: var(--muted); }
    .ex-scroll { overflow-x: auto; }
    .ex-table { border-collapse: collapse; width: 100%; font-size: 14px; }
    .ex-table th, .ex-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
    .ex-table td small { display: block; color: var(--muted); font-size: 12px; }
    .ex-badge { display: inline-block; margin-top: 4px; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; background: var(--soft); color: var(--muted); }
    .ex-badge.better { background: var(--ok); color: var(--surface); }
    .ex-badge.worse { background: var(--warn); color: var(--surface); }
    .ex-variant { display: grid; grid-template-columns: 34px 1fr 90px 32px; gap: 8px; align-items: center; }
  `));
  const STATUS = { draft: t('Sin empezar'), running: t('Corriendo'), paused: t('En pausa'), stopped: t('Terminado') };
  const ENV = { production: t('Producción'), staging: t('Pruebas') };
  const METRICS = [['resolved_rate', t('Resueltas sin persona')], ['handoff_rate', t('Pasadas a una persona')], ['fallback_rate', t('Con algo que no entendió')],
    ['goal_rate', t('Cumplieron el objetivo')], ['csat', t('CSAT promedio')], ['cost', t('Costo por conversación')], ['turns', t('Mensajes por conversación')]];
  const GOALS = [['', t('Sin objetivo')], ['flow', t('Llegó a un flujo')], ['intent', t('Dijo una intención')], ['classification', t('Quedó clasificada')]];
  const base = () => '/' + agent.id + '/experiments';
  const pct = (x) => x == null ? '—' : (x * 100).toFixed(1) + '%';
  const signed = (x, d) => (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d);
  const safely = (fn) => async () => { try { await fn(); } catch (e) { alert(t('No se pudo: {error}', { error: e.message })); } };
  const variantsText = (e) => e.variants.map((v) => v.name + ': v' + v.version + ' (' + v.weight + ')').join(' · ');

  // ---------- resultados ----------
  window.experimentResults = (exp) => {
    const box = h('div', { class: 'stack', 'aria-live': 'polite' }, h('p', { class: 'help' }, t('Calculando…')));
    api('GET', base() + '/' + exp.id + '/results').then((r) => fill(box, resultsTable(r)),
      (e) => fill(box, h('p', { class: 'notice warn' }, t('No se pudieron cargar los resultados: {error}', { error: e.message }))));
    return box;
  };
  function value(key, row, currency) {
    const m = row[key];
    if (m == null) return '—';
    if (key.endsWith('_rate')) return pct(m.rate);
    if (m.avg == null) return '—';
    if (key === 'cost') return window.costText ? window.costText(m.avg, currency) : m.avg.toFixed(4);
    return m.avg.toFixed(2) + (key === 'csat' ? ' (' + t.plural(m.count, '{n} respuesta', '{n} respuestas') + ')' : '');
  }
  function versus(key, c) {
    const m = c?.metrics[key];
    if (!m || m.diff == null) return null;
    const rate = key.endsWith('_rate'), d = rate ? 1 : key === 'cost' ? 4 : 2, k = rate ? 100 : 1, unit = rate ? ' pp' : '';
    const badge = !m.enough_data ? h('span', { class: 'ex-badge' }, t('Faltan datos'))
      : m.significant ? h('span', { class: 'ex-badge ' + (m.direction || '') }, m.direction === 'better' ? t('Mejor, significativo') : m.direction === 'worse' ? t('Peor, significativo') : t('Distinto, significativo'))
      : h('span', { class: 'ex-badge' }, t('Sin diferencia significativa todavía'));
    return [h('small', {}, t('{diff} vs A · IC [{lo}, {hi}] · p = {p}', { diff: signed(m.diff * k, d) + unit, lo: signed(m.ci[0] * k, d), hi: signed(m.ci[1] * k, d), p: m.p < 0.001 ? '<0.001' : m.p.toFixed(3) })), badge];
  }
  function resultsTable(r) {
    const comp = (name) => r.comparisons.find((c) => c.variant === name);
    const rows = METRICS.filter(([key]) => key !== 'goal_rate' || r.experiment.goal);
    return [
      h('p', { class: r.significant.length ? 'notice' : 'help' }, r.significant.length
        ? t('Hay diferencias significativas (con {conf}% de confianza). El experimento no elige solo: decidí vos al terminarlo.', { conf: Math.round(r.confidence * 1000) / 10 })
        : t('Sin diferencia significativa todavía.')),
      r.warnings.length ? h('p', { class: 'notice warn' }, r.warnings.map((w) => w.metric === 'csat'
        ? t('La variante {v} tiene {have} respuestas de CSAT (conviene {need} o más).', { v: w.variant, have: w.have, need: w.need })
        : t('La variante {v} tiene {have} conversaciones: con menos de {need} los resultados no son confiables.', { v: w.variant, have: w.have, need: w.need })).join(' ')) : null,
      h('div', { class: 'ex-scroll' }, h('table', { class: 'ex-table' },
        h('thead', {}, h('tr', {}, h('th', {}, t('Métrica')), r.variants.map((v) => h('th', {}, v.name + ' · v' + v.version)))),
        h('tbody', {},
          h('tr', {}, h('td', {}, t('Conversaciones')), r.variants.map((v) => h('td', {}, String(v.conversations)))),
          rows.map(([key, label]) => h('tr', {}, h('td', {}, label), r.variants.map((v, i) => h('td', {}, value(key, v, r.currency), i ? versus(key, comp(v.name)) : null)))),
          h('tr', {}, h('td', {}, t('Tiempo de respuesta')), r.variants.map((v) => h('td', {}, v.latency_ms == null ? '—' : Math.round(v.latency_ms) + ' ms')))))),
      h('p', { class: 'help', style: 'font-size:13px' }, t('Tasas: prueba z de dos proporciones; promedios: t de Welch. Cada variante contra A; IC al {conf}%.', { conf: Math.round(r.confidence * 1000) / 10 }))];
  }

  // ---------- crear ----------
  function createDialog(info, done) {
    const versions = info.versions.map((x) => x.version);
    const current = info.environments.production ?? versions[0];
    const rows = [{ version: current, weight: 50 }, { version: versions.find((n) => n !== current) ?? current, weight: 50 }];
    const name = h('input', { maxlength: 80, required: true, placeholder: t('Por ejemplo: saludo más corto') });
    const env = pick(Object.entries(ENV), 'production', () => {}, t('Entorno'));
    const goalType = pick(GOALS, '', () => drawGoal(), t('Objetivo'));
    const goalWrap = h('div');
    const channels = h('input', { placeholder: t('Vacío = todos. Por ejemplo: whatsapp, web') });
    const startNow = h('input', { type: 'checkbox', checked: true });
    const list = h('div', { class: 'stack' });
    const msg = h('p', { class: 'notice warn', role: 'alert', hidden: true });
    let goalValue = '';
    function drawGoal() {
      const kind = goalType.value;
      const names = kind === 'flow' ? agent.flows.map((f) => f.name) : kind === 'intent' ? agent.intents.filter((i) => !i.name.startsWith('__')).map((i) => i.name)
        : kind === 'classification' ? (agent.classifications || []).map((c) => c.name) : [];
      goalValue = names[0] || '';
      fill(goalWrap, kind ? lab(t('Cuál'), pick(names.map((n) => [n, n]), goalValue, (v) => { goalValue = v; }, t('Cuál'))) : null);
    }
    function drawRows() {
      fill(list, rows.map((r, i) => h('div', { class: 'ex-variant' }, h('strong', {}, 'ABCD'[i]),
        pick(versions.map((n) => [String(n), 'v' + n + (n === info.environments.production ? ' · ' + t('Producción') : '')]), String(r.version), (v) => { r.version = Number(v); }, t('Versión de la variante {v}', { v: 'ABCD'[i] })),
        h('input', { type: 'number', min: 1, max: 100, value: r.weight, 'aria-label': t('Peso de la variante {v}', { v: 'ABCD'[i] }), oninput: (e) => { r.weight = Number(e.target.value); } }),
        i > 1 ? iconBtn('trash', t('Sacar la variante {v}', { v: 'ABCD'[i] }), () => { rows.splice(i, 1); drawRows(); }) : h('span'))),
        rows.length < 4 ? h('button', { class: 'link', type: 'button', onclick: () => { rows.push({ version: current, weight: 50 }); drawRows(); } }, t('Sumar una variante')) : null);
    }
    drawRows();
    const go = h('button', { class: 'btn' }, t('Crear experimento'));
    const d = h('dialog', { class: 'rl-dialog' }, h('form', { class: 'stack', onsubmit: async (e) => {
      e.preventDefault(); msg.hidden = true; go.disabled = true;
      try {
        const body = { name: name.value, environment: env.value, variants: rows, channels: channels.value.split(',').map((c) => c.trim()).filter(Boolean),
          goal: goalType.value && goalValue ? { type: goalType.value, value: goalValue } : null };
        const exp = await api('POST', base(), body);
        if (startNow.checked) await api('POST', base() + '/' + exp.id + '/start');
        d.close(); done();
      } catch (err) { msg.textContent = err.message; msg.hidden = false; go.disabled = false; }
    } }, h('h2', {}, t('Nuevo experimento')),
      h('p', { class: 'help' }, t('Las conversaciones nuevas del entorno se reparten entre las versiones según el peso, y cada una sigue con la misma versión hasta el final.')),
      lab(t('Nombre'), name), lab(t('Entorno'), env),
      h('div', { class: 'stack' }, h('strong', {}, t('Variantes (versión y peso)')), list),
      lab(t('Objetivo'), goalType), goalWrap, lab(t('Canales'), channels),
      h('label', { class: 'row' }, startNow, t('Empezar ahora')), msg,
      h('div', { class: 'row' }, go, h('button', { class: 'btn quiet', type: 'button', onclick: () => d.close() }, t('Cancelar')))));
    d.onclose = () => d.remove();
    document.body.append(d); d.showModal(); name.focus();
  }

  // ---------- terminar ----------
  function stopDialog(exp, done) {
    const radio = (value, title, checked) => h('label', { class: 'rl-choice' }, h('input', { type: 'radio', name: 'ex-winner', value, checked }), h('span', {}, title));
    const msg = h('p', { class: 'notice warn', role: 'alert', hidden: true });
    const d = h('dialog', { class: 'rl-dialog' }, h('form', { class: 'stack', onsubmit: async (e) => {
      e.preventDefault();
      try {
        await api('POST', base() + '/' + exp.id + '/stop', { winner: d.querySelector('input[name=ex-winner]:checked').value || null });
        d.close(); done();
      } catch (err) { msg.textContent = err.message; msg.hidden = false; }
    } }, h('h2', {}, t('Terminar «{name}»', { name: exp.name })),
      h('p', { class: 'help' }, t('Las conversaciones nuevas dejan de repartirse. Las que están en curso terminan con su versión.')),
      radio('', t('Terminar sin cambiar {env}', { env: ENV[exp.environment] }), true),
      exp.variants.map((v) => radio(v.name, t('Quedarme con {v} (v{n}) en {env}', { v: v.name, n: v.version, env: ENV[exp.environment] }), false)),
      msg, h('div', { class: 'row' }, h('button', { class: 'btn' }, t('Terminar')), h('button', { class: 'btn quiet', type: 'button', onclick: () => d.close() }, t('Cancelar')))));
    d.onclose = () => d.remove();
    document.body.append(d); d.showModal();
  }

  // ---------- el panel de Versiones ----------
  window.experimentsPanel = (info, refresh) => {
    const panel = h('div', { class: 'panel' }, h('h2', {}, t('Experimentos A/B')), h('p', { class: 'help' }, t('Cargando…')));
    const act = (exp, action) => safely(async () => { await api('POST', base() + '/' + exp.id + '/' + action); refresh(); });
    api('GET', base()).then(({ experiments }) => {
      const row = (e) => {
        const out = h('div', { hidden: true });
        const toggle = () => { out.hidden = !out.hidden; if (!out.hidden) fill(out, window.experimentResults(e)); };
        return h('div', { class: 'ex-row' },
          h('div', { class: 'row' }, h('strong', { class: 'grow' }, e.name), h('span', { class: 'tag ex-tag ' + e.status }, STATUS[e.status])),
          h('span', { class: 'ex-meta' }, ENV[e.environment] + ' · ' + variantsText(e) + (e.goal ? ' · ' + t('objetivo: {goal}', { goal: e.goal.value }) : '')
            + (e.channels?.length ? ' · ' + e.channels.join(', ') : '') + (e.winner ? ' · ' + t('ganó {v}', { v: e.winner }) : '')),
          h('div', { class: 'row rl-actions' },
            e.status === 'draft' || e.status === 'paused' ? h('button', { class: 'link', onclick: act(e, 'start') }, e.status === 'draft' ? t('Empezar') : t('Seguir')) : null,
            e.status === 'running' ? h('button', { class: 'link', onclick: act(e, 'pause') }, t('Pausar')) : null,
            e.status === 'running' || e.status === 'paused' ? h('button', { class: 'link', onclick: () => stopDialog(e, refresh) }, t('Terminar y elegir')) : null,
            e.status === 'draft' ? null : h('button', { class: 'link', onclick: toggle }, t('Ver resultados')),
            e.status === 'running' ? null : h('button', { class: 'link', onclick: () => confirmBox(t('Borrar el experimento'), t('Se borra «{name}». Las conversaciones quedan guardadas.', { name: e.name }), t('Borrar'),
              safely(async () => { await api('DELETE', base() + '/' + e.id); refresh(); })) }, t('Borrar'))),
          out);
      };
      fill(panel, h('div', { class: 'row' }, h('h2', { class: 'grow' }, t('Experimentos A/B')),
        info.versions.length >= 1 ? h('button', { class: 'btn small', onclick: () => createDialog(info, refresh) }, t('Nuevo experimento')) : null),
        h('p', { class: 'help' }, t('Compará versiones con tráfico real: cada conversación nueva va a una variante y se miden resolución, derivaciones, CSAT y costo, con significancia estadística.')),
        experiments.length ? experiments.map(row) : h('p', { class: 'help' }, info.versions.length ? t('Todavía no hay experimentos.') : t('Publicá al menos una versión para armar un experimento.')));
    }, (e) => fill(panel, h('h2', {}, t('Experimentos A/B')), h('p', { class: 'notice warn' }, t('No se pudieron cargar los experimentos: {error}', { error: e.message }))));
    return panel;
  };
})();
