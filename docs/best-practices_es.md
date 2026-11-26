# Buenas prácticas para armar bots

[English](best-practices.md) · **Español**

Una guía corta para quien arma bots de Parla a mano o revisa lo que armó una IA. Cada sección lleva a la
[skill](skills_es.md) con el detalle, los números y los ejemplos. Un bot completo que sigue todo esto:
[`skills/parla-build-bot/examples/dental-clinic.json`](../skills/parla-build-bot/examples/dental-clinic.json).

## De a poco y probando

- Empezá con un saludo, una intención, un flujo y sus pruebas. Validá, creá, probá, y recién ahí sumá lo siguiente.
- Todo cambio es un borrador; la gente solo ve lo que desplegás en producción. Publicá primero en Pruebas (staging).
- Cada error que arreglás se convierte en una prueba de conversación.

Detalle: [`parla-build-bot`](../skills/parla-build-bot/SKILL.md).

## Intenciones y frases

- Una intención por objetivo de la persona; 6 a 12 frases variadas en cada una, cantidades parecidas entre
  intenciones, como escribe tu gente (voseo: «quiero», «pasame», «¿tenés?»).
- Con el modelo de vectores, dos intenciones del mismo tema quedan a solo 0,1–0,2 de distancia: las frases tienen
  que llevar las palabras que las distinguen («cancelar **el turno**», no «cancelar», que se lo lleva el cancelar
  del sistema).
- Leé la autoevaluación del entrenamiento después de cada cambio y arreglá las frases que marca.
- Probá con otras palabras, nunca solo con las frases de entrenamiento (esas siempre dan 1,0).
- Dejá `threshold` en 0,75 salvo que las pruebas muestren frases reales justo por debajo. Las preguntas
  frecuentes no van en intenciones.
- No hagas intenciones para cancelar, repetir o «hablar con una persona»: ya están en los flujos del sistema;
  sumá tus palabras a sus ejemplos.

Detalle: [`parla-nlu-design`](../skills/parla-nlu-design/SKILL.md).

## Entidades y slots

| Dato | Entidad |
|---|---|
| opciones cerradas | `list` con `synonyms` (y `phrasings` para entender respuestas por significado) |
| fecha y hora | `date` (lenguaje natural en español; `dd/mm hh:mm` en cualquier idioma) |
| número, email, teléfono, DNI | el tipo que ya viene |
| otros formatos | `custom` con regex |
| nombres | `examples`, marcada en 3 frases o más |
| texto libre | slot sin entidad |

Con formato o lista, el bot vuelve a preguntar si la respuesta no sirve. Vaciá al final del flujo los slots que se
vuelven a pedir: una pregunta con el slot lleno se saltea.

## Flujos y textos

- Un objetivo por flujo; lo que se repite, como subflujo con `call`.
- Un saludo con 2 a 4 botones cuyo valor sea una frase que dispare la intención (WhatsApp no corre el saludo: las
  intenciones tienen que andar sin él).
- Una pregunta corta por mensaje, diciendo el formato esperado. Confirmá antes de acciones importantes, repitiendo
  los datos. Bifurcá según cada respuesta de una API y el `ok` de cada función.
- Flujos de charla con `"interrupts": false`; urgencias con `"interrupts": "always"` y pase a una persona.
- Botones: 2 a 6, etiquetas de hasta 20 letras (WhatsApp muestra 3 como botones y hasta 10 como lista).
- Voz: frases cortas, sin emojis ni links, opciones dichas, fechas legibles.
- `classify` donde se cumple el objetivo, `handoff` con motivo donde el bot no puede resolver.

Detalle: [`parla-flow-design`](../skills/parla-flow-design/SKILL.md).

## Integraciones y seguridad

- Credenciales solo como `{{ secret.NOMBRE }}` en pasos `http` o entradas `secret.NOMBRE` de funciones, cargadas
  por una persona en «Claves». Nunca en mensajes, nunca en el JSON, nunca pegadas en un chat con una IA.
- `http`: 10 s de espera; status 0 = no conectó; un 4xx/5xx no corta el flujo, así que revisá siempre el status.
  Los valores en la URL van codificados, el cuerpo JSON no: poné solo slots validados.
- Funciones: para lógica de verdad, probadas con `test_function` (camino feliz y un caso borde), guardando y
  manejando `ok`/`error`. No son un sandbox; se apagan con `PARLA_FUNCTIONS=0`.
- Base de conocimiento: pares «P: … R: …», una pregunta por par con varias formas de decirla en la línea «P:»;
  revisá los puntajes con `search_knowledge`.
- La IA es opcional. Con un proveedor de afuera, el texto de las conversaciones sale de tu máquina.
- `pii_redaction` y `retention_days` para los datos personales.

Detalle: [`parla-integrations`](../skills/parla-integrations/SKILL.md).

## Pruebas, versiones y mejora

- Cubrí, por flujo: camino feliz, todo en el primer mensaje, una respuesta inválida, un «no», una integración que
  falla, una interrupción, una pregunta frecuente, algo fuera de tema.
- `says` con una parte distintiva del mensaje o una regex; sin fechas ni texto de la IA.
- Publicar en producción corre las pruebas y frena si fallan. Volver atrás = desplegar la versión anterior.
- Con gente real: `list_unrecognized` → enseñar frases o sumar conocimiento; `get_analytics` para abandono,
  fallbacks y CSAT.

Detalle: [`parla-testing-and-release`](../skills/parla-testing-and-release/SKILL.md). Si venís de Rasa:
[`parla-migrate-from-rasa`](../skills/parla-migrate-from-rasa/SKILL.md).
