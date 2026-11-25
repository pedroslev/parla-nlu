# Migrar desde Rasa

[English](migrate-from-rasa.md) · **Español**

Parla importa un proyecto de Rasa 3.x (NLU clásico con stories y rules, o flows de CALM) y lo convierte en un agente
de Parla. La idea es que tu bot quede andando en Parla en una tarde: la importación hace el grueso del trabajo y te
da una **lista de avisos** con todo lo que no pudo pasar tal cual. Nada se descarta en silencio.

Solo se leen los `.yml`/`.yaml`. El código de tus acciones (`actions/*.py`) nunca se ejecuta ni se importa.

## Cómo se usa

**Desde la interfaz.** En la pantalla de inicio («Tus agentes»), tocá **Importar de Rasa** y elegí un `.zip` con la
carpeta del proyecto (la que tiene `domain.yml`, `config.yml` y `data/`). Se crea el agente, se entrena y un diálogo
muestra los avisos. Comprimilo sin `models/` ni `.venv/` (solo importan los `.yml`; hasta 18 MB).

**Desde la API.** `POST /api/agents/import/rasa` (mismo rol que crear un agente: dueño o editor):

```sh
curl -s http://127.0.0.1:8000/api/agents/import/rasa -H 'Content-Type: application/json' \
  -d "{\"name\": \"Moodbot\", \"zip\": \"$(base64 < moodbot.zip | tr -d '\n')\"}"
# o {"files": {"domain.yml": "...", "data/nlu.yml": "..."}}
```

Devuelve `{"agent": {...}, "warnings": ["..."]}`. Límites del zip: 500 archivos `.yml`, 20 MB descomprimido; las
rutas absolutas o con `..` se saltean (con aviso).

**Desde la línea de comandos** (no necesita Parla corriendo; deja un archivo para cargar con «Importar agente»):

```sh
.venv/bin/python -m parla.rasa_import ruta/al/proyecto-rasa -o moodbot.parla.json
```

Los avisos salen por stderr.

**Desde un asistente de IA (MCP).** La herramienta `import_rasa_project(path, name=None)` lee la carpeta del
proyecto en tu compu y llama a la API. Pedile «importá mi bot de Rasa que está en ~/bots/moodbot y arreglá los avisos».

## Qué pasa a qué

| Rasa | Parla |
|---|---|
| `config.yml` `language: en` | `languages: ["en"]`. En inglés, el fallback y los flujos del sistema (cancelar, repetir, pasar con una persona…) quedan con textos en inglés. Otros idiomas: aviso, traducí los flujos del sistema a mano. |
| `pipeline`, `policies` | Se ignoran (aviso): Parla tiene su propio NLU (embeddings + CRF) y sus flujos. |
| Intent de `nlu` con ejemplos | Intención con el mismo nombre y frases. |
| `[valor](entidad)`, `[texto](entidad:valor)`, `[texto]{"entity": "x", "value": "y"}` | `[texto](x)`; si el valor es otro, queda como sinónimo de la entidad. |
| `role` de una entidad | Una entidad por rol: `city` + role `from` → `city_from`. Los slots con `entity: city, role: from` usan `city_from`. |
| `group` de una entidad | Se ignora (aviso). |
| `synonym:` | `synonyms` de la entidad que usa ese valor. En una entidad aprendida (CRF) Parla guarda el texto como lo escribieron; hay un aviso que sugiere pasarla a lista. |
| `lookup:` con el nombre de una entidad | Entidad `list` con esos valores. |
| `regex:` con el nombre de una entidad | Entidad `custom` con esa regex. Una regex que no es entidad es solo una pista del clasificador en Rasa: se saltea con aviso. |
| Entidad sin marcar llamada `email`, `number`, `phone`, `date`, `time` | El tipo predefinido que corresponde (seguro venía de Duckling o spaCy). |
| Otras entidades | Tipo `examples` (el CRF aprende de las marcas). |
| Slot `from_entity` | Slot con esa `entity`. |
| Slot `from_text`, `from_llm`, sin mappings | Slot sin entidad: guarda la respuesta entera cuando se pregunta. Para `from_llm` hay aviso: prendé la IA y usá «Lo completa la IA» para extraer el dato. |
| Slot `categorical` con `values` y sin entidad | Una entidad `list` con esos valores. |
| Slot `bool` sin entidad | Una entidad `list` `true`/`false` con sinónimos sí/no (en, es, pt). |
| Mappings `from_intent`, `from_trigger_intent`, `custom`, `initial_value`, condiciones del mapping | No se importan (aviso). |
| `responses` `utter_*` | El texto de un paso `message` (o la pregunta de un `ask`). `{slot}` → `{{ slot }}`. |
| Variaciones, variantes por `channel` o `condition` | La primera sin condición ni canal (un aviso las lista). |
| Botones `{title, payload}` | `{label, value}`. Un payload `/intent` pasa a ser la primera frase de esa intención (en Parla tocar un botón es escribir su value); entidades en el payload: aviso. |
| `image`, `attachment`, `custom`, … en una respuesta | No se importan (aviso). |
| `utter_default` | El `fallback` del agente. Una regla `nlu_fallback → utter_x` también lo define. |
| Rules y stories | Se cortan en cada intención de la persona: cada intención → un flujo que la tiene de trigger, con las acciones que la siguen. Gana la primera (rules antes que stories); si otra historia responde distinto a la misma intención hay un aviso (depende del contexto). |
| `or:` de intenciones | El mismo flujo para cada una. |
| `bot:` en una historia | Paso `message`. |
| `forms` + `action: mi_form` | Un paso `ask` por cada `required_slots`, con `utter_ask_<form>_<slot>` o `utter_ask_<slot>` como pregunta. Se suman las acciones de después del form (la regla de «submit» con `condition: active_loop`). |
| `validate_<form>`, `action_ask_<slot>` | No se importan (aviso). Validá con entidades de formato o de lista: rechazan lo que no coincide. |
| Acción personalizada `action_x` | Paso `http` de marcador: `POST http://localhost:5055/webhook` con `{"next_action": "action_x"}` y una `note`. Reemplazalo por la consulta real o una función (aviso). |
| `action_listen`, `action_deactivate_loop`, `active_loop`, `slot_was_set: requested_slot` | Nada (son internos de Rasa). |
| `slot_was_set` de otros slots, `checkpoint`, pasos `user:` de punta a punta, `action_restart` | No se importan (aviso). |
| Intenciones de recuperación `faq/ask_x` + `utter_faq/ask_x` | Una intención y un flujo por pregunta. |
| `flows` de CALM | Un flujo de Parla por flow, con el mismo nombre. |
| `description` del flow | CALM elige el flow con un LLM; Parla necesita frases de ejemplo. Una intención nueva con el nombre del flow y la descripción como única frase (aviso: sumá 5 a 10 frases reales). |
| Intenciones de `nlu_trigger` | Sus frases pasan a la intención del flow. |
| `collect: slot` | Paso `ask` con `utter` o `utter_ask_<slot>`. `ask_before_filling: true` → antes borra el slot. |
| `reset_after_flow_ends` (true por defecto), `persisted_slots` | Los slots preguntados se borran donde termina el flow, salvo los persistidos. |
| `rejections` | No se importan (aviso). |
| `action: utter_x` / acción personalizada | Paso `message` / `http` de marcador (como arriba). |
| `set_slots` | Pasos `set` (`null` → borrar). |
| `link: flow` | `goto` (no vuelve). |
| `call: flow` | `call` (vuelve). |
| `next: id_del_paso` | `goto` a un flujo extra «`<flow> · <id_del_paso>`» con los pasos desde ahí. Los loops andan. |
| `next: END` | Fin del flujo. |
| `next` con `if/then/else` | Pasos `if` anidados. |
| Condiciones `slots.x = v`, `is`, `==`, `!=`, `is not`, `>`, `<`, `slots.x`, `not slots.x`, `is null` | Una `cond` (`eq`, `ne`, `gt`, `lt`, `filled`, `empty`). |
| Otras condiciones (`and`, `or`, `>=`, …) | Se traducen a una `expr` CEL (los float se comparan con `double(x)`). Si no se puede: `expr: "false"` con la original en `note` (aviso). |
| `if` del flow, `always_include_in_prompt`, flows `pattern_*` | No se importan (aviso). Los flujos del sistema de Parla cubren cancelar, repetir, aclarar, pasar con una persona, etc. |
| `endpoints.yml`, `credentials.yml`, `tests/` | No se importan (aviso). |

## Después de importar

1. Leé los avisos. Lo de siempre: sumarle frases a las intenciones que vinieron de flows de CALM y reemplazar los
   pasos `http` de marcador de las acciones personalizadas por la consulta real o una función.
2. Probalo en el chat de prueba (o con `test_conversation` desde el MCP).
3. Publicá cuando se porte bien.

## Límites conocidos

- Las historias se aplanan en «intención → acciones»: lo que depende de lo que pasó antes (contexto de la historia,
  ramas por `slot_was_set`, checkpoints) no se reproduce; hay un aviso en cada caso.
- Las acciones personalizadas no se migran (Parla nunca corre tu código Python de Rasa). Si dejás corriendo el
  servidor de acciones de Rasa, el paso de marcador ya apunta ahí, pero guardar la respuesta en slots queda a tu cargo.
- Lo que CALM entiende con un LLM (generador de comandos, llenar slots de texto libre, reformular) no se reproduce
  sin frases; prendé la IA local de Parla para acercarte.
- En Parla los slots son texto; un `float` comparado en una `cond` con `gt`/`lt` anda, otra lógica numérica puede
  necesitar CEL.
