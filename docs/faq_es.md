# Preguntas frecuentes

[English](faq.md) · **Español**

**¿Necesito GPU o internet?**
No. Todo corre en CPU. Internet solo hace falta para instalar y para bajar los modelos la primera vez (el de
vectores, ~1,2 GB; el de Ollama y los de voz, si los usás). Después, salvo los pasos `http` que vos armes, nada sale de tu máquina.

**¿Necesito la IA para que el bot funcione?**
No. Intenciones, entidades, flujos y la base de conocimiento (en modo extractivo) funcionan sin modelo de
lenguaje. La IA suma: rescatar mensajes dudosos, completar slots, respuestas redactadas y el paso `agent`.

**¿Cuántas frases pongo por intención?**
Entre 5 y 10 distintas ya anda bien. Mirá la autoevaluación después de entrenar: si dos intenciones se
confunden, sumá frases que las diferencien o juntalas.

**Cambié frases y el chat no lo nota.**
Tocá **Entrenar**. El chat usa lo último entrenado. Mientras entrena, el bot sigue atendiendo con lo anterior.

**Cambié el bot y la API sigue respondiendo lo viejo.**
La API habla con **Producción**. Publicá una versión y ponela en producción. (Si nunca publicaste nada, la API
usa el borrador.) Las conversaciones ya empezadas siguen con la versión con la que arrancaron.

**¿Cómo vuelvo atrás?**
En **Versiones**, apuntá producción a la versión anterior. Para deshacer cambios del borrador, «Restaurar» una
versión.

**¿En qué idiomas funciona?**
El modelo de vectores es multilingüe. La interfaz y las fechas están en español; los mensajes del bot se pueden
traducir a portugués e inglés y Parla detecta el idioma del primer mensaje (o lo recibe en `data.idioma`).

**¿Cómo lo pongo en mi web?**
**Publicar → Widget web**: prendelo, agregá la dirección de tu sitio y pegá el `<script>`:
```html
<script src="http://127.0.0.1:8000/static/widget.js" data-bot="pizzeria" data-title="Hablá con nosotros"
        data-color="#2f6bff" data-greeting="¡Hola!" data-position="right" data-voice="false" async></script>
```
Para que lo vea gente de afuera, Parla tiene que estar publicado detrás de un proxy (ver
[deployment.md](deployment_es.md)) y el `src` tiene que apuntar a esa dirección.

**¿Puedo hablarle por voz?**
Sí, con los extras de voz instalados: micrófono en el chat de prueba y en el widget (`data-voice="true"`), y en
**Probar → Llamada (voz)** una conversación entera por voz, como por teléfono, que se puede interrumpir hablando. Ver
[ai-and-voice.md](ai-and-voice_es.md#voz).

**¿El bot puede mandar un PDF o una foto?**
Sí, con el paso «Enviar un archivo» (`file`): subís el archivo desde el mismo paso (hasta 10 MB). El link es público
para quien lo recibe, así que no subas nada privado. Ver [concepts.md](concepts_es.md#file-enviar-un-archivo).

**¿Se puede correr en Docker o Kubernetes?**
Sí: hay `Dockerfile`, `docker-compose.yml` y manifiestos en `deploy/`. Ver [deployment.md](deployment_es.md).

**¿Tiene WhatsApp, Telegram o teléfono?**
Todavía no hay canales integrados. La API HTTP sirve para conectarlo desde tu propio puente o IVR. WhatsApp y
telefonía están en la hoja de ruta.

**¿Cómo paso una conversación a una persona?**
Con un paso `handoff`, o la persona lo pide («quiero hablar con alguien»). Aparece en la **Bandeja**: ahí se toma,
se responde y se devuelve al bot. El widget recibe esas respuestas solo.

**¿Dónde veo lo que el bot no entendió?**
En **Operar → Para enseñar**: agrupado por parecido, con la intención sugerida, para enseñárselo a una intención.

**Olvidé la contraseña del único dueño.**
Con Parla apagado, mové o borrá `users.json` de la carpeta de datos: Parla vuelve a quedar abierto y podés crear
el dueño de nuevo (se pierden los otros usuarios y sus claves de API).

**¿Las funciones son seguras?**
Corren aisladas de la conversación (si fallan, el bot sigue), pero no son un sandbox de seguridad. Leé
[security.md](security_es.md#funciones-no-son-un-sandbox).

**¿Puedo usar otro modelo que no sea de Ollama?**
Sí, cualquier servidor local compatible con OpenAI (LM Studio, llama.cpp server) con `provider: "openai"`.

**¿Cómo cambio el tema?**
Con el selector de la interfaz: Claro, Oscuro o Colorido. Se recuerda en ese navegador.

**¿Cuál es la licencia?**
[Apache-2.0](../LICENSE). Todas las funciones están en el proyecto open source; no hay una edición paga que se
guarde funciones (ver el [README](../README_es.md#licencia)).
