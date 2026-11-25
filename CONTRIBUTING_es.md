# Cómo contribuir a Parla

[English](CONTRIBUTING.md) · **Español**

Gracias por ayudar. Parla es un constructor de IA conversacional open source y autoalojado, con licencia
[Apache-2.0](LICENSE), y todas sus funciones viven en este repositorio: no hay una edición cerrada que mantener
aparte. Son bienvenidos los reportes de errores, arreglos de documentación, traducciones, pruebas y código.

Seguí el [Código de conducta](CODE_OF_CONDUCT_es.md). Los problemas de seguridad van por
[SECURITY_es.md](SECURITY_es.md), nunca en un issue público.

## Antes de empezar

- **Arreglo chico** (un error de tipeo, un bug obvio, una prueba que falta): abrí un pull request directamente.
- **Algo más grande** (un tipo de paso nuevo, un canal, una dependencia, un cambio en la API): abrí primero un issue
  para acordar el enfoque. Mirá la [hoja de ruta](docs/ROADMAP_es.md) por si ya está planeado.

## Entorno de desarrollo

Requisitos: Python 3.11 o más nuevo. Node.js es opcional (funciones en JavaScript), igual que
[Ollama](https://ollama.com) (IA local) y `ffmpeg` (voz).

```sh
git clone https://github.com/pedroslev/parla-nlu.git
cd parla-nlu
scripts/setup.sh            # crea .venv e instala requirements.txt (o: make setup)
scripts/setup.sh --voice    # opcional: faster-whisper + piper (o: make setup-voice)
make run                    # http://127.0.0.1:8000
```

El primer entrenamiento baja el modelo de embeddings (~1,2 GB) a `data/models/embeddings`. Con `PARLA_EMBED_CACHE`
podés reusar una copia que ya tengas. Más en [docs/development_es.md](docs/development_es.md).

## Pruebas

```sh
python tests/run_all.py               # todas (o: make test, que usa .venv/bin/python)
python tests/run_all.py app mcp       # algunas, por nombre
python tests/test_app.py              # una sola
```

Las pruebas son scripts con `assert`, sin framework, y nunca tocan tu `data/`. Las de voz se saltean sin los extras
de voz, y la parte con modelo de las de IA se saltea sin Ollama; eso no cuenta como falla. `test_knowledge.py` y
`test_mcp.py` necesitan el modelo de embeddings. La CI corre el mismo comando con Python 3.11 y 3.12 (ver
[`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

Toda lógica no trivial que agregues tiene que dejar una prueba en `tests/`.

## Estilo de código

- **Chico y con la biblioteca estándar primero.** La biblioteca estándar antes que una dependencia nueva, archivos
  JSON antes que una base de datos, sin abstracciones que nadie pidió. Una dependencia nueva necesita una buena
  razón en el pull request.
- **Funciones chicas** que hacen una cosa y se leen de arriba abajo.
- **Los comentarios explican el porqué.** Hoy muchos están en español; los nuevos pueden ir en inglés o en español.
- **Los textos de la interfaz pasan por `t()`** con el texto en español como clave, y cada uno necesita su
  traducción al inglés (ver [Traducciones](#traducciones)). El español es rioplatense y dice qué hacer; el inglés,
  simple, con mayúscula solo al principio y los mismos nombres que el resto de la interfaz.
- **Comentarios `ponytail:`** marcan un atajo deliberado con un límite conocido: nombran el límite y cómo mejorarlo.
- Los módulos opcionales (IA, voz, fechas) nunca pueden cortar una conversación cuando fallan.
- La documentación está en inglés con una copia en español (`nombre_es.md`) y un selector de idioma bajo el
  título. Si cambiás una, actualizá la otra o avisalo en el pull request para que alguien ayude.

Antes de subir, un chequeo rápido:

```sh
python -m compileall -q app.py mcp_server.py parla tests
for f in web/static/*.js; do node --check "$f"; done
python tests/run_all.py
```

## Traducciones

La interfaz está en español y en inglés. La clave es el texto en español, así el código se sigue leyendo igual:

- **Interfaz web** (`web/index.html`, `web/static/*.js`): todo texto visible va dentro de `t()`:
  `t('Crear agente')`, `t('No se pudo guardar: {error}', { error: e.message })`,
  `t.plural(n, '{n} flujo', '{n} flujos')`. Las fechas usan `t.locale`. Después sumá la traducción al bloque `EN`
  de [`web/static/i18n.js`](web/static/i18n.js) (JSON, una entrada por línea, en orden). Una clave sin traducir se
  ve en español; con `localStorage['parla-i18n-debug'] = '1'` la consola avisa cuáles faltan.
- **Mensajes del servidor** que llegan a la interfaz (`error`, `warnings` y `problems` en las respuestas JSON):
  escribilos como texto con `%s` para los datos (`"no existe la función «%s»" % nombre`, no f-string) y sumá el
  inglés a `EN` en [`parla/i18n.py`](parla/i18n.py). La respuesta se traduce según el `Accept-Language` del pedido,
  que la interfaz manda con su idioma. Los logs quedan en español, y lo que el bot le dice a la gente es contenido
  del agente, no interfaz.
- **El widget web** (`web/static/widget.js`) corre en sitios ajenos: tiene su propia tablita `TEXTS`, que se elige
  por el idioma principal del bot (`data-lang`).
- `python tests/test_i18n.py` falla si un texto de `t()` o un mensaje del servidor no tiene inglés, o si los
  `{datos}` / `%s` no coinciden.

**Sumar un idioma** (por ejemplo portugués): agregá `pt: 'Português'` a `LANGS` y un diccionario `PT` a `DICTS` en
`i18n.js` (y su locale en `t.locale`), un diccionario `PT` a `DICTS` en `i18n.py` y una línea `pt` a `TEXTS` en
`widget.js`. Partí de las claves del inglés; lo que falte sale en español. Ampliá `tests/test_i18n.py` para que
revise también los diccionarios nuevos.

## Firmá tus commits (DCO)

Parla usa el [Developer Certificate of Origin](https://developercertificate.org/). Al firmar certificás que
escribiste el cambio o que tenés derecho a enviarlo bajo la licencia del proyecto. Agregá la firma con `-s`:

```sh
git commit -s -m "Qué cambió y por qué"
```

Agrega `Signed-off-by: Tu Nombre <vos@example.com>` al mensaje. ¿Te lo olvidaste? `git commit --amend -s` para el
último commit, o `git rebase --signoff main` para toda la rama.

## Pull requests

1. Creá la rama desde `main`, mantené el cambio enfocado y contá qué y por qué en la plantilla.
2. Corré las pruebas y los chequeos de arriba.
3. Actualizá la documentación (en los dos idiomas si podés) y agregá una entrada en **Unreleased** de
   [CHANGELOG.md](CHANGELOG.md) si el cambio se nota para quien lo usa.

Al contribuir aceptás que tu contribución queda bajo la licencia Apache-2.0.
