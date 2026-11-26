# Skills para asistentes de IA

[English](skills.md) · **Español**

El [servidor MCP](mcp_es.md) de Parla le da a un asistente las *herramientas* para armar bots. Las **skills** de
[`skills/`](../skills) le dan el *oficio*: cómo puntúa de verdad el NLU de Parla, qué tipo de entidad elegir, cómo
diseñar preguntas, botones y pases a una persona, cómo llamar APIs sin tocar claves, cómo probar y publicar sin
romper nada. Usan el formato [Agent Skills](https://agentskills.io) (una carpeta con un `SKILL.md` que tiene
`name` y `description`, más archivos de referencia que el asistente lee solo cuando los necesita), así que las
cargan Claude Code, Claude Desktop / claude.ai, Codex, Cursor y otros. Están en inglés (es lo que mejor siguen los
modelos); los ejemplos de bots están en español rioplatense.

| Skill | Para qué sirve |
|---|---|
| [`parla-build-bot`](../skills/parla-build-bot/SKILL.md) | El recorrido completo con las herramientas del MCP: averiguar, diseñar, crear, validar, leer la autoevaluación, probar, publicar. Trae un bot de ejemplo verificado ([`dental-clinic.json`](../skills/parla-build-bot/examples/dental-clinic.json)). |
| [`parla-nlu-design`](../skills/parla-nlu-design/SKILL.md) | Intenciones, frases, tipos de entidad, marcas, sinónimos, `phrasings`, umbrales, con puntajes medidos con el modelo real. |
| [`parla-flow-design`](../skills/parla-flow-design/SKILL.md) | Flujos y pasos, preguntas y repreguntas, botones por canal, condiciones, interrupciones, flujos del sistema, voz y bots en varios idiomas. |
| [`parla-integrations`](../skills/parla-integrations/SKILL.md) | Pasos `http` y claves, funciones, archivos, base de conocimiento, IA y privacidad, widget, WhatsApp y Telegram, datos personales. |
| [`parla-testing-and-release`](../skills/parla-testing-and-release/SKILL.md) | Pruebas de conversación (también los caminos negativos), el freno al publicar, staging/producción, volver atrás, mejorar con conversaciones reales. |
| [`parla-migrate-from-rasa`](../skills/parla-migrate-from-rasa/SKILL.md) | `import_rasa_project` y lo que hay que revisar después. |

Un resumen para leer vos de los mismos consejos está en [best-practices_es.md](best-practices_es.md).

## Sin instalar nada: los recursos del MCP

Con Parla conectado («Conectar con IA», ver [mcp_es.md](mcp_es.md)), el propio servidor MCP sirve las skills como
recursos: `parla://skills` (el índice) y `parla://skills/<skill>/<archivo>` (cada `SKILL.md` y sus archivos de
referencia). El prompt `build_bot` y las instrucciones del servidor le dicen al modelo que lea primero
`parla://skills/parla-build-bot/SKILL.md`. Los clientes que dejan al modelo leer recursos (o que te dejan
adjuntarlos, como el menú «+» de Claude Desktop o las menciones con `@` en Claude Code) las tienen sin hacer nada.

Instalarlas como skills (abajo) sigue siendo mejor donde se puede: el asistente carga sola la que corresponde por
su descripción, incluso antes de hablar con Parla.

## Claude Code

Personales (para todos los proyectos), como enlaces que se actualizan con `git pull`:

```sh
make skills-install                     # enlaza skills/* en ~/.claude/skills/
```

Muestra lo que enlaza, actualiza sus propios enlaces y saltea (avisando) cualquier carpeta que ya exista y no sea
un enlace. A mano, o para un solo proyecto:

```sh
mkdir -p ~/.claude/skills && ln -s "$PWD"/skills/* ~/.claude/skills/          # personales
mkdir -p .claude/skills && cp -R /ruta/a/parla/skills/* .claude/skills/        # en el repositorio de tu bot
```

Reiniciá Claude Code; `/skills` (o preguntarle «¿qué skills tenés?») las lista. Después pedile «armame un bot que
tome turnos para la peluquería».

## Claude Desktop y claude.ai

Las skills se suben como zip (una por skill) en **Configuración → Capacidades → Skills** (el nombre exacto del
menú puede cambiar según la versión; tiene que estar prendida la ejecución de código):

```sh
cd skills && for d in */; do (cd "$d" && zip -qr "../../parla-${d%/}.zip" .); done; cd ..
```

Subí cada `parla-*.zip`. Conectá también el servidor MCP (ver [mcp_es.md](mcp_es.md)): las skills le explican al
modelo cómo usar sus herramientas.

## Codex, Cursor y otros asistentes

No necesitan un formato especial: apuntalos a los archivos.

- **Codex** (`AGENTS.md` en tu repositorio o `~/.codex/AGENTS.md`):

  ```markdown
  When building or changing Parla bots, first read /ruta/a/parla/skills/parla-build-bot/SKILL.md
  and then the skill in /ruta/a/parla/skills/ that matches the task (nlu-design, flow-design,
  integrations, testing-and-release, migrate-from-rasa).
  ```

- **Cursor**: una regla de proyecto (`.cursor/rules/parla.mdc`) con el mismo texto, o sumá la carpeta `skills/`
  al contexto del chat.
- **Cualquier cliente MCP**: los recursos `parla://skills` y el prompt `build_bot`.

## Cómo se combinan con el MCP

Las skills no reemplazan las herramientas: le dicen al modelo que use `agent_format_guide` para los campos
exactos, `validate_agent` antes de guardar, `test_conversation` y `run_tests` antes de publicar, y que te pregunte
antes de que algo llegue a producción. También le prohíben manejar valores de claves: usa `{{ secret.NOMBRE }}` y
te pide que cargues el valor en «Claves».

## Para quien contribuye

Cada bloque ```` ```json parla-agent ```` de las skills es un agente (o uno chico y completo) que tiene que pasar
`validate_agent` sin errores. `tests/test_skills.py` lo revisa, junto con el frontmatter (`name` = carpeta,
kebab-case, `description` ≤ 1024 caracteres), que cada `SKILL.md` tenga menos de 500 líneas, que los links
relativos existan, que el bot de ejemplo valide sin advertencias y que el servidor MCP sirva cada archivo. Si
cambia el motor, revisá los números de `parla-nlu-design/reference.md`.
