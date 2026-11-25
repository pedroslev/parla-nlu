# Conceptos

## Agente

Un **agente** (o bot) es un archivo JSON con todo lo que lo define. Los campos principales:

| Campo | Qué es |
|---|---|
| `name` | Nombre. Su versión en minúsculas y sin tildes (*slug*) sirve en las URLs: «Pizzería Don Luis» → `pizzeria-don-luis`. |
| `threshold` | Confianza mínima (0 a 1) para aceptar una intención. Por defecto `0.55`. |
| `fallback` | Qué dice cuando no entiende. Texto o lista (elige al azar sin repetir la anterior). |
| `languages` | Idiomas, el primero es el de por defecto. Ej. `["es", "pt", "en"]`. |
| `fallback_translations` | `{"pt": "...", "en": "..."}`. |
| `intents`, `entities`, `slots`, `flows` | Ver abajo. |
| `classifications` | `[{"name", "color", "description"}]` para marcar conversaciones y sacar reportes. |
| `functions` | Código Python o JavaScript que corre un paso `function`. |
| `knowledge`, `knowledge_threshold` | Base de conocimiento y su puntaje mínimo (`0.55`). |
| `system` | Flujos del sistema (ver abajo). |
| `ai` | IA local (ver [ai-and-voice.md](ai-and-voice.md)). |
| `widget` | `{"enabled", "origins", "title", "color", "greeting", "position", "voice"}`. |

Exportar un agente baja ese JSON; importarlo crea un agente nuevo (las versiones, entornos y el entrenamiento
no viajan: se entrena al abrirlo).

## Intención

Lo que la persona quiere hacer: `{"name": "Pedir pizza", "examples": ["quiero una pizza", "una de [muzza](gusto)"]}`.

Parla convierte cada frase en un vector (modelo `paraphrase-multilingual-MiniLM-L12-v2` con fastembed) y compara el
mensaje con todas: gana la intención de la frase más parecida (vecino más cercano). Por eso sumar una frase es
inmediato y funciona en varios idiomas. La confianza es la similitud coseno con esa frase.

## Entidad

Un dato dentro del mensaje. Tipos (el `kind` en el JSON):

| `kind` | En la interfaz | Cómo la reconoce |
|---|---|---|
| `examples` | Por los ejemplos que marco en las frases | Un CRF (python-crfsuite) aprende del contexto de lo marcado, como el `CRFEntityExtractor` de Rasa. |
| `list` | De una lista de opciones | `values` y `synonyms` (`{"muzzarella": ["muzza"]}`): guarda el valor canónico. |
| `number`, `email`, `phone`, `dni` | Número, email, teléfono, DNI | Una regex que pone la interfaz. |
| `date` | Fecha u hora | Reglas en español rioplatense (`dates.py`): «mañana», «el jueves que viene a la tarde», «15/12 a las 10». Guarda `YYYY-MM-DD` o `YYYY-MM-DDTHH:MM`. |
| `custom` | Un formato propio (regex) | Tu regex. Si tiene un grupo, guarda el grupo 1. |

Las marcas en las frases se escriben `[valor](entidad)`. Lo reconocido seguro (formato, lista) tiene prioridad
sobre lo que adivina el CRF.

## Slot

La memoria de la conversación: `{"name": "gusto", "entity": "gusto"}`. Cuando aparece la entidad, se guarda en
el slot. Mientras el bot espera una respuesta, solo se llena el slot que preguntó (así el número de una dirección
no termina en `cantidad`).

Con IA: `{"name": "nombre", "fill": "ai", "description": "el nombre y apellido de la persona"}` deja que la IA
lea el valor del mensaje (solo si está escrito ahí).

Al empezar una conversación por la API, los datos de `data` se guardan en los slots que se llaman igual.

## Flujo

Una lista de pasos que se dispara con una intención:

```json
{"name": "Pedido", "trigger": "Pedir pizza", "steps": [ ... ]}
```

`"trigger": "__start__"` corre el flujo apenas empieza la conversación (evento `start`).

## Tipos de paso

### `message`: enviar un mensaje
```json
{"type": "message", "text": "Hola {{ nombre }}", "translations": {"pt": "Olá {{ nombre }}"},
 "buttons": [{"label": "Ver menú", "value": "quiero ver el menú"}]}
```
Tocar un botón equivale a escribir su `value`.

### `ask`: hacer una pregunta
```json
{"type": "ask", "slot": "gusto", "text": "¿De qué gusto?", "buttons": [{"label": "Muzzarella", "value": "muzzarella"}]}
```
Si el slot ya tiene valor, se saltea. Si el slot espera un formato o una opción y la respuesta no lo tiene, dice
«No reconocí ese dato» y vuelve a preguntar (o, si el mensaje es otra intención clara, la atiende y después
vuelve).

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
Tiempo máximo 10 s. En `saves` las expresiones ven `status` (0 si no se pudo conectar) y `body` (JSON o texto).
Un dato que no vino queda en `null`.

### `if`: tomar un camino
```json
{"type": "if", "cond": {"var": "codigo", "op": "eq", "value": "200"},
 "then": [{"type": "message", "text": "Encontrado"}], "else": [{"type": "message", "text": "No existe"}]}
```
Operadores: `eq`, `ne`, `contains`, `gt`, `lt`, `empty`, `filled` (sin distinguir mayúsculas). En vez de `cond`
se puede usar `"expr"` con una expresión CEL que devuelva `true`.

### `goto`: seguir con otro flujo
```json
{"type": "goto", "goto": "Pedido"}
```
Salta a otro flujo y no vuelve.

### `call`: llamar a otro flujo (y volver)
```json
{"type": "call", "flow": "Pedir dirección"}
```
Al terminar el subflujo sigue con el paso siguiente. Hasta 5 flujos apilados.

### `end`: terminar
```json
{"type": "end"}
```
En un subflujo, vuelve al que lo llamó.

### `classify`: clasificar la conversación
```json
{"type": "classify", "classification": "Venta"}
```
Queda marcada y cuenta en los reportes.

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
slot se guarda solo (`auto_save`). Si falla y ningún `saves` mira `ok` o `error`, el flujo se corta con un aviso.
Tiempo máximo 5 s. JavaScript necesita Node.js. Ver [security.md](security.md): no es un sandbox.

### `handoff`: pasar con una persona
```json
{"type": "handoff", "text": "Te paso con alguien del local.", "reason": "reclamo"}
```
El bot se calla y la conversación aparece en la **Bandeja** hasta que una persona la devuelve.

### `agent`: dejar que la IA converse
```json
{"type": "agent", "instructions": "Ayudá a elegir un gusto y averiguá la dirección.",
 "functions": ["precio"], "knowledge": true, "slots": ["gusto", "direccion"],
 "goal": "cuando tengas el gusto y la dirección", "max_turns": 8}
```
Una isla de IA dentro del flujo: conversa, puede llamar solo a las funciones listadas, llena los slots listados y
termina cuando cumple el objetivo o agota los turnos. Necesita la IA prendida.

## Plantillas `{{ }}` y CEL

Dentro de textos, URLs, headers y bodies, `{{ ... }}` se reemplaza por su valor. Adentro va un nombre de slot o
una expresión [CEL](https://github.com/google/cel-spec):

```
Tu pedido de {{ cantidad }} {{ gusto }} sale ${{ int(cantidad) * 5000 }}.
{{ nombre != null ? nombre : "che" }}
```

Variables disponibles: todos los slots, más `intent`, `confidence`, `text` (el último mensaje) y `entities`
(`{entidad: valor}`). En `saves` de `http` además `status` y `body`; en `saves` de `function`, `result`, `ok` y
`error`. `{{ secret.NOMBRE }}` solo vale en URL, headers y body de un paso `http`: en un mensaje es un error (el
validador del MCP lo marca).

Un slot vacío se muestra como texto vacío. Si una expresión falla, el chat muestra qué paso y qué expresión.

## Flujos del sistema

Reparaciones de la charla que vienen prendidas (o no) y se editan en `system`:

| Clave | Por defecto | Qué hace |
|---|---|---|
| `cancel` | prendido | «cancelar», «olvidalo»: corta lo que estaba haciendo. |
| `repeat` | prendido | «¿cómo?», «repetí»: repite lo último. |
| `clarify` | prendido, `margin: 0.04` | Si las dos mejores intenciones están muy cerca, pregunta «¿Quisiste decir A o B?» con botones. |
| `anything_else` | apagado | Al terminar un flujo: «¿Te ayudo con algo más?». |
| `resume` | prendido | Al volver de una interrupción: «Sigamos con lo de antes.». |
| `correction` | prendido | «mejor de fugazza» mientras pregunta otra cosa: cambia un dato que ya había dado. |
| `handoff` | prendido | «quiero hablar con una persona»: pasa a la Bandeja. |
| `csat` | apagado | Al terminar: «¿Cómo te atendí? Del 1 al 5.» con botones. |

Cada uno tiene `enabled`, `text` (y `translations`) y, los que se reconocen por frases, `examples`. Mientras el bot
espera una respuesta, estos comportamientos piden más seguridad para no confundir «Pedro» con «repetí».

## Qué pasa cuando no entiende

1. Si la IA está prendida, intenta rescatar la intención entre las más parecidas.
2. Busca en la base de conocimiento; si algo supera `knowledge_threshold`, responde con eso (sin IA, con el
   fragmento tal cual; con IA, una respuesta corta controlada).
3. Con IA y `generative_fallback`, repregunta y dice qué sabe hacer el bot.
4. Si no, el `fallback`.

## Versiones y entornos

- **Borrador**: lo que editás.
- **Versión**: una copia numerada e inmutable del borrador, con su propio modelo entrenado.
- **Entornos**: `staging` (Pruebas) y `production` (Producción) apuntan a una versión.

La API habla con `production` por defecto (o con el borrador si todavía no se publicó nada). Cada conversación
queda atada a la versión con la que empezó: publicar no cambia los pasos a mitad de una charla. Rollback =
apuntar el entorno a otra versión. «Restaurar» vuelve el borrador a lo que tenía una versión.
