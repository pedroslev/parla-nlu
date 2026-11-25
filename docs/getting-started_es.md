# Primeros pasos: tu primer bot

[English](getting-started.md) · **Español**

Vamos a armar un bot de pizzería que toma pedidos: entiende «quiero una pizza de muzza», pregunta lo que falta
y confirma. Toma unos 15 minutos. (Si querés ver uno terminado, importá `examples/pizzeria.json` con
«Importar agente».)

## 0. Instalar y abrir

```sh
scripts/setup.sh     # o: make setup
make run             # o: .venv/bin/python app.py
```

Abrí `http://127.0.0.1:8000`. La primera vez que entrena, Parla baja el modelo de vectores (~1,2 GB, una sola
vez). Hace falta Python 3.11 o más nuevo. Si preferís un contenedor, ver [deployment.md](deployment_es.md).

En «Tus agentes» creá un agente nuevo y ponele un nombre, por ejemplo «Pizzería».

## 1. Intenciones: qué tiene que entender

En **Construir → Intenciones** creá dos:

- `Saludar`: «hola», «buenas», «buen día», «qué tal».
- `Pedir pizza`: «quiero una pizza», «me mandás una de muzza», «quiero pedir», «dos de fugazza», «quiero hacer un
  pedido».

Con 5 a 10 frases distintas por intención ya anda bien. Variá las palabras, no solo el final.

## 2. Entidades: qué datos sacar del mensaje

En **Entidades** creá:

- `gusto`, del tipo **De una lista de opciones**, con valores `muzzarella`, `fugazza`, `napolitana`. En
  sinónimos poné que «muzza» quiere decir `muzzarella`.
- `cantidad`, del tipo **Un número**.

Ahora marcá los datos dentro de las frases. En la intención `Pedir pizza`, seleccioná «muzza» en «me mandás una
de muzza» y elegí `gusto`. Por dentro queda así:

```
me mandás una de [muzza](gusto)
[dos](cantidad) de [fugazza](gusto)
```

Marcar importa sobre todo para las entidades **Por los ejemplos que marco en las frases** (por ejemplo un
nombre): ahí Parla aprende del contexto y reconoce valores nuevos. Con 3 o más ejemplos marcados en frases
distintas la reconoce mejor.

## 3. Slots: qué recordar

En **Slots** creá `gusto` (conectado a la entidad `gusto`) y `cantidad` (conectado a `cantidad`). Un slot es la
memoria de la conversación: cuando la persona dice un gusto, queda guardado en el slot `gusto`.

## 4. Flujos: qué hacer

En **Flujos** creá:

**Saludo** (se dispara con `Saludar`):
1. Enviar un mensaje: «¡Hola! ¿Qué pizza querés?»

**Pedido** (se dispara con `Pedir pizza`):
1. Hacer una pregunta → slot `gusto`: «¿De qué gusto?» (sumá botones Muzzarella, Fugazza, Napolitana).
2. Hacer una pregunta → slot `cantidad`: «¿Cuántas?»
3. Enviar un mensaje: «Listo: {{ cantidad }} de {{ gusto }}. ¡Ya sale!»
4. Guardar un valor → `gusto`, modo vaciar; lo mismo con `cantidad` (para el próximo pedido).

Una pregunta se saltea sola si el slot ya tiene valor: si la persona dijo «dos de fugazza», el bot va directo a
la confirmación.

## 5. Entrenar

Arriba a la derecha tocá **Entrenar**. Tarda segundos. El registro de entrenamiento muestra:

- cuántas frases se pasaron a vectores,
- si hizo falta entrenar el modelo de entidades,
- la **autoevaluación**: para cada frase, «si no la conociera, ¿a qué intención la mandaría?», con porcentaje de
  acierto y matriz de confusión,
- consejos («`Saludar` tiene 2 frases: sumale al menos 3 más»).

## 6. Probar

Tocá **Probar** para abrir el chat de prueba y elegí **Chat** (o **Llamada (voz)** si instalaste la voz, ver
[ai-and-voice.md](ai-and-voice_es.md#voz)). Escribí «hola», después «quiero dos de muzza». En cada mensaje podés ver
qué intención entendió, con qué confianza, qué entidades encontró y la traza del flujo. Con «Empezar con datos»
arrancás la charla con slots precargados, como lo haría un IVR.

Probá también: «cancelar» a mitad del pedido, «¿cómo?» (repite lo último) o «mejor de fugazza» mientras te
pregunta la cantidad (corrige el dato).

## 7. Publicar

Lo que editás es el **borrador**. Tocá **Publicar**: se congela una versión numerada (v1) con su propio modelo
entrenado. Podés ponerla primero en **Pruebas (staging)**, probarla eligiendo ese entorno en el chat y después
pasarla a **Producción**. En **Versiones** ves qué cambia entre lo publicado y el borrador, y para volver atrás
apuntás producción a la versión anterior.

Mientras producción no tenga ninguna versión, la API responde con el borrador.

## 8. Conectarlo

- **Widget web**: en **Publicar → Widget web** prendelo, agregá la dirección de tu sitio y copiá el `<script>`.
- **API**: en **Publicar → API** está la referencia; ver también [api.md](api_es.md).

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' \
  -d '{"type": "message", "sessionId": "prueba-1", "text": "quiero dos de muzza"}'
```

## Lo que sigue

- [Conceptos](concepts_es.md): todos los tipos de paso y los flujos del sistema.
- [IA local](ai-and-voice_es.md): que el bot entienda más con un modelo chico.
- [Seguridad](security_es.md): creá un usuario antes de compartir Parla con alguien.
