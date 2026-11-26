# IA y voz

[English](ai-and-voice.md) · **Español**

Todo es opcional y, por defecto, todo corre en tu compu. Sin IA, Parla funciona igual: el NLU (embeddings + CRF +
reglas) no necesita un modelo de lenguaje. Si querés, podés usar tu propia API key: la IA puede ir con OpenAI,
Anthropic (Claude), Google Gemini o cualquier [endpoint compatible con OpenAI](#endpoints-compatibles-con-openai)
(vLLM, llama.cpp, LM Studio, Azure OpenAI, …), y la voz con OpenAI, Deepgram, ElevenLabs o Google Cloud. Mirá
[Proveedores](#proveedores-con-tu-propia-key).

## El modelo de vectores (siempre)

No es opcional ni es «IA generativa»: es lo que usa el NLU para comparar frases.

- Modelo: `google/embeddinggemma-300m` con [fastembed](https://github.com/qdrant/fastembed) (ONNX, CPU), con el
  prefijo `task: sentence similarity | query: `. Se eligió midiendo con un bot de citas: acertó más respuestas que
  `paraphrase-multilingual-MiniLM` y `mpnet`, sin errores, en unos 10 ms por mensaje.
- Lo usan las intenciones, [entender respuestas por significado](#entender-respuestas-por-significado), la base de
  conocimiento y «Para enseñar». Se carga una sola vez.
- Se baja la primera vez que se usa (~1,2 GB) a `data/models/embeddings` dentro del repo, aunque cambies
  `PARLA_DATA`. Para otra carpeta: `PARLA_EMBED_CACHE=/ruta`.

## Instalar Ollama

1. Bajalo de [ollama.com](https://ollama.com) e instalalo (o en Linux `curl -fsSL https://ollama.com/install.sh | sh`).
2. Bajá el modelo por defecto:
   ```sh
   ollama pull qwen2.5:0.5b
   ```
   (`scripts/setup.sh --ollama` lo hace por vos.) También se puede bajar desde la sección **IA** con «Descargar».
3. En el agente, **Inteligencia → IA**: prendela y probá la conexión.

Parla habla con Ollama en `http://127.0.0.1:11434`. Ollama es lo que viene por defecto y nada sale de tu máquina.
Para usar un proveedor en la nube u otro servidor, mirá [Proveedores](#proveedores-con-tu-propia-key).

## Modelos sugeridos

| Modelo | Tamaño aprox. | Nota |
|---|---|---|
| `qwen2.5:0.5b` (por defecto) | 400 MB | El más liviano. Rápido en cualquier compu. |
| `qwen3:0.6b` | 520 MB | Muy liviano, un poco más listo. |
| `gemma3:1b` | 820 MB | Liviano, buen español. |
| `qwen2.5:1.5b` | 990 MB | Más preciso; necesita algo más de memoria. |
| `llama3.2:1b` | 1,3 GB | Buen seguidor de instrucciones. |

Con Ollama el modelo queda cargado 30 minutos entre mensajes (`keep_alive`) y se usa un contexto de 4096 tokens: la
primera respuesta tarda más, las demás no.

## Configuración (`agent.ai`)

Los valores por defecto:

```json
{"enabled": false, "provider": "ollama", "url": "http://127.0.0.1:11434", "model": "qwen2.5:0.5b",
 "temperature": 0.2, "rescue_intents": true, "use_knowledge": true, "generative_fallback": true, "persona": ""}
```

`persona` es cómo habla el bot («Hablás de vos, sos amable y breve.»); se suma a los pedidos que redactan texto.

`provider` es `ollama` (por defecto), `openai`, `anthropic`, `gemini` u `openai_compatible`. Otros campos: `url`,
`model`, `api_key_secret`, `azure`.

## Proveedores con tu propia key

Lo local sigue siendo lo que viene por defecto. Cada agente elige sus proveedores, y el proveedor le cobra el uso a
quien sea dueño de la key.

| Parte | Proveedor (`provider`) | Dónde corre | Qué sale de la máquina |
|---|---|---|---|
| IA (LLM) | Ollama (`ollama`, por defecto) | tu compu | nada |
| IA | OpenAI (`openai`) | nube | el texto de la charla, los turnos recientes, la persona, los fragmentos de conocimiento usados, los resultados de herramientas del paso `agent` |
| IA | Anthropic Claude (`anthropic`) | nube | lo mismo |
| IA | Google Gemini (`gemini`) | nube | lo mismo |
| IA | Compatible con OpenAI (`openai_compatible`) | donde apunte la URL | lo mismo, salvo que el servidor sea tuyo |
| Transcripción (ASR) | `local` (faster-whisper, por defecto) | tu compu | nada |
| ASR | `openai`, `deepgram`, `elevenlabs`, `google` | nube | el audio de la persona y las pistas de vocabulario del bot |
| Voz del bot (TTS) | `local` (piper, por defecto) | tu compu | nada |
| TTS | `openai`, `deepgram`, `elevenlabs`, `google` | nube | el texto de la respuesta del bot |

El modelo de vectores (intenciones, significado, búsqueda en el conocimiento) es siempre local.

### Claves

Las keys viven solo en la sección **Claves** del agente, por nombre: el JSON del agente tiene `api_key_secret` (un
nombre), nunca la key (el `validate` de MCP rechaza un `api_key`). El campo de la key en la pantalla **IA** la guarda
en Claves por vos. Las keys se tapan (`••••`) en todos los errores, logs y trazas, también cuando el proveedor la
repite. Crear y borrar una clave queda en la auditoría. Si no ponés `api_key_secret`, se usan estos nombres:

| Proveedor | Clave por defecto | Dónde sacar la key |
|---|---|---|
| OpenAI (IA y voz) | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) → API keys |
| Anthropic | `ANTHROPIC_API_KEY` | [Claude Console](https://console.anthropic.com) → API keys |
| Google Gemini | `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com) → Get API key |
| Deepgram | `DEEPGRAM_API_KEY` | [console.deepgram.com](https://console.deepgram.com) → API keys |
| ElevenLabs | `ELEVENLABS_API_KEY` | [elevenlabs.io](https://elevenlabs.io) → API keys |
| Google Cloud (voz) | `GOOGLE_API_KEY` | consola de Google Cloud → habilitá Speech-to-Text / Text-to-Speech → Credenciales → una API key restringida a esas APIs. Las cuentas de servicio todavía no se soportan. |

### Proveedores de IA

En la interfaz: **IA → Programa**: Local (Ollama) / OpenAI / Anthropic (Claude) / Google Gemini / Compatible con
OpenAI. Cada opción completa la dirección, el modelo y el nombre de la key; **Probar conexión** manda un mensaje; el
campo del modelo sugiere ids; un aviso te dice cuando el proveedor no es local.

| Proveedor | Modelo por defecto | Otras sugerencias |
|---|---|---|
| `openai` (sin `url` = `https://api.openai.com/v1`) | `gpt-6-luna` | `gpt-6.1-terra`, `gpt-6.2-sol` |
| `anthropic` | `claude-opus-5-5` | `claude-sonnet-5-5`, `claude-haiku-5-5` |
| `gemini` | `gemini-3.8-flash` | `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` |

```jsonc
// OpenAI
{"enabled": true, "provider": "openai", "model": "gpt-6-luna"}
// Claude
{"enabled": true, "provider": "anthropic", "model": "claude-sonnet-5-5"}
// Gemini, con la key guardada con otro nombre
{"enabled": true, "provider": "gemini", "model": "gemini-3.8-flash", "api_key_secret": "MI_KEY_GEMINI"}
```

`"provider": "openai"` **con** `url` mantiene el significado de antes (cualquier servidor compatible con OpenAI), así
que los agentes que ya tenías no cambian.

**Gemini** usa la API REST nativa `generateContent` (key en `x-goog-api-key`). Las respuestas JSON van con
`responseMimeType: "application/json"` + `responseJsonSchema`; si Gemini lo rechaza con un 400, Parla pide el JSON
solo en el prompt.

### Detalles de Claude

- Usa el SDK oficial de Python `anthropic` (API Messages nativa). Es una dependencia opcional, solo para Claude:
  `pip install -r requirements-providers.txt` (fija `anthropic==1.17.0`), o `scripts/setup.sh --providers`,
  `make setup-providers`, o el build arg de Docker `INSTALL_PROVIDERS=1` (`make docker-build PROVIDERS=1`). Si falta,
  el error lo dice. Los demás proveedores usan solo la biblioteca estándar.
- El esfuerzo (effort) es `low`: Opus 5.5 siempre piensa, y en low la charla sigue rápida. `max_tokens` es de al menos
  2048 (el pensamiento cuenta).
- Las respuestas JSON usan structured outputs (`output_config.format` con un JSON schema) cuando el esquema no tiene
  objetos libres; si no, el esquema va en el prompt y el JSON se saca de la respuesta.
- En Opus 5.5 y Sonnet 5.5 está prendido el respaldo ante rechazos del lado del servidor (`fallbacks: "default"`). Un
  rechazo o una respuesta cortada por `max_tokens` se vuelven un error claro (y el bot sigue como si la IA estuviera
  apagada).
- 1 reintento del SDK y timeout por pedido. La dirección es fija (`api.anthropic.com`).

### Combinaciones recomendadas

| Para | IA | ASR | TTS |
|---|---|---|---|
| Todo local, gratis y privado (por defecto) | Ollama | `local` | `local` |
| Teléfono con poca latencia | cualquiera | Twilio/jambonz (siempre) | `channels.phone.tts: "parla"` + Deepgram Aura-2 o ElevenLabs Flash |
| Modo llamada del navegador / widget | cualquiera | Deepgram `nova-3` | ElevenLabs `eleven_flash_v2_5` |
| Lo más barato en la nube | `gemini-3.5-flash-lite`, `claude-haiku-5-5` o `gpt-6-luna` | | |
| La mejor calidad | `claude-opus-5-5` o `gemini-3.1-pro-preview` | | |

Mirá la página de precios de cada proveedor: los costos cambian y se le cobran al dueño de la key. En el teléfono las
frases fijas pregeneradas suenan al instante; ver [Proveedores de voz en la nube](#proveedores-de-voz-en-la-nube).

## Endpoints compatibles con OpenAI

Con `"provider": "openai_compatible"` (o el viejo `"provider": "openai"` con `url`; en la interfaz: **Programa →
Compatible con OpenAI**) cada función de IA llama a
`POST {url}/chat/completions` (`model`, `messages`, `temperature`, `max_tokens`, `stream: false`). Sirve para vLLM,
llama.cpp server, LM Studio, LocalAI, OpenAI, Azure OpenAI, Groq, OpenRouter y cualquier otro que hable esa API.

| Campo | Qué es |
|---|---|
| `url` | La dirección base, casi siempre terminada en `/v1` (`http://localhost:8000/v1`). Si no tiene ruta (`http://127.0.0.1:1234`), se le agrega `/v1`. |
| `model` | El id del modelo que espera el servidor. En la interfaz es texto libre, con sugerencias de `GET {url}/models` cuando el servidor las da. |
| `api_key_secret` | El **nombre** de una clave de la sección **Claves** del agente, por ejemplo `OPENAI_KEY`. La key nunca se guarda en el JSON del agente. El campo «API key» de la pantalla IA la guarda en Claves por vos (como `AI_API_KEY` si no elegiste otro nombre). |
| `azure` | `true` para Azure OpenAI: la key va en el encabezado `api-key` en vez de `Authorization: Bearer` y se agrega `?api-version=` (`api_version`, por defecto `2024-10-21`). Se prende solo con direcciones `*.openai.azure.com`. |

Ejemplos (`agent.ai`; sin `api_key_secret` si el servidor no pide key):

```jsonc
// vLLM (vllm serve Qwen/Qwen2.5-1.5B-Instruct)
{"enabled": true, "provider": "openai", "url": "http://localhost:8000/v1", "model": "Qwen/Qwen2.5-1.5B-Instruct"}
// llama.cpp server (llama-server -m modelo.gguf --port 8080)
{"enabled": true, "provider": "openai", "url": "http://localhost:8080/v1", "model": "local"}
// LM Studio (pestaña del servidor local)
{"enabled": true, "provider": "openai", "url": "http://127.0.0.1:1234/v1", "model": "qwen2.5-1.5b-instruct"}
// Azure OpenAI: la URL incluye tu deployment; Azure ignora "model"
{"enabled": true, "provider": "openai", "url": "https://mi-recurso.openai.azure.com/openai/deployments/mi-gpt4o-mini",
 "model": "gpt-4o-mini", "api_key_secret": "AZURE_OPENAI_KEY", "azure": true}
// OpenRouter
{"enabled": true, "provider": "openai", "url": "https://openrouter.ai/api/v1", "model": "meta-llama/llama-3.1-8b-instruct", "api_key_secret": "OPENROUTER_KEY"}
// Groq
{"enabled": true, "provider": "openai", "url": "https://api.groq.com/openai/v1", "model": "llama-3.1-8b-instant", "api_key_secret": "GROQ_KEY"}
```

Cómo se comporta:

- **Respuestas estructuradas:** donde a Ollama se le pasa un JSON schema (`format`), por acá se manda
  `response_format: {"type": "json_object"}` más el esquema en un mensaje de sistema. Si el servidor rechaza
  `response_format` con un 400, Parla reintenta sin él (el JSON se pide solo en el prompt y se saca de un bloque
  ```` ```json ```` si hace falta) y lo recuerda para esa URL hasta que se reinicia el servidor.
- **Estado:** «Volver a mirar» llama a `GET {url}/models`. Los servidores que no lo tienen (404) quedan como
  «conectado, probalo»: usá **Probar conexión**, que manda un mensaje y muestra la respuesta y cuánto tardó.
- **Errores** en el idioma de la interfaz: 401/403 (key mala o faltante, sin repetir el mensaje del proveedor, que suele incluir
  parte de la key), 404 (dirección o modelo equivocados), 429 (límite de pedidos o sin crédito), 5xx y timeouts.
  La key se tapa (`••••`) en todos los errores. Si el proveedor falla, el bot sigue como si la IA estuviera apagada.
- **Descargar modelos** («Descargar») es solo para Ollama; en los otros servidores el modelo se carga ahí.
- **Los embeddings siguen siendo locales** (fastembed): las intenciones, el significado y la búsqueda en la base de
  conocimiento nunca llaman al proveedor.

Esto (errores, key tapada, embeddings locales, seguir si falla) vale también para OpenAI, Claude y Gemini.

**Privacidad:** con un proveedor en la nube (OpenAI, Anthropic, Gemini, Azure, Groq, OpenRouter, …) el texto de las
conversaciones, los turnos recientes, la persona, los fragmentos de la base de conocimiento que se usan para responder
y los resultados de herramientas del paso `agent` se mandan a ese proveedor y quedan sujetos a sus condiciones. La pantalla IA avisa cuando la dirección no es de esta compu ni
de tu red privada. Si eso no sirve, usá Ollama o un servidor propio (vLLM, llama.cpp, LM Studio).

## Qué hace cada función y sus guardas

La regla general: **la IA propone y el motor decide**. Si la IA está apagada, no responde o devuelve algo raro,
el bot sigue con el comportamiento de siempre (ninguna falla de la IA corta la conversación). Las respuestas del
modelo se piden en JSON con un esquema siempre que se puede.

### Rescatar intenciones (`rescue_intents`)

Cuando la confianza no llega al umbral, o dos intenciones están empatadas, la IA elige entre las 5 más parecidas
(o «ninguna»).

- Solo puede elegir una letra de la lista (salida JSON con `enum`).
- Se descartan candidatas lejanas (similitud menor a `max(0.25, umbral − 0.3)`).
- Se pregunta dos veces con el orden invertido, porque los modelos chicos tienden a elegir la primera: solo vale
  si las dos respuestas coinciden. La intención elegida queda con la confianza llevada al umbral.

### Completar slots (`fill: "ai"`)

Para un slot con `"fill": "ai"` y una `description` («el nombre y apellido»), la IA lee el valor del mensaje.

- Fechas: si la entidad es `date` o el nombre o la descripción hablan de fecha, día, hora o turno, se resuelven
  primero con `dates.py` (reglas, sin modelo).
- El valor tiene que estar escrito en el mensaje: cada palabra se busca en el texto. Si la IA normaliza («dos» →
  «2»), se descarta.
- Una segunda pregunta («¿esto es un dato del tipo …? sí/no») confirma.

### Entender respuestas por significado

No usa la IA generativa: compara con el modelo de vectores. Solo para entidades de lista que tienen `phrasings`
(las formas de decir cada opción). Ver [concepts.md](concepts_es.md#entender-una-respuesta-por-significado). Decide
solo si está claro:

| Umbral | Valor |
|---|---|
| Similitud mínima | 0.60 |
| Ventaja sobre la segunda opción | 0.04 |
| Ventaja que necesita «otra acción» sobre la mejor respuesta | 0.10 |

Si decide, el turno trae `via: "significado"` y la traza dice a qué frase se pareció.

### Entender el turno con IA

Cuando el bot espera una opción (lista, formato o fecha), la respuesta no la trae y lo anterior no alcanzó, la IA
lee el turno con la charla reciente y elige qué hizo la persona: contestó una opción, preguntó algo, pidió otra cosa
(una intención con flujo) o nada (saludó, agradeció). Si eligió «otra acción» o «sí», se pregunta de nuevo con la
lista al revés y solo vale si coincide: una mala lectura podría confirmar una cita.

### Preguntas en medio de una pregunta

Si la respuesta parece una pregunta («¿qué es presencial?», «cuánto sale»), primero se busca en la base de
conocimiento (esto funciona sin IA). Con IA, si la base no tiene nada, el modelo decide si es una pregunta o una
respuesta con signos de pregunta («¿y el jueves hay algo?»); si es una pregunta, el bot dice que no puede responder
eso por acá (nunca inventa) y vuelve a preguntar.

### Base de conocimiento (`use_knowledge`)

Cargás documentos en **Inteligencia → Conocimiento**: texto, HTML, un PDF o una URL (una página de hasta 3 MB). Parla los parte
en fragmentos de unos 500 caracteres (las preguntas frecuentes «P: / R:» quedan juntas) y los busca con el mismo
modelo de vectores del NLU.

- **Sin IA** también funciona: si un fragmento llega a `knowledge_threshold` (0.75 por defecto), responde con ese
  fragmento (hasta 600 caracteres, sin repetir la pregunta).
- **Con IA**: arma una respuesta de una o dos oraciones usando solo los 2 mejores fragmentos. Se descarta (y se
  muestra el fragmento tal cual) si tiene números que no están en el texto, una negación que el texto no tiene,
  demasiadas palabras nuevas, más de 400 caracteres o restos del prompt.
- La respuesta trae `via: "knowledge"` y `sources` con título y puntaje.

### Repregunta generativa (`generative_fallback`)

Si no entendió y no hay nada en el conocimiento, la IA escribe una repregunta corta y amable.

- Tiene que ser una pregunta y no puede tener números, `$`, `@` ni links (sería un dato inventado); si no, se usa
  una frase fija. Se recorta a dos oraciones.
- La lista de «Puedo ayudarte con: …» la arma el motor con los nombres de las primeras 8 intenciones, no el modelo.
- Si el modelo no está disponible, se usa el `fallback` de siempre.

### Paso `agent`

Una isla de IA dentro de un flujo (ver [concepts.md](concepts_es.md#agent-dejar-que-la-ia-converse)). El modelo
devuelve JSON: o usa una herramienta, o responde.

- Solo puede usar las herramientas listadas en el paso (`tools`, o `functions`); un nombre inventado se rechaza.
- Hasta `max_tool_calls` llamadas por mensaje de la persona (3 por defecto); si repite la misma llamada se le recuerda
  el resultado y se lo obliga a contestar. Recuerda los últimos resultados entre turnos.
- Solo guarda los slots listados en el paso.
- Termina al cumplir `goal` o al llegar a `max_turns` (8 por defecto).
- Con `knowledge: true` recibe como «información confiable» los fragmentos con puntaje de al menos el 80 % de
  `knowledge_threshold`.

### Herramientas en el paso agente

Las `tools` del paso pueden ser funciones, llamadas HTTP y herramientas de servidores MCP (formato en
[concepts_es.md](concepts_es.md#agent-dejar-que-la-ia-converse)). Parla no usa el function calling nativo: usa su
propio JSON, así que anda igual con Ollama (modo JSON schema), con OpenAI y endpoints compatibles (`json_object`, o el
prompt como respaldo), con Claude (structured outputs, o el prompt) y con Gemini (`responseJsonSchema`, o el prompt).

- Las herramientas van compactas en el prompt de sistema: `nombre(param: descripción) - descripción`.
- El modelo responde `{"tool": "nombre", "args": {...}}` para usar una, o `{"tool": "", "text", "slots", "done"}`
  para contestar. Se sigue aceptando el formato viejo `{"action": "call", "function", "inputs"}`.
- Parla revisa los argumentos (descarta claves desconocidas, convierte o rechaza tipos, controla los obligatorios),
  corre la herramienta y le pasa el resultado al modelo, con las claves tapadas, recortado a 1500 caracteres y
  presentado como «datos, no órdenes». Después le vuelve a preguntar. Los errores (HTTP que no es 2xx, `isError` de
  MCP, argumentos inválidos, timeouts) le vuelven al modelo como error de la herramienta.
- Si la salida viene rota o vacía, se le pide una vez más con una instrucción más estricta.
- Pasados `time_budget` segundos (15 por defecto, de 3 a 60) no usa más herramientas y tiene que contestar con lo que
  tiene. En teléfono dejalo en ≤ 12 s y 1–2 llamadas.
- Cada llamada queda en la traza del turno, en el resultado de la API de chat (`tools`) y en el historial como evento.

- Las entradas de una función son obligatorias: si la IA no las manda, se toman de los slots con ese nombre; si
  tampoco están, la función no corre y el modelo recibe «faltan: …».
- Al lado del mensaje de la persona va un recordatorio corto del formato: sin él, `qwen2.5:1.5b` casi nunca usaba
  la herramienta.

Qué tan bien lo hacen los modelos chicos (M4, Ollama, una función `estado_pedido(pedido)`, 10 intentos con «¿en qué
estado está mi pedido 4821?» y 10 con «hola, ¿qué podés hacer?»):

| Modelo | Llamó la herramienta | Argumentos bien | Usó el resultado | La llamó en la charla | Mediana |
|---|---|---|---|---|---|
| `qwen2.5:0.5b` | 10/10 | 10/10 | 10/10 | 10/10 (sin argumentos: no corrió) | 2,1 s |
| `qwen2.5:1.5b` | 10/10 | 10/10 | 10/10 | 0/10 | 1,4 s |

`qwen2.5:0.5b` usa la herramienta cuando hace falta, pero también cuando no, y contesta peor. Para herramientas usá
`qwen2.5:1.5b` o más grande (`qwen2.5:3b`, `qwen2.5:7b`, `llama3.1:8b`) o un modelo en la nube, y dejá 1 a 3
herramientas con descripciones cortas y parámetros con nombres claros (`pedido`, no `id`). Es una prueba chica con
una sola herramienta: con varias, o con descripciones ambiguas, fallan más. Si la consulta pasa siempre, un flujo
común con `ask` + `http` es más rápido y no depende del modelo.

## Latencias de referencia

Medidas en una Mac con M4 y `qwen2.5:0.5b`, con el modelo ya cargado. En otra máquina pueden variar mucho.

| Qué | Tiempo |
|---|---|
| Rescatar intención | ~0,5 s |
| Completar un slot | ~0,4 s |
| Respuesta de la base de conocimiento | 0,2–0,3 s |
| Un turno del paso `agent` | 1,6–2,2 s |
| Transcribir audio (Whisper `base`, en caliente) | ~0,4 s |
| Leer en voz alta (piper) | ~0,4 s |

## Voz

Por defecto la voz es local (faster-whisper + piper). Cada agente puede pasar la transcripción y/o la voz del bot a
un proveedor en la nube: mirá [Proveedores de voz en la nube](#proveedores-de-voz-en-la-nube). Para la voz local,
instalá los extras:

```sh
scripts/setup.sh --voice
# o: .venv/bin/pip install -r requirements-voice.txt
```

Hace falta `ffmpeg` en el sistema para los formatos de audio que PyAV no abre (Parla lo busca en
`/opt/homebrew/bin`, `/usr/local/bin` y `/usr/bin`, o en el `PATH`).

- **Transcripción**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) modelo `base`, CPU, int8, con
  filtro de silencio (VAD). `PARLA_WHISPER=tiny` si la máquina es lenta. Las palabras del bot (valores y sinónimos
  de entidades, hasta 600 caracteres) se pasan como `hotwords`, para que escriba «muzzarella» y no «multareza». Se
  descartan los pedazos que el propio modelo marca como «no es voz» o como repetición anormal (Whisper inventa con
  audio casi mudo). Audios de 0,3 a 60 segundos.
- **Voz**: [piper](https://github.com/rhasspy/piper). Voces: `es_AR-daniela-high` (con `es_MX-claude-high` y
  `es_ES-davefx-medium` de respaldo), `pt_BR-faber-medium`, `en_US-lessac-medium`. Otro idioma usa la voz en español.
- **Frases pregeneradas**: con alguna voz ya bajada, cada vez que se guarda un agente Parla genera en segundo plano el
  audio de las frases fijas (mensajes, preguntas, pases a persona, el `fallback` y el «No reconocí ese dato»), en el
  idioma por defecto y oración por oración. Las frases con `{{ }}` se generan en el momento y no se guardan. La caché
  vive en `<PARLA_DATA>/models/tts-cache/` y no se borra sola.
- La primera vez se bajan los modelos (~150 MB) a `<PARLA_DATA>/models/`.
- Un solo audio se procesa a la vez (alcanza para un servidor local).

Dónde se usa:

- **Chat de prueba**: al tocar **Probar** elegís **Chat** o **Llamada (voz)**. En el chat hay micrófono para
  dictar y un botón para leer las respuestas en voz alta.
- **Llamada (voz)**: la conversación entera por voz, como por teléfono. El navegador escucha con un detector de voz
  propio (corta al quedar ~0,5 s en silencio; si no hablás en 15 s, sigue esperando sin mandar nada), el servidor
  transcribe, el bot contesta y la respuesta se lee oración por oración mientras se pide la siguiente. La voz del bot
  pasa por una conexión WebRTC local para que el cancelador de eco del navegador la reste del micrófono: así podés
  interrumpir al bot hablando. Si eso no conecta, el bot suena directo y no te escucha mientras habla. Muestra
  subtítulos y se puede silenciar. Si el servidor no tiene piper, usa la voz del navegador. Con
  `localStorage['parla.voice.debug'] = '1'` la consola muestra niveles y tiempos de cada turno.
- **Widget** con `data-voice="true"`: un botón de micrófono que graba, manda a
  `POST /api/v1/bots/{bot}/audio` con `speak: true` y reproduce la respuesta.
- **API**: `POST /api/v1/bots/{bot}/audio` (ver [api.md](api_es.md#post-apiv1botsbotaudio)).

Todos estos (y el teléfono con `tts: "parla"`) usan la configuración `voice` del agente.

### Proveedores de voz en la nube

Se configuran por agente en la clave `voice` de primer nivel (en la interfaz: **IA → Voz**, con **Transcripción (lo
que dice la persona)** y **Voz del bot**):

```jsonc
"voice": {
  "asr": {"provider": "deepgram", "model": "nova-3"},
  "tts": {"provider": "elevenlabs", "model": "eleven_flash_v2_5", "voice": "<voice_id>"}
}
// cada parte: provider "local" (por defecto) | "openai" | "deepgram" | "elevenlabs" | "google";
// "api_key_secret" opcional (los nombres por defecto están en la tabla de Claves de arriba)
```

**Transcripción (ASR).** El vocabulario del bot (valores y sinónimos de entidades, como los hotwords de Whisper) se
manda como pistas. Los idiomas `es`/`en`/`pt` se traducen para cada proveedor.

| Proveedor | Modelo | Pistas de vocabulario |
|---|---|---|
| `openai` | `gpt-4o-mini-transcribe` (por defecto), `gpt-4o-transcribe`, `gpt-transcribe`, `whisper-1` | `prompt` |
| `deepgram` | `nova-3` (por defecto) | `keyterm` (solo Nova-3) |
| `elevenlabs` | Scribe `scribe_v3` (por defecto) | `keyterms` (ElevenLabs cobra ~20 % más cuando se mandan) |
| `google` | Speech-to-Text v1 | `speechContexts`; `es-US`, `en-US`, `pt-BR` salvo que indiques una región. El audio que no es Opus ni LINEAR16 se pasa a WAV con ffmpeg. |

**Voz del bot (TTS).** Todos devuelven WAV, como piper, así que el modo llamada, el widget y el `<Play>` del teléfono
andan igual.

| Proveedor | Modelo / voz |
|---|---|
| `openai` | `gpt-4o-mini-tts-2025-12-15`; voces `alloy`, `ash`, `ballad`, `coral` (por defecto), `echo`, `fable`, `onyx`, `nova`, `sage`, `shimmer`, `verse`, `marin`, `cedar`. (OpenAI marcó como obsoletos `gpt-4o-mini-tts` y `tts-1`, con cierre anunciado para el 2027-01-06.) |
| `deepgram` | Aura-2: la voz es el id del modelo, por ejemplo `aura-2-celeste-es` (por defecto en español), `aura-2-thalia-en` (por defecto en inglés). No hay voces en portugués. |
| `elevenlabs` | `eleven_flash_v2_5` (por defecto, ~100 ms, la menor latencia), `eleven_v4_turbo`, `eleven_multilingual_v2`; el id de voz sale de tus voces de ElevenLabs. |
| `google` | Cloud Text-to-Speech, nombre de voz opcional (por ejemplo `es-US-Neural2-A`). |

- **Probalo** en el panel Voz: **Probar voz** reproduce una muestra; **Grabar 3 s y transcribir** / **Subir un audio**
  muestra la transcripción. La lista de voces viene del proveedor (ElevenLabs y Google desde sus APIs, OpenAI y
  Deepgram listas fijas, local = voces de piper). El panel avisa cuando el audio o el texto salen de la máquina.
- **Las frases pregeneradas** también funcionan con TTS en la nube (cada frase se genera una sola vez). La clave de la
  caché incluye proveedor, modelo y voz, así que al cambiar nunca suena un audio viejo.
- Cada llamada de voz tiene un timeout de 30 s. Las keys y cómo se tapan, igual que en [Claves](#claves).
- **Teléfono:** `channels.phone.tts: "parla"` usa el `voice.tts` del agente (piper o un proveedor en la nube);
  `"provider"` sigue siendo la voz propia de Twilio/jambonz. En modo por turnos el reconocimiento de voz en el
  teléfono lo hace Twilio/jambonz; en modo stream ([Voz en tiempo real](#voz-en-tiempo-real)), el `voice.asr` del agente.
- **Privacidad y costo:** el ASR en la nube recibe el audio de la persona y las pistas de vocabulario; el TTS en la
  nube recibe el texto de la respuesta del bot. El proveedor le cobra el uso al dueño de la key.
- API: `POST /api/voice/speak` y `POST /api/voice/voices` aceptan un `agent` (o un `voice` sin guardar para probar);
  `POST /api/agents/{id}/voice/transcribe` usa el ASR del agente. Ver [api.md](api_es.md).

## Voz en tiempo real

Respuestas en menos de un segundo y barge-in de verdad, por WebSocket (`parla/voicestream.py`). La usan **Llamada
(voz)** del chat de prueba y el micrófono del widget (los dos vuelven al modo por turnos si el WebSocket no contesta) y
el teléfono con `channels.phone.mode: "stream"` ([channels.md](channels_es.md#modo-stream-en-tiempo-real)). Protocolo
en [api.md](api_es.md#websocket-de-voz-en-tiempo-real).

```
audio ─► ASR en streaming ──final──► turno (POST /events, mismas reglas) ──tokens de la IA por el bus──► oraciones
 (μ-law/L16/PCM16 → 16 kHz)  │                                                                            │
                             └─parcial/voz mientras habla el bot─► barge-in                               ▼
audio ◄── formato del canal (μ-law 8 kHz / L16 8 kHz / PCM16 16 kHz) ◄── TTS por oración (HTTP en streaming)
```

- **ASR.** `deepgram`: Deepgram live (WebSocket `/v1/listen`) con `interim_results`, `endpointing` (300 ms),
  `utterance_end_ms`, `vad_events` y las palabras del bot como `keyterm`. Cualquier otro proveedor (`local`,
  `openai`, `elevenlabs`, `google`): un VAD por energía en Python corta cada frase (600 ms de silencio por defecto) y
  se transcribe en el momento con el ASR por frase de siempre (faster-whisper por el pool de modelos de voz, o la API
  batch del proveedor). Ahí no hay parciales: el barge-in lo dispara el VAD. OpenAI Realtime y el STT realtime de
  ElevenLabs todavía no están conectados.
- **TTS.** Apenas existe la primera oración de la respuesta (los tokens de la IA llegan por el bus; las respuestas del
  NLU vienen enteras), cada oración va al TTS. `openai` (`response_format: "pcm"`), `deepgram` Aura
  (`container=none`) y `elevenlabs` (`/stream`, `pcm_16000`) transmiten: el audio sale con el primer pedazo. piper,
  Google y la caché de frases pregeneradas dan la oración entera. Todo se convierte al formato del canal (μ-law y
  remuestreo con numpy: `audioop` ya no está en Python 3.13).
- **Barge-in.** Mientras habla el bot, Parla sigue escuchando. Voz detectada (VAD) o un parcial de Deepgram con ≥
  `barge_in_chars` letras corta el audio al instante (`clear` en Twilio, `killAudio` en jambonz, `clear` en el
  navegador), corta el stream de la IA de ese turno (la respuesta queda con lo escrito) y el historial suma un evento
  «La persona interrumpió al bot después de «…»» con lo que llegó a escuchar. Después se atiende la frase nueva.
- **Config** (opcional, por agente): `"voice": {"stream": {"barge_in": true, "barge_in_chars": 2, "silence_ms": 600,
  "idle_seconds": 8}}`. `silence_ms` es el fin del turno (300 con Deepgram); `idle_seconds` repregunta en el teléfono
  como hacía el Gather (al tercer silencio corta).
- **Costos y métricas** como siempre: segundos de ASR (Deepgram: los segundos transmitidos) y letras de TTS por
  conversación; `parla_voice_e2e_latency_seconds`, `parla_voice_tts_first_byte_seconds`,
  `parla_voice_barge_ins_total` ([observability.md](observability_es.md)).

**Latencia** (fin de lo que dice la persona → primer byte de audio que sale; incluye el silencio de fin de turno):

| Armado | Medido |
|---|---|
| Deepgram live + ElevenLabs en streaming (servidores falsos de `tests/test_voice_stream.py`, respuesta del NLU) | ~0,34 s (300 ms son el endpointing); los proveedores reales suman su red y proceso: verificalo con tu cuenta |
| Local, teléfono (VAD 600 ms + ASR/TTS falsos) | ~0,62 s |
| Local, modelos reales en una laptop Apple Silicon: whisper `base` ~0,40 s para 2 s de voz, piper ~0,22 s la primera oración | ~1,2 s con `silence_ms` 600, ~1,0 s con 400; las frases fijas de la caché no pasan por piper |

Con una respuesta de la IA sumá lo que tarda el modelo en la primera oración. En una CPU más lenta, `PARLA_WHISPER=tiny`
o un ASR en la nube.
