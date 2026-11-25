# Desarrollo

## Dependencias

Pocas y a propósito: el servidor HTTP es el de la biblioteca estándar (`http.server`), sin framework.

| Paquete | Para qué |
|---|---|
| `fastembed` (+ `numpy`, `onnxruntime`) | Vectores de las frases con `paraphrase-multilingual-MiniLM-L12-v2`. |
| `python-crfsuite` | Entidades aprendidas (CRF). |
| `cel-python` | Expresiones CEL en `{{ }}`, `set`, `if` y `saves`. |
| `pypdf` | PDFs de la base de conocimiento. |
| `mcp` | El servidor MCP. |
| `faster-whisper`, `piper-tts` | Voz (extras, `requirements-voice.txt`). |

La IA habla con Ollama por HTTP con `urllib` (`llm.py`), sin SDK.

## Código

| Archivo | Qué tiene |
|---|---|
| `app.py` | Entrada: arranca `parla/server.py` en `127.0.0.1:[puerto]`. |
| `parla/server.py` | NLU (`classify`, `extract`, `parse`), entrenamiento (`train`, `self_check`), versiones (`publish`, `deploy`, `target`, `diff`), plantillas (`cel`, `render`), el motor (`handle`, `run`, `begin`), conversaciones en disco, `api_v1` y el `Handler` HTTP. |
| `parla/auth.py` | Usuarios, roles, cookies, claves; `handle` (rutas `/api/auth`, `/api/users`) y `guard` (antes de cada `/api/`). |
| `parla/brain.py` | IA encima del motor: `rescue_intent`, `fill_slot`, `fallback`, `agent_turn`. Ninguna función lanza. |
| `parla/llm.py` | Cliente de Ollama / compatible OpenAI: `chat`, `status`, `pull`. |
| `parla/knowledge.py` | `extract` (texto, HTML, URL, PDF), `chunks`, `search`. |
| `parla/dates.py` | `extract`: fechas en lenguaje natural por reglas. |
| `parla/insights.py` | `unrecognized` y `analytics`, calculados al vuelo sobre las conversaciones. |
| `parla/runner.py` | `run_function`: funciones en un proceso aparte. |
| `parla/vault.py` | Claves por agente: `put`, `delete`, `names`, `values`, `mask`. |
| `parla/voice.py` | `transcribe` y `speak`. |
| `parla/connect.py` | «Conectar con IA». |
| `parla/mcp_server.py` | Servidor MCP: validador del formato (`validate`), guía del formato y herramientas. |
| `web/index.html` | La interfaz (JS sin build); cada sección grande en `web/static/*.js`. |
| `web/static/widget.js` | El widget, sin dependencias, en un Shadow DOM. |

## Cómo funciona el motor

El estado de una conversación (`st`) es un diccionario: `slots`, `flow` (flujo en curso), `pc` (paso), `stack`
(subflujos e interrupciones), `waiting` (slot preguntado), `lang`, `buttons`, `clarify`, `handoff`, `agent`
(estado del paso de IA), `recent` (contexto para la IA). Se guarda en `<agente>.sessions/<sid>.json`.

`begin(agent, st, data)` empieza: copia `data` a los slots que se llaman igual, elige el idioma y corre el flujo
con trigger `__start__`.

`handle(agent, st, text)` es un turno, en este orden:

1. Si la atiende una persona (`handoff.active`), el bot no habla.
2. Botón tocado, respuesta a la encuesta CSAT, respuesta a «¿quisiste decir…?».
3. `parse`: intención + entidades. Las entidades llenan sus slots (mientras espera una respuesta, solo el slot
   preguntado).
4. Intenciones del sistema (`__cancel__`, `__repeat__`, `__handoff__`), con umbral más alto si está esperando un
   dato (0.75) y nunca por debajo de 0.65.
5. Si hay un paso `agent` activo, le toca a la IA. Si está esperando un dato: correcciones, `fill: "ai"`,
   validación de formato, interrupción por otra intención (se apila y después vuelve) o «No reconocí ese dato».
6. Si no estaba en un flujo: rescate con IA, aclaración por empate, flujo por intención o fallback (conocimiento →
   repregunta con IA → `fallback`).
7. `run`, y al terminar CSAT o «¿algo más?».
8. `turn` arma el resultado (`messages`, `buttons`, `nlu`, `slots`, `trace`, `via`, `sources`, …).

`run(agent, st, nlu, text, out, trace)` ejecuta pasos hasta `done`, `wait`, `handoff` o `error`. Antes, `flatten`
convierte los `if` anidados en una lista plana con etiquetas y saltos. Límites: 200 pasos seguidos
(`MAX_STEPS`) y 5 flujos apilados (`MAX_DEPTH`). Un paso que falla no tira el servidor: el chat muestra
«⚠ Hay un problema en el flujo…» y la conversación se corta.

Los módulos enchufables (IA, fechas, claves) se llaman con `hook()`: si explotan, el bot sigue como si no
estuvieran.

`converse` es el puente entre la API/chat y `handle`: carga la versión con la que empezó la conversación, usa su
modelo entrenado, guarda el historial (hasta 500 mensajes) y las clasificaciones.

## Cómo sumar un tipo de paso

Ejemplo: un paso `wait` que dice «un momento».

1. **Motor** (`parla/server.py`): agregá el nombre a `STEP_NAMES` y una rama en `run()`:
   ```python
   elif kind == "wait":
       out.append(render(localized(step, st), ctx) or "Un momento…")
   ```
   Si el paso tiene que esperar a la persona, devolvé `"wait"`; si corta la charla, `"done"`.
2. **Validador del MCP** (`parla/mcp_server.py`): sumalo a `STEP_TYPES`, validá sus campos en `validate()` y
   documentalo en la guía del formato (`agent_format_guide`).
3. **Interfaz** (`web/index.html`): sumalo a `STEP_MENU` y armá su editor.
4. **Prueba** (`tests/test_app.py`): una conversación que lo use y un `assert` sobre lo que dice.
5. **Docs**: [concepts.md](concepts.md#tipos-de-paso).

## Pruebas

```sh
make test                                # todas: tests/run_all.py
.venv/bin/python tests/test_app.py       # motor sin modelo ni red
```

Son scripts con `assert`, sin framework: si algo no se cumple, el script falla en ese `assert`.

| Archivo | Necesita |
|---|---|
| `test_app.py` | Nada (motor sin modelo ni red). |
| `test_insights.py`, `test_connect.py` | Nada (`test_connect` usa un HOME temporal). |
| `test_knowledge.py` | El modelo de vectores. |
| `test_auth.py` | Nada: levanta su propio servidor en el puerto 8124 con un `users.json` temporal. |
| `test_ai.py` | Ollama para la parte con modelo; si no está, la saltea con un aviso. |
| `test_voice.py` | Los extras de voz y `ffmpeg`. |
| `test_mcp.py` | El paquete `mcp` y Parla corriendo (`PARLA_URL`) para la parte punta a punta. |

## Estilo

- **Funciones chicas** que hacen una cosa y se leen de arriba abajo.
- **Comentarios en español**, para explicar el porqué, no el qué. Los mensajes al usuario también, en
  rioplatense y diciendo qué hacer («Revisá que los slots que usa existan»).
- **Lo más simple que funcione**: biblioteca estándar antes que una dependencia nueva, archivos JSON antes que una
  base de datos, sin abstracciones que nadie pidió.
- **Comentarios `ponytail:`** cuando se toma un atajo con un límite conocido, nombrando el límite y cómo
  mejorarlo. Ejemplos reales del código:
  ```python
  # ponytail: un hilo por pedido; dos mensajes a la vez en la MISMA conversación pueden pisarse:
  # agregar un lock por sessionId si algún canal los manda en paralelo
  # ponytail: sesiones en memoria (se pierden al reiniciar el servidor); a disco si molesta
  ```
  Buscalos con `grep -rn "ponytail:" parla web` para ver la deuda técnica asumida.
- Un error de un módulo opcional (IA, voz, fechas) nunca corta una conversación.
- Toda lógica no trivial deja una prueba en `tests/`.
