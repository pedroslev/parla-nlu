# Probar bots (suites de pruebas de conversación)

[English](testing-bots.md) · **Español**

Una **prueba** es una conversación que escribís una vez (qué dice la persona, qué tiene que entender y contestar el
bot) y que corrés de nuevo después de cada cambio. Es una prueba de regresión para el bot: si retocás una intención,
un flujo o un prompt y se rompe algo que andaba, la prueba falla antes de que lo note la gente. Es la misma idea que
las pruebas end-to-end de Rasa o el simulador de Cognigy, pero corre local, en la interfaz, por la API y en tu CI.

En la interfaz, la sección se llama **Tests** (para no confundirla con el entorno «Pruebas», que es staging).

## Formato

Las pruebas se guardan adentro del JSON del agente, en `"tests": [...]`. Por eso viajan con el agente: se exportan e
importan (el archivo `.parla.json`), forman parte de cada versión publicada (restaurar una versión también restaura
sus pruebas) y aparecen en el diff de versiones (`tests`, «Tests»).

```json
{"name": "Pedido completo", "start": {"nombre": "Ana"}, "environment": "draft",
 "turns": [
   {"user": "hola", "intent": "Saludar", "flow": "Tomar pedido", "says": "¿Cuál es tu nombre?"},
   {"user": "Juan", "slots": {"nombre": "Juan"}, "says": "/(?i)apellido/"},
   {"user": "Sí", "buttons": ["Confirmar"], "handoff": false}
 ]}
```

### Campos de una prueba

| Campo | Qué es |
|---|---|
| `name` | Obligatorio y único dentro del agente. |
| `start` | Opcional. Datos de inicio: los campos que se llaman como un slot lo precargan, igual que `data` en el evento `start` de la API (ver [api_es.md](api_es.md#start-empezar-con-datos-precargados)). El flujo `__start__` corre antes del primer turno. |
| `environment` | Opcional: `draft` (por defecto), `staging` o `production`. |
| `turns` | La lista de turnos, en orden. |

### Campos de un turno

`user` es lo que escribe la persona. Para tocar un botón, escribí su valor o su texto. Solo el **primer** turno puede
no tener `user`: entonces revisa lo que dice el bot al empezar la conversación (el saludo del flujo `__start__`).

Todo lo demás son expectativas, y todas son opcionales: solo se revisa lo que escribas.

| Expectativa | Pasa cuando |
|---|---|
| `intent` | La intención que entendió es esa. La respuesta a una pregunta (un slot) y un fallback por poca confianza cuentan como sin intención. |
| `says` | Todo lo que dijo el bot en ese turno (unido con saltos de línea) contiene ese texto, sin importar mayúsculas. O, escrita entre barras (`/.../`), cumple esa expresión regular de Python: distingue mayúsculas salvo que le pongas `(?i)`. |
| `buttons` | Cada elemento está entre los textos o valores de los botones que ofreció. |
| `slots` | Solo se comparan los slots que pongas, como texto y sin importar mayúsculas. Los demás pueden tener cualquier cosa. |
| `flow` | El flujo que está corriendo al final del turno o, si ya terminó, el último flujo que empezó en ese turno. |
| `handoff` | `true` o `false`: si una persona tomó la conversación. |

Un turno en el que falló un paso (un mensaje del bot que empieza con «⚠») falla solo, salvo que tenga un `says`.

[`examples/pizzeria.json`](../examples/pizzeria.json) trae dos pruebas: «Pedido completo» y «Pedido directo con el
nombre precargado».

## Cómo corren

- En memoria, con el motor: no se guarda ninguna sesión. Las pruebas nunca aparecen en Conversaciones, Bandeja, Para
  enseñar, Reportes ni en la analítica.
- Los pasos `http`, las funciones y la IA (el paso `agent` y el fallback generativo) corren **de verdad**. Ver
  [limitaciones](#limitaciones).
- Contra `draft`, usan la definición actual del borrador. Si cambiaron intenciones o entidades desde el último
  entrenamiento, se entrena aparte un modelo descartable solo para las pruebas: el modelo del chat no se toca.
- `staging` y `production` corren contra la versión publicada ahí.

## En la interfaz

**Tests** está en el menú lateral, en el grupo «Publicar», arriba de «Versiones».

- Lista las pruebas. **Correr todos** corre la suite entera y **Correr** una sola, contra el entorno que elijas.
- Cada turno se ve en verde o en rojo; las revisiones que fallaron dicen «esperaba … / recibió …».
- Las expectativas se editan ahí mismo: intención (una lista), says, botones (separados por coma), slots
  (`slot=valor`, separados por coma), flujo (una lista) y handoff (una casilla). También se editan los datos de
  inicio y se agregan o sacan turnos y pruebas.

### «Guardar como test»

La forma más rápida de escribir una prueba: tener la conversación y guardarla. El botón está en **Conversaciones**
(sobre una conversación abierta) y en el panel de chat **Probar**. Convierte la transcripción en una prueba con las
expectativas completadas con lo que pasó: la intención, `says` con el último mensaje del bot en cada turno, los
botones que ofreció y, en el último turno, los slots finales.

Después revisala y aflojá lo que cambia de una corrida a otra (fechas, nombres, cómo lo dice la IA): acortá `says` a
la parte que importa, o usá una regex.

## Freno al publicar

Publicar en **Producción** corre antes toda la suite contra el borrador, si el agente tiene pruebas. Si falla alguna,
no se publica nada.

- En la interfaz, el diálogo de publicar muestra las fallas y un botón **Publicar igual**.
- En la API, `POST /api/agents/{id}/versions` con `"environment": "production"` responde 409:

  ```json
  {"error": "No se publicó en Producción: fallaron 1 de 3 pruebas: «Pedido completo». …",
   "tests": {"passed": false, "total": 3, "failed": 1, "tests": [...]}}
  ```

  Mandá `"force": true` para publicar igual.

No tienen freno: publicar en `staging`, crear una versión sin entorno y `POST /api/agents/{id}/deploy` (mover una
versión que ya existe, incluido un rollback).

## API

Las pruebas son parte del agente: se leen con `GET /api/agents/{id}` y se cambian con `PUT /api/agents/{id}` (campo
`tests`). Solo dueños y editores las pueden editar. Dueños, editores y analistas las pueden correr (correrlas no
cambia nada).

```sh
curl -s http://127.0.0.1:8000/api/agents/654a0008/tests/run \
  -H 'Content-Type: application/json' -d '{"environment": "draft", "names": ["Pedido completo"]}'
```

Los dos campos son opcionales: `environment` pisa el de cada prueba, y `names` corre solo esas pruebas.

```json
{"passed": false, "total": 1, "failed": 1,
 "tests": [{"name": "Pedido completo", "environment": "draft", "version": null, "passed": false,
            "turns": [{"user": "hola", "passed": false,
                       "failures": [{"check": "intent", "expected": "Saludar", "got": null}],
                       "got": {"intent": null, "says": "No te entendí.", "buttons": [], "slots": {},
                               "flow": null, "handoff": false}}]}]}
```

| Campo | Qué es |
|---|---|
| `passed`, `total`, `failed` | Resumen de la corrida. |
| `tests[].error` | Solo si la prueba no se pudo correr (por ejemplo, está mal armada). |
| `turns[].failures` | `[{"check", "expected", "got"}]`. `check` es `says`, `intent`, `buttons`, `slots.<nombre>`, `flow`, `handoff` o `error`. |
| `turns[].got` | Lo que pasó: `intent`, `says`, `buttons`, `slots` (los que tienen valor), `flow`, `handoff`. |

Referencia completa en [api_es.md](api_es.md#versiones).

## Línea de comandos y CI

```sh
.venv/bin/python -m parla.bottests examples/pizzeria.json
```

Recibe el JSON del agente o un `.parla.json` exportado, lo carga en una carpeta de datos descartable, lo entrena y
corre sus pruebas. Imprime `ok` o `FALLÓ` por prueba, las líneas de cada falla y un resumen. Sale con código 1 si
falla alguna (o si el archivo no tiene pruebas) y 0 si no. `--env` solo acepta `draft` (el valor por defecto): un
archivo solo tiene el borrador. Con `GITHUB_ACTIONS=true` además imprime anotaciones `::error`, así las fallas
aparecen en el pull request.

No necesita Parla andando, pero sí los requisitos de Parla y el modelo de vectores (`google/embeddinggemma-300m`,
~1,2 GB), que se baja a `PARLA_EMBED_CACHE` (por defecto `data/models/embeddings`). En CI, guardá esa carpeta en
caché.

El CI de Parla corre `python -m parla.bottests examples/pizzeria.json` después de las pruebas unitarias.

### GitHub Actions para tu bot

Exportá tu bot («Exportar agente», el archivo `.parla.json`), subilo a tu repositorio y copiá este workflow en
`.github/workflows/bot-tests.yml`. Cambiá `bots/mybot.parla.json` por la ruta de tu archivo.

```yaml
name: Bot tests

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  bot-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      PARLA_EMBED_CACHE: ${{ github.workspace }}/.cache/embeddings
      HF_HOME: ${{ github.workspace }}/.cache/hf
    steps:
      - uses: actions/checkout@v4                 # tu repositorio, con el bot exportado
      - uses: actions/checkout@v4                 # Parla, en ./parla
        with:
          repository: pedroslev/parla-nlu
          path: parla
          # ref: v0.9.0                           # fijá un tag o commit para corridas reproducibles
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: parla/requirements.txt
      - run: pip install -r parla/requirements.txt
      - name: Embedding model name
        id: model
        run: echo "name=$(grep -Po '^MODEL = "\K[^"]+' parla/parla/server.py)" >> "$GITHUB_OUTPUT"
      - uses: actions/cache@v4
        with:
          path: .cache/embeddings
          key: embed-${{ steps.model.outputs.name }}
      - name: Run the bot's tests
        run: python -m parla.bottests bots/mybot.parla.json
        env:
          PYTHONPATH: parla
```

La primera corrida baja el modelo (~1,2 GB); las siguientes lo sacan de la caché. Si el bot usa claves en pasos
`http`, dejá esas pruebas afuera del CI o apuntalas a un servicio de prueba (ver abajo): las claves no viajan en el
archivo exportado.

## Limitaciones

- **La IA y las APIs en vivo son reales.** Las pruebas que pasan por IA generativa (el paso `agent`, el fallback
  generativo) o llaman servicios en vivo con pasos `http` o funciones pueden fallar de a ratos. Dejalas afuera de la
  suite que frena la publicación a producción, o revisá de forma floja (un `says` corto, una regex, solo `intent` o
  `flow`).
- **Solo se frena publicar a producción.** `deploy` (mover una versión que ya existe, un rollback) y publicar a
  staging nunca corren las pruebas.
- **Las regex usan la sintaxis de Python** (`re`) y distinguen mayúsculas salvo que empiecen con `(?i)`.
- **Fechas y otros valores que cambian.** Un `says` con la fecha de hoy pasa hoy y falla mañana. Revisá la parte
  fija del mensaje, o usá una regex como `/\d{2}\/\d{2}/`.
- En la línea de comandos `--env` solo acepta `draft`; para probar `staging` o `production`, usá la API, la interfaz
  o el MCP.
