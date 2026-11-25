# Hoja de ruta

[English](ROADMAP.md) · **Español**

Hacia dónde va Parla, agrupado por cercanía. Es un plan, no un compromiso de fechas: las prioridades se mueven con lo
que necesitan quienes lo usan. Todo lo que figura acá va a llegar al proyecto open source bajo Apache-2.0; no hay
una edición paga que se guarde funciones.

¿Querés ayudar o necesitás algo antes? Abrí un issue o comentá en uno existente; ver
[CONTRIBUTING_es.md](../CONTRIBUTING_es.md). Para ver cómo se compara Parla hoy con otras plataformas, ver
[comparison_es.md](comparison_es.md).

## Recién salido

- **Inicio de sesión único con OIDC**: entrar con Keycloak, Entra ID, Google Workspace, Okta, Authentik o Auth0,
  con roles mapeados desde los grupos del proveedor y un modo opcional solo SSO. Ver [sso_es.md](sso_es.md).
- **Interfaz en inglés y portugués**: toda la interfaz, los mensajes del servidor y el widget web en español, inglés
  o portugués (pt-BR), a elección de cada usuario (al lado del selector de tema: inicio, menú ⋯ o pantalla de
  entrada), con un idioma por defecto de la instalación en `PARLA_LANG` (`scripts/setup.sh --lang en|es|pt`); los bots con inglés como idioma principal traen en
  inglés los textos de los flujos del sistema. Para sumar un idioma, ver
  [CONTRIBUTING_es.md](../CONTRIBUTING_es.md#traducciones).
- **Canal de WhatsApp** (WhatsApp Business Cloud API) y **canal de Telegram**, con botones, archivos y respuestas
  desde la Bandeja. Ver [channels_es.md](channels_es.md).
- **Importador de proyectos Rasa**: los proyectos de Rasa 3.x, clásicos y CALM, pasan a agentes de Parla, con un
  aviso por todo lo que no se convierte. Ver [migrate-from-rasa_es.md](migrate-from-rasa_es.md).
- **Endpoints de modelos compatibles con OpenAI**: las funciones de IA pueden usar cualquier API compatible con
  OpenAI (vLLM, llama.cpp, LM Studio, OpenAI, Azure OpenAI, Groq, OpenRouter), con la key en Claves. Ollama sigue
  siendo lo que viene por defecto. Ver [ai-and-voice_es.md](ai-and-voice_es.md#endpoints-compatibles-con-openai).
- **Suites de pruebas de conversación**: conversaciones esperadas guardadas en el bot, que se corren desde la
  interfaz, la API, el MCP y la línea de comandos (también en GitHub Actions), y antes de cada publicación a
  producción. Ver [testing-bots_es.md](testing-bots_es.md).
- **Conversaciones en SQLite** (`parla.db`), con migración automática desde los archivos JSON viejos, y **sesiones
  de login que sobreviven a un reinicio**. Ver [deployment_es.md](deployment_es.md#dónde-quedan-los-datos).
- **Retención de conversaciones** por agente y **registro de auditoría** de quién cambió qué. Ver
  [security_es.md](security_es.md#registro-de-auditoría).
- **Enmascarado de datos personales (PII)**: tapar emails, teléfonos, documentos, tarjetas y cuentas bancarias en
  las conversaciones guardadas. Ver [concepts_es.md](concepts_es.md#retención-y-datos-personales).

## Después

- **Telefonía**: llamadas SIP / telefónicas con Jambonz y Twilio, con entrada DTMF, sobre la voz local que ya existe.

## Más adelante

- **Escalado horizontal y Postgres**: varias réplicas sobre almacenamiento compartido, con Postgres como
  alternativa a SQLite.
- **Herramientas en el paso de agente de IA**: que el paso `agent` llame herramientas externas como **cliente MCP**.
- **Observabilidad**: exportar trazas y métricas con OpenTelemetry.
- **Experimentos A/B** entre versiones de flujos o de bots.
- **Campañas salientes**: iniciar conversaciones de forma proactiva (recordatorios, avisos).

## Lo que ya está

Como referencia, lo que Parla hace hoy: constructor sin código, NLU con embeddings + CRF, flujos con muchos tipos de
paso, LLM local opcional, voz local, versiones con `staging`/`production`, usuarios y roles, inicio de sesión único con OIDC, bóveda de secretos,
bandeja, analíticas, API HTTP, widget web, servidor MCP, Docker y Kubernetes. Ver el
[README](../README_es.md#qué-trae).
