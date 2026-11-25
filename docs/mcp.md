# MCP y «Conectar con IA»

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

```sh
.venv/bin/pip install mcp        # si todavía no está instalado
make mcp                          # o: .venv/bin/python mcp_server.py   (stdio)
```

Usa el SDK oficial `mcp` 2.x (`MCPServer`).

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
en el proxy (ver [security.md](security.md)).

## Variables de entorno

| Variable | Por defecto | Qué es |
|---|---|---|
| `PARLA_URL` | `http://127.0.0.1:8000` | Dónde está Parla. |
| `PARLA_TOKEN` | vacío | Se manda como `Authorization: Bearer <token>`. Hace falta si Parla tiene usuarios: rol `owner` o `editor` para armar bots; `analyst` solo puede leer. |
| `PARLA_MCP_ALLOWED_HOSTS` | vacío | Solo con `--http` detrás de un proxy: dominios públicos separados por coma (el SDK rechaza Host desconocidos para evitar DNS rebinding). |

## Herramientas

**Armar**

| Herramienta | Qué hace |
|---|---|
| `list_agents` | Lista los bots. |
| `get_agent(agent)` | La definición completa. |
| `agent_format_guide` | La guía del formato de agente (también como recurso `parla://format-guide`). |
| `validate_agent(agent_json)` | Valida sin guardar: pasos, flujos de `call`/`goto`, funciones y slots del paso `agent`, botones con label, idiomas de `translations`, claves. |
| `create_agent(agent_json)` | Crea un bot (valida antes). |
| `update_agent(agent, agent_json)` | Reemplaza el borrador. |
| `train_agent(agent)` | Entrena. |
| `delete_agent(agent, confirm)` | Borra; pide `confirm=True`. |

**Probar**

| Herramienta | Qué hace |
|---|---|
| `test_conversation(agent, messages, start_data, keep, environment)` | Corre una conversación (`draft` por defecto, o `staging` / `production`). Devuelve por turno `buttons`, `language`, `handoff`, `via` y `sources`. Para tocar un botón, mandá su `value`; para otro idioma, `start_data={"idioma": "pt"}`. |
| `test_function(agent, function, inputs)` | Corre una función (por nombre o con la definición completa antes de guardarla): `ok`, `result`/`error`, `logs`, `ms`. |

**Versiones**

| Herramienta | Qué hace |
|---|---|
| `publish_agent(agent, note, environment, confirm)` | Congela el borrador como versión; opcionalmente la pone en `staging` o `production` (esta con `confirm=True`). |
| `deploy_version(agent, environment, version, confirm)` | Apunta un entorno a una versión (a production pide `confirm=True`). |
| `list_versions(agent)` | Versiones, entornos y registro de despliegues. |
| `diff_agent(agent, from_ref, to_ref)` | Qué cambia entre production, staging, draft o una versión. |
| `restore_version(agent, version, confirm)` | Vuelve el borrador a una versión. |

**Conversaciones y métricas**

| Herramienta | Qué hace |
|---|---|
| `list_sessions(agent, channel, classification, date_from, date_to)` | Conversaciones guardadas. |
| `get_session(agent, session_id)` | Una conversación con su historial. |
| `get_report(agent, date_from, date_to, channel)` | Conversaciones por clasificación y por día. |
| `get_analytics(agent, date_from, date_to)` | Contención, derivaciones, fallbacks, CSAT, abandono por flujo y pregunta. |

**Conocimiento y mejora**

| Herramienta | Qué hace |
|---|---|
| `add_knowledge(agent, title, text \| url)` | Suma un documento (con `url`, baja la página y saca el texto). Mismo título = reemplaza. |
| `search_knowledge(agent, query)` | Busca como el bot; `answers` dice si llegaría a contestar (puntaje ≥ `knowledge_threshold`). |
| `list_unrecognized(agent, date_from, date_to)` | Lo que no entendió, agrupado y con intención sugerida. |
| `teach_phrases(agent, intent, phrases)` | Agrega frases a una intención (saltea repetidas). No reentrena: después `train_agent`. |
| `list_files(agent)` | Los archivos que la persona subió al agente (id, nombre, tipo, tamaño), para usarlos en un paso `file`. El MCP no sube archivos. |
| `list_secret_names(agent)` | Los **nombres** de las claves, cuáles usa y cuáles faltan. El MCP nunca lee ni escribe valores. |

**Prompt**: `build_bot(description)` enseña buenas prácticas: botones para opciones cerradas, conocimiento para
preguntas frecuentes, `handoff` para reclamos, flujos del sistema prendidos, claves siempre por
`{{ secret.X }}` y probar cada función con `test_function`.

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
