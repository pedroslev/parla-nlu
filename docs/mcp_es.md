# MCP y «Conectar con IA»

[English](mcp.md) · **Español**

Parla trae un servidor [MCP](https://modelcontextprotocol.io) que le da a un asistente (Claude Code, Codex, Claude
Desktop, Cursor o claude.ai) herramientas para armar bots: leer la guía del formato, validar, crear, entrenar,
probar conversaciones, publicar y revisar conversaciones reales. Así le podés pedir «armame un bot que tome turnos
para la peluquería» y lo diseña, lo crea, lo prueba y lo corrige.

Parla tiene que estar corriendo mientras lo usás.

## «Conectar con IA» (un clic)

En la interfaz, **Conectar con IA** muestra Claude Code, Codex, Claude Desktop y Cursor, si están instalados y si
ya están conectados. Al conectar:

- **Claude Code**: corre `claude mcp add --scope user parla ...` (si ya estaba, lo saca y lo vuelve a agregar con
  la ruta y el puerto actuales).
- **Codex**: agrega la tabla `[mcp_servers.parla]` a `~/.codex/config.toml`.
- **Claude Desktop**: agrega `parla` a `mcpServers` en `claude_desktop_config.json` (en macOS
  `~/Library/Application Support/Claude/`, en Windows `%APPDATA%\Claude\`, en Linux `~/.config/Claude/`).
- **Cursor**: agrega `parla` a `~/.cursor/mcp.json`.

Antes de tocar un archivo guarda una copia `*.parla-backup`; si el archivo no se puede leer, no lo toca y te
muestra qué pegar a mano («Hacerlo a mano»). Si Parla tiene usuarios, crea una clave de API para tu usuario
(«Conectar con …») y la deja en `PARLA_TOKEN`. Después reiniciá el asistente (Claude Desktop, Codex y Cursor)
y pedile «armame un bot que…».

Esta función solo responde a pedidos hechos a `127.0.0.1`/`localhost`.

## Instalación a mano

El paquete `mcp` ya viene en `requirements.txt`. Hay dos formas de correrlo:

```sh
.venv/bin/python mcp_server.py                         # stdio: lo arranca el asistente (lo normal)
make mcp                                               # HTTP en http://127.0.0.1:8001/mcp (ver «Hosteado»)
```

Usa el SDK oficial `mcp` 2.x (`MCPServer`). No habla directo con los archivos: llama a la API HTTP de Parla
(`PARLA_URL`), así que respeta los usuarios y roles.

### Claude Code

```sh
claude mcp add --scope user parla -e PARLA_URL=http://127.0.0.1:8000 -- \
  /ruta/a/parla/.venv/bin/python /ruta/a/parla/mcp_server.py
```

Después: «armame un bot que …» o `/mcp__parla__build_bot`.

### Claude Desktop / Cursor

```json
{
  "mcpServers": {
    "parla": {
      "command": "/ruta/a/parla/.venv/bin/python",
      "args": ["/ruta/a/parla/mcp_server.py"],
      "env": {"PARLA_URL": "http://127.0.0.1:8000", "PARLA_TOKEN": "parla_..."}
    }
  }
}
```

### Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.parla]
command = "/ruta/a/parla/.venv/bin/python"
args = ["/ruta/a/parla/mcp_server.py"]
env = { PARLA_URL = "http://127.0.0.1:8000" }
```

### Hosteado (claude.ai, conector personalizado)

En el mismo servidor que Parla:

```sh
.venv/bin/python app.py 8000 &
PARLA_URL=http://127.0.0.1:8000 PARLA_TOKEN=parla_... PARLA_MCP_ALLOWED_HOSTS=bots.midominio.com \
  .venv/bin/python mcp_server.py --http --port 8001
```

Escucha en `http://127.0.0.1:8001/mcp` (streamable HTTP; `--host` cambia la interfaz). Publicalo con un proxy
HTTPS en `https://bots.midominio.com/mcp` y agregá esa URL como conector personalizado en claude.ai. **El servidor
MCP con `--http` no tiene autenticación propia**: quien llegue a él actúa con la clave de `PARLA_TOKEN`. Protegelo
en el proxy (ver [security.md](security_es.md)).

## Variables de entorno

| Variable | Por defecto | Qué es |
|---|---|---|
| `PARLA_URL` | `http://127.0.0.1:8000` | Dónde está Parla. |
| `PARLA_TOKEN` | vacío | Se manda como `Authorization: Bearer <token>`. Hace falta si Parla tiene usuarios: rol `owner` o `editor` para armar y probar bots; con `analyst` solo andan las herramientas que leen (`list_*`, `get_*`, `diff_agent`, `agent_format_guide`, `validate_agent`). La clave solo ve los bots que ve su usuario. |
| `PARLA_MCP_ALLOWED_HOSTS` | vacío | Solo con `--http` detrás de un proxy: dominios públicos separados por coma (el SDK rechaza Host desconocidos para evitar DNS rebinding). |

## Herramientas

26 herramientas, un recurso (`parla://format-guide`) y un prompt (`build_bot`). En todas, `agent` puede ser el id,
el nombre exacto o el slug. Las que cambian algo trabajan sobre el **borrador**.

**Armar**

| Herramienta | Qué hace |
|---|---|
| `list_agents()` | Lista los bots: id, nombre, slug, cuándo se entrenó, intenciones y qué versión tiene cada entorno. |
| `get_agent(agent)` | La definición completa del borrador. |
| `agent_format_guide()` | La guía del formato de agente con ejemplos completos (también como recurso `parla://format-guide`). |
| `validate_agent(agent_json)` | Valida sin guardar y devuelve `{ok, errors, warnings}`: tipos de paso, slots usados en pasos, `{{ }}` y condiciones, triggers, flujos de `goto`/`call`, entidades de las marcas, regex, `interrupts`, `also`, funciones (lenguaje, `run()`, sintaxis Python, entradas), slots y funciones del paso `agent`, botones con label, idiomas de `translations`, `{{ secret.X }}` fuera de un `http`. |
| `create_agent(agent_json)` | Valida, crea y entrena un bot nuevo. Completa la regex de las entidades `number`, `email`, `phone` y `dni` si falta. Devuelve `{id, name, slug, trained, warnings}` (`trained.log` trae la autoevaluación). |
| `update_agent(agent, agent_json)` | Reemplaza el borrador entero (lo que no mandes vuelve a vacío) y reentrena. Valida antes, también que existan los archivos de los pasos `file`. Producción y staging no cambian. |
| `train_agent(agent)` | Reentrena el borrador. |
| `import_rasa_project(path, name=None)` | Lee los `.yml` de la carpeta de un proyecto de Rasa 3.x en tu compu (clásico o CALM), crea un agente nuevo entrenado y devuelve `{id, name, slug, warnings, validation}`: `warnings` es lo que no se pudo pasar tal cual. Ver [migrate-from-rasa_es.md](migrate-from-rasa_es.md). |
| `delete_agent(agent, confirm)` | Borra el bot con sus conversaciones; pide `confirm=True`. |

**Probar**

| Herramienta | Qué hace |
|---|---|
| `test_conversation(agent, messages, start_data=None, keep=False, environment="draft")` | Empieza una conversación por la API (canal `mcp`) con `start_data` y manda cada mensaje. Devuelve por turno intención, confianza, entidades, `answer_to`, respuestas, flujo, slot que espera, clasificaciones, `language`, `handoff` y, si hay, `buttons`, `via`, `sources` y `files` (nombres de archivos enviados); al final, los slots, la versión usada y `problems` (los mensajes «⚠»). La conversación se borra salvo con `keep=True`. Para tocar un botón, mandá su `value`; para otro idioma, `start_data={"idioma": "pt"}`. |
| `test_function(agent, function, inputs=None)` | Corre una función (por nombre, o con la definición completa antes de guardarla) con solo las entradas que declara: `ok`, `result`/`error`, `traceback`, `logs`, `ms`, `sent` e `ignored_inputs`. |

**Versiones**

| Herramienta | Qué hace |
|---|---|
| `publish_agent(agent, note, environment=None, confirm=False)` | Congela el borrador como versión nueva; opcionalmente la pone en `staging` o `production` (esta con `confirm=True`). |
| `deploy_version(agent, environment, version, confirm=False)` | Apunta un entorno a una versión (`None` lo vacía). A production pide `confirm=True`. |
| `list_versions(agent)` | Versiones, entornos y registro de despliegues (con `previous` para volver atrás). |
| `diff_agent(agent, from_ref="production", to_ref="draft")` | Qué cambia entre `production`, `staging`, `draft` o un número de versión. |
| `restore_version(agent, version, confirm=False)` | Vuelve el borrador a una versión y lo reentrena; pide `confirm=True` (se pierden los cambios sin publicar). |

**Conversaciones y métricas**

| Herramienta | Qué hace |
|---|---|
| `list_sessions(agent, channel, classification, date_from, date_to)` | Conversaciones guardadas, la más reciente primero. |
| `get_session(agent, session_id)` | Una conversación con su historial. |
| `get_report(agent, date_from, date_to, channel)` | Conversaciones por clasificación y por día. |
| `get_analytics(agent, date_from, date_to)` | Contención, derivaciones, fallbacks, CSAT, abandono por flujo y pregunta. |

**Conocimiento y mejora**

| Herramienta | Qué hace |
|---|---|
| `add_knowledge(agent, title="", text=None, url=None)` | Suma un documento con `text` o con `url` (uno de los dos; con `url` baja la página y saca el texto). Mismo título = reemplaza (`replaced: true`). No hace falta reentrenar. |
| `search_knowledge(agent, query, k=3)` | Busca como el bot; `answers` dice si llegaría a contestar (puntaje ≥ `knowledge_threshold`). |
| `list_unrecognized(agent, date_from, date_to)` | Lo que no entendió, agrupado y con intención sugerida. |
| `teach_phrases(agent, intent, phrases)` | Agrega frases a una intención que ya existe (saltea repetidas; las marcas tienen que usar entidades existentes). No reentrena: después `train_agent`. |
| `list_files(agent)` | Los archivos que la persona subió al agente (id, nombre, tipo, tamaño), para usarlos en un paso `file`. El MCP no sube archivos. |
| `list_secret_names(agent)` | Los **nombres** de las claves, cuáles usa y cuáles faltan. El MCP nunca lee ni escribe valores. |

**Prompt**: `build_bot(description)` guía a la IA paso a paso: frases variadas y balanceadas, el tipo de entidad
según el dato, funciones probadas con `test_function`, botones para opciones cerradas, conocimiento para preguntas
frecuentes, `handoff` para reclamos, flujos del sistema prendidos, claves siempre por `{{ secret.X }}`,
clasificaciones, revisar la autoevaluación, probar el borrador, publicar a staging y pasar a producción solo con el
OK de la persona.

## Flujo recomendado

`create_agent` y `update_agent` solo cambian el **borrador**: los usuarios reales no ven nada hasta que se
publica.

1. Editar el borrador → `test_conversation` (borrador).
2. `diff_agent` → `publish_agent(note, environment="staging")` → `test_conversation(environment="staging")`.
3. Con el visto bueno de la persona: `deploy_version(environment="production", version=N, confirm=True)`.
4. Rollback: `deploy_version` a production con la versión anterior (`list_versions` muestra `previous`).

## Antes de usarlo con datos reales

- Revisá los pasos `http` que arme la IA: un bot puede llamar a cualquier URL desde tu servidor, incluida tu red
  interna.
- Las funciones corren código en la máquina de Parla. En un Parla compartido, arrancalo con `PARLA_FUNCTIONS=0`.
