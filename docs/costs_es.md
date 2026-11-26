# Costos por conversación

[English](costs.md) · **Español**

Parla mide lo que usa cada conversación (tokens del modelo, minutos de audio, caracteres hablados, minutos de
teléfono, mensajes enviados) y lo multiplica por una tabla de precios que manejás vos. Así tenés el costo de cada
conversación, de cada conversación resuelta y de cada día, para compararlo con lo que cobra un proveedor cerrado
por conversación.

**Son estimaciones.** La factura de cada proveedor es la fuente de verdad: no se modelan los tramos gratis, los
descuentos por volumen, los impuestos, el redondeo (Twilio cobra minutos enteros) ni los precios por país.

## Qué se mide

| Tipo | Unidad | De dónde sale |
|---|---|---|
| `llm_input`, `llm_output` | tokens | Lo que informa el proveedor en cada llamada: `usage` de Anthropic (la escritura de caché cuenta como entrada), `usage` de los compatibles con OpenAI, `usageMetadata` de Gemini (el razonamiento cuenta como salida), `prompt_eval_count` / `eval_count` de Ollama. |
| `llm_cached` | tokens | La entrada leída de caché cuando el proveedor la informa (`cache_read_input_tokens`, `prompt_tokens_details.cached_tokens`, `cachedContentTokenCount`). |
| `llm_compute` | horas de CPU | `prompt_eval_duration + eval_duration` de Ollama, para ponerle precio a tu propio hardware. |
| `asr` | minutos | Whisper local: el audio decodificado. Proveedores: la duración que informan (Deepgram `metadata.duration`, Google `totalBilledTime`, OpenAI `whisper-1`); si no, el largo del audio. |
| `tts` | caracteres | Cada frase sintetizada; las frases fijas pregeneradas que salen de la caché no se cuentan. |
| `phone` | minutos | `CallDuration` de Twilio / `duration` de jambonz en el status callback cuando termina la llamada, `inbound` u `outbound`. |
| `phone_call` | llamadas | Cada llamada saliente. |
| `whatsapp` | mensajes | Respuestas del bot (`service`) y plantillas (`template:<categoría>`, del `category` de la plantilla en el catálogo). |
| `telegram` | mensajes | Respuestas del bot (la Bot API es gratis). |
| `turn` | turnos | Cada turno, para repartir un costo fijo de servidor (los embeddings y el CRF corren acá y no tienen precio por llamada). |

El uso se guarda crudo, por agente, día, conversación, canal, proveedor, modelo y tipo (tabla SQLite `usage`), y un
resumen por turno va al registro de la conversación (`usage` en el mensaje de la persona y en la conversación). El
turno nunca espera esto: las escrituras van por la cola del escritor de la base sin esperar el commit.

El costo se calcula **al leerlo** con los precios de ahora: cambiar un precio cambia también lo pasado ("estimado
con los precios actuales").

## Precios

**Reportes → Costos → Precios** muestra la tabla; solo el **dueño** la cambia (`PUT /api/prices`, queda en la
auditoría). Se guarda en `DATA/prices.json`. Cada fila es un `kind`, un `provider`, un `model` (exacto, o un patrón
como `aura-2-*` o `*`) y un `price` por unidad: por 1M de tokens, por minuto, por 1M de caracteres, por mensaje, por
llamada, por hora de CPU. Precio vacío = "no se sabe": ese uso aparece en **Falta el precio** («completá el precio»)
y no se suma.

Valores de fábrica solo donde el precio se verificó en la página oficial del proveedor (cada fila trae su `source` y
la fecha `checked`, 2026-11-26):

| Proveedor | Modelo | Precio |
|---|---|---|
| Anthropic | `claude-opus-5-5` | US$4 entrada / 0,20 caché / 20 salida por 1M de tokens |
| Anthropic | `claude-sonnet-5-5` | 2 / 0,10 / 10 |
| Anthropic | `claude-haiku-5-5` | 0,10 / — / 0,50 (prompts de hasta 100K tokens) |
| OpenAI | `gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.2-sol` | 0,10/0,01/0,50 · 1/0,05/5 · 2/0,10/10 |
| Gemini | `gemini-3.8-flash` | 0,75 / 0,075 / 3,75 hasta el 31/12/2026 (1,50 / 0,15 / 7,50 desde 2027) |
| Gemini | `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` | 0,30/0,03/2,50 · 2/0,20/12 (hasta 200K) |
| OpenAI | `gpt-4o-mini-transcribe` | US$0,003 por minuto |
| Deepgram | `nova-3` / `aura-2-*` | US$0,0043 por minuto / 30 por 1M de caracteres |
| ElevenLabs | `scribe_v3` / `eleven_flash_v2_5`, `eleven_turbo_v2_5` / `eleven_multilingual_v2` | US$0,20 por hora / 40 / 80 por 1M de caracteres |
| Twilio | entrante / saliente | US$0,0085 / 0,014 por minuto (número local de EE. UU.) |
| Local | tokens de Ollama, Whisper, Piper | 0 (el hardware se cuenta con `llm_compute`) |
| Telegram | | 0 |

Vacíos a propósito: Google Cloud Speech-to-Text y Text-to-Speech, TTS de OpenAI (se cobra por token de audio, no por
carácter), jambonz (la tarifa de tu operador), WhatsApp (Meta cobra por mensaje entregado, según país y categoría; los
de servicio tienen 1.000 gratis por número por mes), las horas de CPU de Ollama y el servidor de Parla.

**Tu propia infraestructura.** `llm_compute` / `ollama` es tu costo por hora de CPU. `turn` / `parla` es el costo
mensual del servidor de Parla: se reparte entre todos los turnos de ese mes (de todos los agentes).

## Reportes y API

**Reportes → Costos** (con los mismos filtros que el resto de Reportes): total, por día, promedio / mediana / p95 por
conversación, costo por conversación resuelta (el total dividido por las conversaciones que no pasaron a una
persona), por canal, por tipo (IA, voz a texto, texto a voz, teléfono, mensajería, motor), por proveedor y modelo,
las conversaciones más caras (se abren con un clic) y **Exportar CSV**. Una conversación en **Conversaciones**
muestra su detalle; una campaña muestra su costo.

```sh
curl -s 'http://127.0.0.1:8000/api/v1/bots/clinica/costs?from=2026-11-01&to=2026-11-30&group=channel' \
  -H 'Authorization: Bearer parla_xxxxxxxx'
```

Analista o más. Detalle en [api_es.md](api_es.md#get-apiv1botsbotcosts). Prometheus: `parla_usage_total` y
`parla_cost_total` ([observability_es.md](observability_es.md)).

## Comparar con un proveedor

1. Corré una semana representativa (o re-ejecutá conversaciones reales como pruebas) y mirá el **costo por
   conversación resuelta**.
2. Comparalo con el precio por conversación o por sesión del proveedor para el mismo canal; sumale su cuota de
   plataforma si tiene, y de este lado sumá el costo de tu servidor de Parla (`turn`).
3. Compará lo mismo con lo mismo: una "conversación" para Meta, para Dialogflow (por pedido) y para un contact
   center (por resolución o por minuto) son unidades distintas.

## Advertencias

- Son estimaciones: manda la factura del proveedor. Los precios cambian; mirá la fecha `checked` y actualizá la tabla.
- El uso fuera de una conversación (las corridas de pruebas, escuchar voces en el editor)
  cuenta en las métricas pero no por conversación. El audio que Parla reproduce en una llamada (`tts: parla`) cuenta
  para el agente, no para la llamada.
- Borrar una conversación, o el período de retención, saca su id de la tabla de uso; los totales del día quedan.
- La voz que reconocen Twilio o jambonz (`<Gather>`) la cobran ellos y acá no se mide.
