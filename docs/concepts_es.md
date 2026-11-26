# Conceptos

[English](concepts.md) · **Español**

## Agente

Un **agente** (o bot) es un archivo JSON con todo lo que lo define. Los campos principales:

| Campo | Qué es |
|---|---|
| `name` | Nombre. Su versión en minúsculas y sin tildes (*slug*) sirve en las URLs: «Pizzería Don Luis» → `pizzeria-don-luis`. |
| `threshold` | Confianza mínima (0 a 1) para aceptar una intención. En un agente nuevo, `0.75`. |
| `fallback` | Qué dice cuando no entiende. Texto o lista (elige al azar sin repetir la anterior). |
| `languages` | Idiomas, el primero es el de por defecto. Ej. `["es", "pt", "en"]`. Sin este campo, `["es"]`. |
| `fallback_translations` | `{"pt": "...", "en": "..."}` (texto o lista). |
| `intents`, `entities`, `slots`, `flows` | Ver abajo. |
| `classifications` | `[{"name", "color", "description"}]` para marcar conversaciones y sacar reportes. |
| `functions` | Código Python o JavaScript que corre un paso `function`. |
| `knowledge`, `knowledge_threshold` | Base de conocimiento (`[{"id", "title", "source", "url", "text"}]`) y su puntaje mínimo (`0.75` por defecto). |
| `system` | Flujos del sistema (ver abajo). |
| `ai` | IA, local por defecto (ver [ai-and-voice.md](ai-and-voice_es.md)). `provider`: `"ollama"` (por defecto), `"openai"` (sin `url`, `https://api.openai.com/v1`; con `url`, cualquier servidor compatible con OpenAI, como antes), `"openai_compatible"` (mismo protocolo, con tu `url`: vLLM, llama.cpp, LM Studio, LocalAI, Azure OpenAI, Groq, OpenRouter), `"anthropic"` (Claude) o `"gemini"`. `api_key_secret` es el **nombre** de una clave de la bóveda; si no está, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` o `GEMINI_API_KEY`. |
| `voice` | `{"asr": {"provider", "model"?, "api_key_secret"?}, "tts": {"provider", "voice"?, "model"?, "api_key_secret"?}}`: reconocimiento de voz y la voz del bot. `provider`: `"local"` (por defecto: faster-whisper / piper, nada sale de la máquina), `"openai"`, `"deepgram"`, `"elevenlabs"` o `"google"`. Nombres de clave por defecto: `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `GOOGLE_API_KEY`. |
| `mcp_servers` | `[{"name", "url", "headers_secret"}]`: servidores MCP cuyas herramientas puede usar un paso `agent` (ver [`agent`](#agent-dejar-que-la-ia-converse)). |
| `widget` | `{"enabled", "origins", "title", "color", "greeting", "position", "voice"}`. |
| `channels` | `{"public_url", "whatsapp": {"enabled", "phone_number_id"}, "telegram": {"enabled"}}`. Los tokens van en la bóveda, ver [channels_es.md](channels_es.md). |
| `ignored_phrases` | Frases que «Para enseñar» ya no muestra. |
| `tests` | Pruebas de conversación: conversaciones esperadas que corren antes de publicar a producción (ver [testing-bots_es.md](testing-bots_es.md)). |
| `retention_days` | Días que se guardan las conversaciones sin movimiento. Sin el campo o `null`: `PARLA_RETENTION_DAYS`; `0`: para siempre. Ver [Retención y datos personales](#retención-y-datos-personales). |
| `pii_redaction` | Tapar datos personales en las conversaciones guardadas: `false` (por defecto), `true` (todo) o una lista de categorías. Misma sección. |

Exportar un agente baja ese JSON; importarlo crea un agente nuevo. No viajan las versiones, los entornos, el
entrenamiento, las claves ni los archivos subidos (se entrena al abrirlo), ni `retention_days` y
`pii_redaction`.

## Intención

Lo que la persona quiere hacer: `{"name": "Pedir pizza", "examples": ["quiero una pizza", "una de [muzza](gusto)"]}`.

Parla convierte cada frase en un vector (modelo `google/embeddinggemma-300m` con fastembed, con el prefijo
`task: sentence similarity | query: `) y compara el mensaje con todas: gana la intención de la frase más parecida
(vecino más cercano). Por eso sumar una frase no requiere entrenar un modelo pesado y funciona en varios idiomas.
La confianza es la similitud coseno con esa frase.

Los nombres que empiezan con `__` están reservados: `__start__` y las intenciones de los flujos del sistema
(`__cancel__`, `__repeat__`, `__handoff__`).

## Entidad

Un dato dentro del mensaje. Tipos (el `kind` en el JSON):

| `kind` | En la interfaz | Cómo la reconoce |
|---|---|---|
| `examples` | Por los ejemplos que marco en las frases | Un CRF (python-crfsuite) aprende del contexto de lo marcado, como el `CRFEntityExtractor` de Rasa. Guarda el valor tal como se escribió. |
| `list` | De una lista de opciones | `values` y `synonyms` (`{"muzzarella": ["muzza"]}`): guarda el valor canónico. |
| `number`, `email`, `phone`, `dni` | Número, email, teléfono, DNI | Una regex que pone la interfaz. |
| `date` | Fecha u hora | Reglas en español rioplatense (`dates.py`): «mañana», «el jueves que viene a la tarde», «15/12 a las 10». Guarda `YYYY-MM-DD` o `YYYY-MM-DDTHH:MM`. |
| `custom` | Un formato propio (regex) | Tu regex (sin distinguir mayúsculas). Si tiene un grupo, guarda el grupo 1. |

En realidad el motor decide por los campos, no por `kind`: si hay `regex`, usa la regex; si hay `values`, la lista;
si es `date`, las reglas de fechas; si no tiene nada de eso, la aprende el CRF. Las marcas en las frases se escriben
`[valor](entidad)` y además suman ese valor como forma conocida. Lo reconocido seguro (formato, lista) tiene
prioridad sobre lo que adivina el CRF.

Opcional, solo en el JSON (la interfaz todavía no lo edita): `phrasings`, otras formas de decir cada opción de una
lista, para [entender respuestas por significado](#entender-una-respuesta-por-significado):

```json
{"name": "modalidad", "kind": "list", "values": ["presencial", "virtual"],
 "phrasings": {"virtual": ["desde mi casa", "por videollamada"], "presencial": ["voy al consultorio"]}}
```

## Slot

La memoria de la conversación: `{"name": "gusto", "entity": "gusto"}`. Cuando aparece la entidad, se guarda en
el slot. Mientras el bot espera una respuesta, solo se llena el slot que preguntó (así el número de una dirección
no termina en `cantidad`).

- Sin entidad (o con una entidad `examples`), la respuesta a la pregunta se guarda entera.
- Con IA: `{"name": "nombre", "fill": "ai", "description": "el nombre y apellido de la persona"}` deja que la IA
  lea el valor del mensaje (solo si está escrito ahí).
- `"start": true` lo marca como dato inicial: «Empezar con datos» en el chat de prueba muestra solo esos. No cambia
  el motor: al empezar una conversación por la API, cualquier campo de `data` que se llame como un slot se guarda.

## Flujo

Una lista de pasos que se dispara con una intención:

```json
{"name": "Pedido", "trigger": "Pedir pizza", "steps": [ ... ]}
```

- `"trigger": "__start__"` corre el flujo apenas empieza la conversación (evento `start`).
- `"trigger": ""` = solo se llega con `goto` o `call`.
- Si dos flujos tienen el mismo trigger, gana el primero.
- `interrupts` (opcional, solo en el JSON): `false` para flujos de charla (saludar, agradecer) que nunca cortan una
  pregunta pendiente; `"always"` para lo urgente: corta la pregunta, aunque el mensaje traiga el dato, y no vuelve.
  Por defecto `true` (ver [mientras espera una respuesta](#mientras-espera-una-respuesta)).

## Tipos de paso

### `message`: enviar un mensaje
```json
{"type": "message", "text": "Hola {{ nombre }}", "translations": {"pt": "Olá {{ nombre }}"},
 "buttons": [{"label": "Ver menú", "value": "quiero ver el menú"}]}
```
Tocar un botón equivale a escribir su `value` (si no tiene, el `label`). Escribir el label o el value a mano también
cuenta como tocarlo. Los botones también aceptan `translations` para el label.

### `ask`: hacer una pregunta
```json
{"type": "ask", "slot": "gusto", "text": "¿De qué gusto?", "buttons": [{"label": "Muzzarella", "value": "muzzarella"}]}
```
Si el slot ya tiene valor, se saltea. Tocar un botón guarda su `value` en el slot. Qué pasa con la respuesta está
en [mientras espera una respuesta](#mientras-espera-una-respuesta).

`also` (opcional, solo en el JSON): otras entidades que también cuentan como respuesta. Si la respuesta no trae la
del slot pero sí una de esas («el jueves» a «¿te sirve el lunes?»), el slot queda vacío y el flujo sigue: los pasos
siguientes leen `entities` y deciden.
```json
{"type": "ask", "slot": "confirma", "text": "¿Te sirve el lunes a las 9?", "also": ["fecha"]},
{"type": "if", "expr": "has(entities.fecha)", "then": [ ... ], "else": [ ... ]}
```

### `set`: guardar un valor
```json
{"type": "set", "slot": "saludo", "mode": "text", "text": "Hola {{ nombre }}"}
{"type": "set", "slot": "total", "mode": "cel", "expr": "int(cantidad) * 5000"}
{"type": "set", "slot": "gusto", "mode": "clear"}
```

### `http`: consultar un servicio
```json
{"type": "http", "method": "GET", "url": "https://api.ejemplo.com/pedidos/{{ numero }}",
 "headers": [{"key": "Authorization", "value": "Bearer {{ secret.API_KEY }}"}], "body": "",
 "saves": [{"expr": "status", "slot": "codigo"}, {"expr": "body.estado", "slot": "estado"}]}
```
Tiempo máximo 10 s; se leen hasta 1 MB de respuesta. Con `body`, se agrega `Content-Type: application/json`. En
la URL, cada `{{ }}` se codifica (lo que escribió la persona no puede cambiar la dirección), salvo
`{{ secret.X }}`; un encabezado con saltos de línea es un error. En
`saves` las expresiones ven `status` (0 si no se pudo conectar) y `body` (JSON o texto). Un dato que no vino queda en
`null`. Un 4xx/5xx no corta el flujo: decidí con un `if` sobre el código.

### `if`: tomar un camino
```json
{"type": "if", "cond": {"var": "codigo", "op": "eq", "value": "200"},
 "then": [{"type": "message", "text": "Encontrado"}], "else": [{"type": "message", "text": "No existe"}]}
```
Operadores: `eq`, `ne`, `contains` (como texto, sin distinguir mayúsculas), `gt`, `lt` (como números), `empty`,
`filled`. En vez de `cond` se puede usar `"expr"` con una expresión CEL: la rama `then` corre solo si da `true`.

### `goto`: seguir con otro flujo
```json
{"type": "goto", "flow": "Pedido"}
```
Salta al principio de otro flujo y no vuelve. (También acepta el nombre en `"goto"`.)

### `call`: llamar a otro flujo (y volver)
```json
{"type": "call", "flow": "Pedir dirección"}
```
Al terminar el subflujo sigue con el paso siguiente. Hasta 5 flujos apilados (subflujos e interrupciones).

### `end`: terminar
```json
{"type": "end"}
```
En un subflujo, vuelve al que lo llamó. En una llamada telefónica, corta después de decir lo anterior
([channels_es.md](channels_es.md#llamadas-telefónicas-twilio-y-jambonz)).

### `classify`: clasificar la conversación
```json
{"type": "classify", "classification": "Venta"}
```
Queda marcada (cada clasificación cuenta una sola vez por conversación) y aparece en los reportes.

### `file`: enviar un archivo
```json
{"type": "file", "file": "Lista de precios.pdf", "text": "Acá tenés la lista, {{ nombre }}"}
```
Manda un archivo que subiste al bot desde el mismo paso (PDF, imagen, Word, Excel, PowerPoint, CSV, TXT o ZIP, hasta
10 MB). `file` es el id o el nombre (con nombres repetidos, el último subido); `text` es opcional (sin texto, el
mensaje es el nombre del archivo). En la API el mensaje llega en `messages` como siempre y `replies[i].file` trae
`{id, name, mime, size, url}`; `url` (`/files/<agente>/<id>`) se abre sin sesión: el id es aleatorio y hace de
llave, así que no subas nada privado. Los archivos son del bot, no de una versión: si borrás uno, el paso falla
también en lo publicado. Exportar el bot no lleva los archivos.

### `function`: ejecutar una función
```json
{"type": "function", "function": "precio", "auto_save": true,
 "saves": [{"expr": "result.total", "slot": "total"}, {"expr": "ok", "slot": "salio_bien"}]}
```
La función se define en `functions`:
```json
{"name": "precio", "language": "python", "inputs": ["gusto", "cantidad", "secret.API_KEY"],
 "code": "def run(inputs):\n    return {\"total\": int(inputs[\"cantidad\"]) * 5000}"}
```
Recibe los slots que declara en `inputs` (y `inputs["secret"]["API_KEY"]`). Lo que devuelve con el nombre de un
slot se guarda solo (`auto_save`, prendido por defecto). Si falla y ningún `saves` mira `ok` o `error`, el flujo se
corta con un aviso. Tiempo máximo 5 s. JavaScript necesita Node.js. La sección **Funciones** trae ejemplos listos
para usar y un botón para probarlas. Ver [security.md](security_es.md): no es un sandbox.

### `handoff`: pasar con una persona
```json
{"type": "handoff", "text": "Te paso con alguien del local.", "reason": "reclamo"}
```
El bot se calla y la conversación aparece en la **Bandeja** hasta que una persona la devuelve. Sin `text`, usa el
de `system.handoff`.

### `agent`: dejar que la IA converse
```json
{"type": "agent", "instructions": "Ayudá a elegir un gusto y averiguá la dirección.",
 "functions": ["precio"], "knowledge": true, "slots": ["gusto", "direccion"],
 "goal": "cuando tengas el gusto y la dirección", "max_turns": 8}
```
Una isla de IA dentro del flujo: conversa, puede llamar solo a las funciones listadas, llena los slots listados y
termina cuando cumple el objetivo o agota los turnos; después sigue con el paso siguiente. Necesita la IA prendida.

**Herramientas.** Con `tools` el modelo puede consultar cosas por su cuenta (`functions` sigue andando y equivale a
herramientas `function`):
```json
"tools": [
  {"type": "function", "name": "precio"},
  {"type": "http", "name": "buscar_pedido", "description": "Estado de un pedido por número",
   "params": {"pedido": "número de pedido"}, "method": "GET",
   "url": "https://api.ejemplo.com/pedidos/{{ pedido }}",
   "headers": [{"key": "Authorization", "value": "Bearer {{ secret.API_KEY }}"}], "body": ""},
  {"type": "mcp", "server": "crm", "tools": ["get_customer"]}
],
"max_tool_calls": 2, "time_budget": 12
```
- `http` funciona como un paso `http`: el modelo solo completa los `params` (`{nombre: "descripción"}` o
  `{nombre: {"type": "string|integer|number|boolean", "description", "required"}}`), que van codificados en la URL y
  escapados como JSON en el body. El servidor queda fijo en `url`; el modelo nunca lo elige.
- `mcp` usa un servidor de `mcp_servers` del agente (Streamable HTTP; `headers_secret` es el *nombre* de una clave de
  la bóveda que va como `Authorization`, `Bearer <valor>` si no tiene espacio). `tools` es una allow-list obligatoria:
  el modelo solo ve las herramientas que están en la lista y que el servidor ofrece. Si el servidor no responde, el
  paso sigue sin ellas.
- `max_tool_calls` (1 a 10, 3 por mensaje por defecto) y `time_budget` (3 a 60 s, 15 por defecto) limitan las
  consultas; en teléfono dejá 1–2 llamadas y ≤ 12 s.

Cada llamada aparece en la traza del chat de prueba (`IA usó buscar_pedido(...) -> bien: ...`) y en el historial, con
las claves tapadas. En el editor de flujos es la sección **Herramientas** del paso agente; los servidores MCP se
cargan en la pantalla **IA**. Si la consulta pasa siempre, mejor un `ask` + `http` común: más rápido y se prueba sin
IA. Detalles en [ai-and-voice_es.md](ai-and-voice_es.md#herramientas-en-el-paso-agente) y
[security_es.md](security_es.md#herramientas-en-el-paso-agente).

## Plantillas `{{ }}` y CEL

Dentro de textos, URLs, headers y bodies, `{{ ... }}` se reemplaza por su valor. Adentro va un nombre de slot o
una expresión [CEL](https://github.com/google/cel-spec):

```
Tu pedido de {{ cantidad }} {{ gusto }} sale ${{ int(cantidad) * 5000 }}.
{{ nombre != null ? nombre : "che" }}
```

Variables disponibles: todos los slots, más `intent`, `confidence`, `text` (el último mensaje) y `entities`
(`{entidad: valor}`). En `saves` de `http` además `status` y `body`; en `saves` de `function`, `result`, `ok` y
`error`. `{{ secret.NOMBRE }}` solo vale en URL, headers y body de un paso `http` (y como entrada `secret.NOMBRE`
de una función): en un mensaje es un error (el validador del MCP lo marca).

Un slot vacío se muestra como texto vacío. Si una expresión falla, el chat muestra el flujo, el paso y la expresión,
y la conversación se corta.

## Flujos del sistema

Reparaciones de la charla que vienen prendidas (o no) y se editan en `system`:

| Clave | Por defecto | Qué hace |
|---|---|---|
| `cancel` | prendido | «cancelar», «olvidalo»: corta lo que estaba haciendo. |
| `repeat` | prendido | «¿cómo?», «repetí»: repite lo último que dijo el bot. |
| `clarify` | prendido, `margin: 0.04` | Si las dos mejores intenciones superan el umbral y están a menos de `margin`, pregunta «¿Quisiste decir A o B?» con botones. |
| `anything_else` | apagado | Al terminar un flujo: «¿Te ayudo con algo más?». |
| `resume` | prendido | Al volver de una interrupción: «Sigamos con lo de antes.». |
| `correction` | prendido | «mejor de fugazza» mientras pregunta otra cosa: cambia un dato que ya había dado (solo slots que este flujo ya preguntó) y sigue desde esa pregunta. |
| `handoff` | prendido | «quiero hablar con una persona»: pasa a la Bandeja. |
| `csat` | apagado | Al terminar el primer flujo de la conversación: «¿Cómo te atendí? Del 1 al 5.» con botones. Acepta `4` o `4/5`. |

Cada uno tiene `enabled`, `text` (y `translations`) y, los que se reconocen por frases (`cancel`, `repeat`,
`handoff`), `examples`. Esas frases se entrenan como intenciones del sistema.

## Mientras espera una respuesta

Cuando un `ask` está esperando, el mensaje se toma primero como respuesta. En orden:

1. **Comportamientos del sistema** (cancelar, repetir, pasar con una persona): piden más seguridad que una
   intención normal (al menos 0.75, o 0.92 si la pregunta es de texto libre) y no cuentan si el mensaje ya trae el
   dato pedido o si se tocó un botón. Así «Pedro» o «30.123.456» no se confunden con «repetí».
2. **Urgente**: un flujo con `"interrupts": "always"` cuya intención llega al umbral corta todo y no vuelve.
3. **Una pregunta en vez de una respuesta** («¿qué es presencial?» a «¿presencial o virtual?»): si la base de
   conocimiento la sabe contestar, contesta y vuelve a preguntar. Con IA, si no hay nada en la base, dice que no lo
   sabe en vez de inventar. Si la persona después dice «ah, entonces sí», elige la opción que se le explicó.
4. **Corrección** de un dato anterior (si `correction` está prendido).
5. **La respuesta**:
   - Si el slot tiene entidad con formato, lista o fecha y la respuesta no la trae: primero mira `also`; después
     intenta [entenderla por significado](#entender-una-respuesta-por-significado) y, con IA, le pregunta al modelo
     qué hizo la persona (contestó, preguntó, pidió otra cosa o solo saludó). Si nada de eso sirve, dice «No reconocí
     ese dato, probemos de nuevo.» y vuelve a preguntar. A un «gracias» no le dice «No reconocí».
   - Si la respuesta trae dos valores distintos de la misma entidad («sí… no puedo»), no elige ninguno y vuelve a
     preguntar.
   - Con `fill: "ai"`, la IA lee el valor; si no lo encuentra, vuelve a preguntar.
   - Si el slot no tiene entidad, guarda el texto entero.
6. **Interrupción**: si la respuesta no sirvió y el mensaje es otra intención clara (al menos 0.75) cuyo flujo
   interrumpe, la atiende y después vuelve a la pregunta (con `resume`). Si el mensaje se leyó por significado o con
   la IA, solo interrumpe lo que esa lectura vio como otra acción. Los flujos con `"interrupts": false` no
   interrumpen.

### Entender una respuesta por significado

Para una entidad de lista con `phrasings`, si la respuesta no trae literalmente una opción («la quiero desde mi
casa»), Parla la compara por significado, con el mismo modelo de vectores, contra las formas de decir cada opción
(valores, sinónimos y `phrasings`), contra las frases de las intenciones que podrían interrumpir y contra charla que
no contesta nada («gracias», «un momento»). Solo decide si está claro (similitud de al menos 0.60 y 0.04 de ventaja
sobre la segunda; una intención le tiene que ganar por 0.10 a la mejor opción). Si no, pasa a la IA o al «No
reconocí». No necesita IA generativa. Cuando decide, el turno trae `via: "significado"`.

## Qué pasa cuando no entiende

Fuera de una pregunta:

1. Si la IA está prendida y la confianza no llega al umbral (o dos intenciones empatan), intenta rescatar la
   intención entre las más parecidas.
2. Si dos intenciones siguen empatadas, pregunta «¿Quisiste decir…?» (`clarify`).
3. Si no hay intención (o la intención no tiene flujo), busca en la base de conocimiento: si algo llega a
   `knowledge_threshold`, responde con eso (sin IA, con el fragmento tal cual; con IA, una respuesta corta
   controlada).
4. Con IA y `generative_fallback`, repregunta y dice qué sabe hacer el bot.
5. Si no, el `fallback`.

## Idioma

El idioma de la charla es el que llega al empezar (`idioma`, `language` o `lang` en los datos de inicio) o, si no,
el que se adivina por las palabras del primer mensaje entre los de `languages` (en empate gana el primero). Los
mensajes usan `translations[idioma]` si está; si no, el texto original.

## Versiones y entornos

- **Borrador**: lo que editás.
- **Versión**: una copia numerada e inmutable del borrador, con su propio modelo entrenado.
- **Entornos**: `staging` (Pruebas) y `production` (Producción) apuntan a una versión.

La API habla con `production` por defecto (o con el borrador si todavía no se publicó nada). Cada conversación
queda atada a la versión con la que empezó: publicar no cambia los pasos a mitad de una charla. Rollback =
apuntar el entorno a otra versión. «Restaurar» vuelve el borrador a lo que tenía una versión.

Lo que no es de una versión sino del bot: las claves, los archivos, las conversaciones y los ajustes de operación
`retention_days` y `pii_redaction` (no se versionan y «Restaurar» los respeta).

Las **pruebas** de conversación (sección «Tests») son parte de la definición, así que cada versión tiene las suyas.
Publicar a `production` las corre antes contra el borrador y frena si falla alguna; publicar a `staging` y `deploy`
no. Ver [testing-bots_es.md](testing-bots_es.md).

## Retención y datos personales

Las conversaciones se guardan en `parla.db`, en la carpeta de datos. Los dos ajustes están en **Ajustes** del
agente → **Privacidad y datos**.

**Retención (`retention_days`).** Se borran las conversaciones cuyo último movimiento tiene más de esa cantidad de
días. Sin el campo (o con `null`) vale `PARLA_RETENTION_DAYS`; con `0`, o sin ninguno de los dos, se guardan para
siempre. La limpieza corre al arrancar y cada hora. Los archivos subidos (paso `file`) son del agente, no de una
conversación: la retención nunca los borra.

**Tapado (`pii_redaction`).** `true` tapa todas las categorías; una lista, solo esas:

| Categoría | Queda | Qué agarra |
|---|---|---|
| `email` | «[email]» | Direcciones de correo. |
| `phone` | «[teléfono]» | Teléfonos. |
| `card` | «[tarjeta]» | De 13 a 19 dígitos, solo si pasan el control de Luhn. |
| `id` | «[documento]» | CUIT/CUIL (11 dígitos), DNI (7 u 8 dígitos, con o sin puntos) y cualquier otro número de 9 dígitos o más. |
| `bank` | «[cuenta]» | CBU/CVU (22 dígitos) e IBAN (validado con módulo 97). |

Se aplica a lo que se **guarda**: el texto del historial, los valores de las entidades y los datos de inicio. Así,
la Bandeja, el visor de conversaciones, «lo que no entendió», las analíticas y el historial de la API ven el texto
tapado. No se aplica al turno en vivo: el flujo, los pasos `http` y las funciones reciben el valor real, y la
respuesta de ese turno trae el texto real. Los slots y el contexto de la IA guardan los valores reales mientras la
conversación sigue abierta (los pasos siguientes los necesitan) y se borran cuando termina; con el tapado
prendido, las conversaciones quietas por 24 horas (salvo las que están con una persona) se cierran para que eso pase.

Límites: es una heurística, así que se le puede escapar un formato o tapar un número que no es un dato personal
(un número de pedido de 9 dígitos o más); las respuestas del operador en la Bandeja también se guardan tapadas (un
widget que lee el historial las ve tapadas); prenderlo no reescribe lo que ya estaba guardado (cada conversación
se tapa desde su próximo guardado); y no se aplica a lo que el servidor escribe en la consola.
