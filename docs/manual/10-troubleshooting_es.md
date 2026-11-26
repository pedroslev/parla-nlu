# 10. Problemas frecuentes y glosario

[English](10-troubleshooting.md) · **Español**

Buscá tu problema abajo. Cada uno empieza por las causas más probables. Si nada funciona, anotá qué hiciste, qué
esperabas y qué pasó (una captura ayuda) y mandáselo a tu administrador. Las [preguntas frecuentes](../faq_es.md)
técnicas tienen más respuestas para Sistemas.

## El bot

### El bot no entiende algo

1. Probalo en el panel **Probar** y leé la línea debajo de tu mensaje.
   - **No estuvo seguro. Lo más parecido: …** → tocá **Enseñarle**, elegí la intención y después **Entrenar**.
   - **Entendió: (otra intención)** → sumá la frase a la intención correcta, entrená y abrí la ventana del
     entrenamiento (tocá **Entrenado …** arriba) para ver **Con qué intenciones se confunde**.
2. ¿**Entrenaste** después del último cambio? Si arriba dice **Hay cambios sin entrenar**, tocá **Entrenar**.
3. ¿Es un **tema nuevo**? Creá una intención y su flujo, o sumá la respuesta en **Conocimiento**.
4. ¿Falla con **clientes reales** pero no con vos? Mirá **Para enseñar**: los clientes escriben distinto que vos.

Ver [Cómo entiende el bot](02-understanding_es.md#cuando-el-bot-no-entiende).

### Responde cosas que nadie preguntó

El bot está demasiado entusiasta: un mensaje que se parece apenas a una intención pasa el mínimo.

- En **Ajustes**, mové **Qué tan seguro tiene que estar para responder** hacia **Estricto**.
- Revisá que ninguna intención tenga frases muy genéricas ("tengo una consulta", "ayuda").
- Si responde desde Conocimiento con textos que no tienen que ver, subí **Qué tan parecido tiene que ser** en
  **Conocimiento**.

### Pregunta lo mismo una y otra vez, o guarda mal un dato

Abrí **Qué tiene anotado el bot**, abajo del panel Probar, y mirá los slots.

- **La respuesta no coincide con la entidad.** Si el slot de la pregunta está unido a una entidad de lista, solo se
  aceptan las opciones de la lista (o sus sinónimos). Sumá el sinónimo (**Enseñarle** debajo del mensaje, o en
  **Entidades**).
- **El slot está unido a la entidad equivocada.** Revisalo en **Slots**. Un slot para texto libre (una dirección, un
  comentario) no debería estar unido a ninguna entidad.
- **Un número de la respuesta "corrigió" otro dato.** Con **Corregir un dato** activado, una respuesta como
  "Corrientes 1234" se puede leer como una corrección de un número que el bot ya preguntó (la cantidad). Preguntá
  primero lo que es texto libre y después lo numérico, o apagá **Corregir un dato**.
- **La pregunta se saltea cuando no lo esperás.** Una pregunta se saltea cuando su slot ya tiene un valor. Si
  reusás un flujo (un segundo pedido), vaciá los slots con **Guardar un valor → dejarlo vacío** al final del flujo.

### El bot no responde nada

- En Probar ves **El flujo no respondió nada. Revisá que tenga algún mensaje.** → el flujo no tiene ningún paso
  **Enviar un mensaje** (o están todos dentro de un camino que no se tomó).
- Un **flujo del sistema** atrapó el mensaje. Las frases muy cortas ("¿cómo?") pueden atrapar preguntas de verdad
  ("¿cómo puedo pagar?"). Revisá **Frases que lo activan** en **Repetir**, **Cancelar** y los demás.
- La conversación está **en la Bandeja** esperando a una persona: el bot no habla hasta que alguien toque
  **Devolver al bot**.

### No veo mis cambios

- ¿Cambiaste frases o entidades? **Entrenar**.
- En el panel Probar, fijate **Qué versión probar**: si dice **Producción (v1)** estás probando la versión
  publicada, no tu borrador.
- Los clientes de tu web, WhatsApp, Telegram o teléfono usan la versión de **Producción**. **Publicá** tus cambios.

### El paso Conversar con IA no funciona

El paso muestra **La IA está apagada**. Prendela en **IA** (y fijate que el modelo esté listo) o pedíselo a tu
administrador. Ver [Conocimiento e IA](04-knowledge-and-ai_es.md).

## Probar y publicar

### No me deja publicar porque fallan tests

Viste **No se publicó: fallaron 1 de 2 pruebas.** Leé la falla: dice, turno por turno, qué se esperaba y qué
llegó.

- Si el que está mal es el **bot**, arreglalo, corré los tests de nuevo y publicá.
- Si el **test** quedó viejo (cambiaste un mensaje a propósito), actualizalo en **Tests** y publicá.
- **Publicar igual** es para emergencias. Arreglá el test enseguida.

### "No hay nada nuevo para publicar"

El borrador es igual a la última versión. Si querías poner una versión que ya existe en Producción, hacelo desde
**Versiones** (**Poner en Producción** o **Pasar a Producción**).

### Publiqué algo mal

Andá a **Versiones** y tocá **Volver a la versión anterior** en la tarjeta de Producción, o **Poner en Producción**
en una versión que andaba. Ver [Volver atrás](05-testing-and-publishing_es.md#volver-atrás).

## La voz no funciona

- **Llamada (voz) aparece gris** o no aparece el botón del micrófono: el navegador no puede usar el micrófono, o la
  voz no está instalada en el servidor. Probá con Chrome o Edge, y pedile a tu administrador que instale la voz (ver
  [ai-and-voice_es.md](../ai-and-voice_es.md#voz)).
- **"No tengo permiso para usar el micrófono"**: tocá el candado de la barra de direcciones, permití el micrófono y
  probá de nuevo.
- **Anda en la compu donde corre Parla pero no desde otras**: los navegadores solo permiten el micrófono en
  direcciones seguras (https). Pedile a Sistemas una dirección con HTTPS.
- **"No escuché nada"**: hablá más cerca del micrófono, o fijate en la configuración de tu compu que esté elegido el
  micrófono correcto.
- **La voz suena rara o en otro idioma**: en **IA → Voz del bot**, elegí una voz del idioma del bot.

## Canales

### WhatsApp no responde

Revisá en **Canales → WhatsApp**, en este orden:

1. **Atender por WhatsApp** está prendido.
2. La **Dirección pública de Parla** está completa y empieza con https://.
3. Ninguna clave dice **Falta**.
4. La URL de devolución de llamada y el token de verificación están cargados en Meta y suscriptos a "messages"
   (preguntale a quien maneja Meta).
5. **Último mensaje recibido**: si dice *ninguno desde que arrancó Parla*, los mensajes no llegan a Parla (dirección o
   configuración de Meta). Si llegan mensajes pero no hay **Última respuesta enviada**, leé **Último error**.
6. La conversación del cliente no está trabada **en la Bandeja** esperando a una persona.
7. Para escribir primero, o después de 24 horas sin mensajes, WhatsApp exige una **plantilla aprobada**.

### Telegram no responde

Prendé **Atender por Telegram**, fijate que el token no diga **Falta** y tocá **Conectar webhook** de nuevo (hace
falta si cambió la dirección pública). Leé **Último error**.

### No aparece el chat en la web

- **Activar el chat en mi sitio** está prendido.
- La dirección de tu sitio está en **Sitios autorizados**, tal cual la muestra el navegador (con y sin www, agregá las
  dos). Si el chat dice *Este sitio no está autorizado para usar este chat*, la dirección no coincide.
- Parla tiene una dirección pública y el código apunta a ella.
- El código está pegado en la página (pedile a quien maneja la web que lo revise).

### Las llamadas no conectan

Fijate que **Atender llamadas** esté prendido, que ninguna clave diga **Falta** y que las dos URL estén pegadas en
el proveedor exactamente donde dice la pantalla. Si fallan los pases a una persona, revisá el número de
**Transferir a una persona**.

## Acceso

### No puedo entrar

- **Usuario o contraseña incorrectos**: no hay botón de "olvidé mi contraseña". Pedile a alguien con rol **Dueño**
  que te ponga una nueva (**Administrar usuarios → Cambiar contraseña**).
- **Con la cuenta de tu empresa (SSO)**: mirá los mensajes en
  [Entrar con la cuenta de tu empresa](09-administration_es.md#entrar-con-la-cuenta-de-tu-empresa-sso).
- **El único dueño perdió la contraseña**: alguien técnico puede recuperar el acceso desde el servidor, pero se
  pierden los demás usuarios y sus claves de API (ver las [preguntas frecuentes](../faq_es.md)). Por eso conviene
  tener dos dueños.

### No veo un agente o una sección

Tu rol o tu lista de agentes no lo incluye. **Atención** trabaja en la Bandeja; **Analista** mira pero no cambia; y
quien no es dueño puede ver solo algunos agentes. Pedíselo a alguien con rol Dueño (ver
[Usuarios y roles](09-administration_es.md#usuarios-y-roles)).

### "No se pudo guardar"

Puede que tu sesión haya vencido, o que no tengas permiso para editar (Analista o Atención). Recargá la página y
volvé a entrar. Si sos Editor y sigue pasando, avisale a tu administrador.

## Glosario

| Término | Qué es |
|---|---|
| **Agente** | Un bot. Cada uno tiene sus intenciones, flujos, ajustes y conversaciones. |
| **API** | La puerta que usan otros programas para hablar con Parla. La usan los desarrolladores. |
| **Auditoría** | El registro de quién cambió qué en Parla. |
| **Bandeja** | Donde tu equipo responde las conversaciones que el bot pasa a una persona. |
| **Borrador** | La versión del bot que estás editando. |
| **Canal** | Dónde pasa la conversación: web, WhatsApp, Telegram, teléfono, chat de prueba. |
| **Clasificación** | Una etiqueta que anota cómo terminó una conversación ("Pedido tomado"), para los reportes. |
| **Clave** | Una contraseña o API key de otro sistema, guardada de forma segura y que no se vuelve a mostrar. |
| **Clave de API** | Una contraseña para un programa, creada para un usuario y con sus mismos permisos. |
| **Conocimiento** | Documentos con los que el bot puede responder. |
| **Entidad** | Un dato que el bot saca de un mensaje: un gusto, un número, una fecha. |
| **Entorno** | Dónde se pone una versión: **Pruebas** (para revisar) o **Producción** (la que usan los clientes). |
| **Entrenar** | Hacer que el bot estudie las frases de ejemplo y las entidades actuales. |
| **Flujo** | El guion de lo que el bot dice y hace para una intención, paso a paso. |
| **Flujo del sistema** | Un comportamiento que el bot ya trae y funciona en cualquier flujo: cancelar, repetir, pasar a una persona… |
| **Frase de ejemplo** | Una forma en que la gente pide algo, usada para enseñarle una intención. |
| **Intención** | Algo que la gente le pide al bot ("pedir una pizza"). |
| **Local** | Corre en tu propia compu o servidor; no se manda nada a otras empresas. |
| **MCP** | Una forma estándar de conectar asistentes de IA y herramientas. La usan **Conectar con IA** y las herramientas del paso Conversar con IA. |
| **Modelo (IA)** | El modelo de lenguaje que hace funcionar la IA, local (Ollama) o de un proveedor. |
| **No entendió** | Lo que hace el bot cuando no entiende ("Perdón, no te entendí"). La *tasa de no entendidos* dice cada cuánto pasa. |
| **Pasar a una persona** | Pasar una conversación del bot a una persona en la Bandeja. |
| **Proveedor** | Una empresa que te corre la IA o la voz (OpenAI, Anthropic, Google…), en general paga y en la nube. |
| **Publicar** | Guardar una versión fija y numerada del bot y ponerla en un entorno. |
| **Rol** | Lo que puede hacer un usuario: Dueño, Editor, Analista o Atención. |
| **Satisfacción** | La nota del 1 al 5 que dan los clientes en la encuesta al final. |
| **Seguridad** | Qué tan seguro está el bot de haber entendido una intención, en porcentaje. |
| **Sinónimo** | Otra forma de decir una opción de una entidad de lista ("muzza" por muzzarella). |
| **Slot** | Un casillero donde el bot anota un dato durante la conversación. |
| **SSO** | Entrar con la cuenta de tu empresa en lugar de una contraseña de Parla. |
| **Test** | Una charla de ejemplo con lo que se espera, que se vuelve a correr para ver que nada se rompió. |
| **Tomar un camino** | Un paso del flujo que hace una cosa u otra según un slot. |
| **Versión** | Una copia fija y numerada del bot (v1, v2…). |
| **Volver atrás** | Poner de nuevo en Producción una versión anterior. |
| **Webhook** | Una dirección a la que otro servicio (WhatsApp, Telegram, Twilio) le manda mensajes a Parla. |
| **Widget web** | El botón de chat para tu sitio. |
| **Dirección pública** | La dirección de internet (https) donde WhatsApp, Telegram, los proveedores de teléfono y tu web pueden llegar a Parla. |
