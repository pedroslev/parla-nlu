# Cómo se compara Parla

[English](comparison.md) · **Español**

Esta página compara Parla con otras plataformas de IA conversacional y chatbots: Rasa Pro / Rasa Studio, NiCE
Cognigy, Kore.ai, Google Dialogflow CX, Microsoft Copilot Studio, Botpress y Voiceflow. La idea es ayudarte a
elegir la herramienta adecuada. No es un benchmark, y cada producto tiene muchas más funciones de las que entran
en una página.

La investigación es **a noviembre de 2026**. Los proveedores cambian precios y funciones seguido, así que revisá
las fuentes enlazadas antes de decidir. Cuando un proveedor no publica algo, esta página lo dice en lugar de
adivinar.

## Parla en un párrafo

Parla es un constructor de chatbots de código abierto con licencia Apache-2.0 que corre localmente en CPU: un
solo proceso de Python (servidor HTTP de la biblioteca estándar), archivos JSON y un archivo SQLite en disco y una interfaz web sin
código en JavaScript puro. Su NLU usa embeddings y vecino más cercano (`google/embeddinggemma-300m` vía
fastembed), un CRF para entidades y reglas de listas, regex y fechas. Los flujos tienen muchos tipos de paso
(preguntas, pedidos HTTP, condiciones, subflujos, envío de archivos, funciones, derivación a una persona, pasos
de IA). El LLM es opcional (Ollama local por defecto, o tu propia key de OpenAI, Claude, Gemini o cualquier endpoint compatible con OpenAI), igual que la voz local
(faster-whisper para transcribir, piper para sintetizar; o tu propia key de OpenAI, Deepgram, ElevenLabs o Google Cloud), incluida una llamada de voz interrumpible en el chat de
prueba. Incluye un servidor MCP con 27 herramientas, un paso de agente de IA que puede llamar funciones, APIs HTTP y herramientas MCP, versiones con `staging` / `production` y rollback,
usuarios, roles y claves de API, inicio de sesión único con OIDC, una bóveda de secretos por agente, una bandeja para la atención humana,
analítica, una cola «para enseñar» con las frases no reconocidas y la reproducción de conversaciones contra otra
versión. Los canales hoy son la API HTTP (`/api/v1`) y un widget web embebible. Se puede desplegar con Docker,
docker-compose, Kubernetes o k3s. La interfaz está en español, inglés y portugués. Parla
tiene un **compromiso de no open core**: todas las funciones siguen siendo de código abierto.

## Tabla resumen

| | Parla | Rasa Pro / Studio | NiCE Cognigy | Kore.ai | Dialogflow CX | Copilot Studio | Botpress | Voiceflow |
|---|---|---|---|---|---|---|---|---|
| Licencia | Apache-2.0, sin open core | Licencia comercial; Developer Edition gratuita [1][2] | Propietaria [3] | Propietaria [5] | Propietaria (servicio de Google Cloud) [7] | Propietaria (servicio de Microsoft) [9] | Nube propietaria; v12 (AGPLv3 / propietaria) discontinuada [11] | SaaS propietario [13] |
| Autoalojamiento | Sí (un proceso, Docker, K8s, k3s) | Sí (Helm / Kubernetes) [2] | Ofrecido según materiales del proveedor; a cotizar [3] | Nube privada / on-premise en el plan enterprise, según guías de terceros [5] | No (Google Cloud) | No (nube de Microsoft) | No para despliegues nuevos (v12 discontinuada) [11] | No figura en la página de precios; alojado en Voiceflow [13] |
| Precio | Gratis | No publicado [2] | A cotizar; una guía de terceros cita un precio de lista de USD 43.080 [3] | A cotizar / no publicado [5] | Por solicitud, publicado (p. ej. USD 0,007 texto, USD 0,012 con playbooks) [7] | Paquetes de créditos (USD 200 / 25.000 créditos / mes) o pago por uso (USD 0,01 / crédito) [9] | Plan gratuito + planes pagos publicados [12] | Por uso para agencias; empresas a pedido [13] |
| Modelos locales / sin conexión | Sí: embeddings, CRF y LLM opcional corren localmente | Proveedores de LLM configurables; es posible usar modelos propios [2] | No documentado públicamente como totalmente offline | No documentado públicamente como totalmente offline | No (modelos de Google) | No (modelos de Microsoft / Azure) | No | No |
| Proveedores de LLM | Ollama local por defecto; tu propia key de OpenAI, Claude, Gemini o cualquier endpoint compatible con OpenAI | Proveedores de LLM configurables [2] | No verificado para esta página | No verificado para esta página | Modelos de Google | Modelos de Microsoft / Azure | No verificado para esta página | No verificado para esta página |
| Voz | STT/TTS local (por defecto) o tu propia key de OpenAI, Deepgram, ElevenLabs o Google Cloud; llamada de voz interrumpible en el chat de prueba; llamadas telefónicas por Twilio o jambonz (DTMF, transferencia) | Sí, vía AudioCodes, Jambonz, navegador [1] | Sí, Voice Gateway [3] | Sí | Sí (audio facturado por segundo) [7] | Sí, voz en tiempo real [10] | Canal de voz en el plan enterprise, según guía de terceros [12] | Sí (voz y chat) [13] |
| Canales | API HTTP, widget web, WhatsApp, Telegram, teléfono (Twilio, jambonz) | Muchos conectores | Muchos | Muchos | Muchas integraciones | Teams, web y canales de Microsoft | Muchos | Muchos |
| MCP | Servidor MCP (27 herramientas) para construir, probar y publicar bots; herramientas MCP en el paso agente (cliente, Streamable HTTP, con allow-list) | Servidor de herramientas MCP para IDE (beta, 3.16) [1] | Herramientas MCP en agentes; endpoint de servidor MCP (experimental) [4] | No verificado en la documentación oficial | No verificado en la documentación oficial | Herramientas MCP en agentes (GA) [10] | MCP en el ADK CLI, según fuentes de terceros [12] | Herramientas MCP en agentes + servidor MCP alojado [14] |
| Analítica | Contención, derivaciones, fallbacks, CSAT, abandono | Panel integrado en Studio 1.16 [1] | Sí | Sí | Sí (Google Cloud) | Sí | Sí | Sí (observabilidad) [13] |
| Observabilidad | Métricas de Prometheus, trazas de OpenTelemetry por OTLP (convenciones GenAI, contexto de traza W3C), logs JSON; privadas por defecto | No verificado para esta página | No verificado para esta página | No verificado para esta página | No verificado para esta página | No verificado para esta página | No verificado para esta página | Funciones de observabilidad [13] |
| Pruebas | Suites de tests de conversación (interfaz, CLI, CI, freno al publicar), autoevaluación, matriz de confusión, reproducción contra otra versión | Sí (pruebas E2E) | Simulador [3] | Sí | Sí | Sí | Sí | Sí |
| SSO | Sí, OIDC (Keycloak, Entra ID, Google, Okta, Authentik, Auth0) | No verificado para esta página | No verificado para esta página | No verificado para esta página | Identidad de Google Cloud | Microsoft Entra ID | No verificado para esta página | No verificado para esta página |

«Sí» sin fuente indica que la función está ampliamente documentada por el proveedor, pero no se volvió a
verificar para esta página.

## Notas por plataforma

### Rasa Pro y Rasa Studio

Rasa Pro usa el enfoque CALM (comprensión con LLM y lógica de negocio determinista) y Rasa Studio suma un editor
sin código. Rasa 3.16 (marzo de 2026) agregó un servidor local de herramientas MCP para que los copilotos del IDE
lean, validen y entrenen un proyecto Rasa, y Studio 1.16 (abril de 2026) incorporó un panel de analítica con
contención y CSAT [1]. La voz funciona a través de AudioCodes y Jambonz. Se despliega en Kubernetes con Helm.
Rasa Pro requiere una licencia comercial; la Developer Edition gratuita es limitada (unas 1.000 conversaciones
por mes según una guía) y el precio para producción no está publicado [2].

**Elegí Rasa si** necesitás una plataforma madura y de gran escala con CALM, socios de telefonía y soporte
empresarial, y una licencia comercial entra en tu presupuesto. **Elegí Parla si** buscás una alternativa de
código abierto a Rasa más liviana (un proceso, sin servidor de base de datos), completamente Apache-2.0 y que corre en una
notebook.

### NiCE Cognigy

Cognigy, hoy parte de NiCE, es una plataforma empresarial de IA para centros de contacto, con Voice Gateway,
muchos canales y un simulador para pruebas [3]. Admite herramientas MCP dentro de los agentes y, desde la versión
2026.5, un endpoint de servidor MCP experimental [4]. El precio es personalizado; una guía de terceros cita un
precio de lista de USD 43.080 [3].

**Elegí Cognigy si** operás un centro de contacto grande y necesitás telefonía nativa, integración con CCaaS y
soporte del proveedor. **Elegí Parla si** querés un bot on-premise sin costo de licencia y con control total del
código.

### Kore.ai

Kore.ai es una plataforma empresarial de IA conversacional y agéntica. En mayo de 2026 anunció Artemis, una
plataforma nativa de IA para sistemas multiagente empresariales [6]. El precio es a cotizar y no está publicado;
las estimaciones de terceros varían mucho [5]. Fuentes de terceros describen opciones de nube privada /
on-premise en su plan superior [5]. No pudimos confirmar soporte de MCP en la documentación propia de Kore.ai.

**Elegí Kore.ai si** necesitás una suite empresarial amplia (orquestación multiagente, muchos canales,
gobernanza) con soporte del proveedor. **Elegí Parla si** tu alcance es un bot acotado que querés operar vos
mismo.

### Google Dialogflow CX

Dialogflow CX (parte de Conversational Agents de Google Cloud) ofrece flujos visuales y playbooks generativos
[8]. Su precio está publicado y es por solicitud: por ejemplo USD 0,007 por solicitud de texto sin IA generativa,
USD 0,012 por solicitud con playbooks, y el audio se factura por segundo [7]. Corre solo en Google Cloud.

**Elegí Dialogflow CX si** ya estás en Google Cloud y querés un servicio administrado con modelos y telefonía de
Google. **Elegí Parla si** necesitás una alternativa autoalojada a Dialogflow donde las conversaciones nunca
salgan de tus servidores.

### Microsoft Copilot Studio

Copilot Studio crea agentes para Microsoft 365, Teams y la web, con orquestación multiagente (incluido A2A) y voz
en tiempo real [10]. Se pueden agregar servidores MCP a los agentes como herramientas (disponible de forma
general) [10]. El licenciamiento se basa en Copilot Credits: paquetes de 25.000 créditos a USD 200 por mes, o pago
por uso a USD 0,01 por crédito [9].

**Elegí Copilot Studio si** tu organización trabaja en Microsoft 365 y quiere agentes dentro de Teams y Power
Platform. **Elegí Parla si** necesitás algo independiente de un tenant en la nube, que funcione sin conexión.

### Botpress

Botpress es una plataforma en la nube con editor visual y un gran ecosistema de integraciones. La versión de
código abierto anterior, Botpress v12 (con licencia dual AGPLv3 / propietaria), fue discontinuada oficialmente y
ya no está disponible para despliegues nuevos [11]. Fuentes de terceros informan un plan gratuito más planes
pagos, un cambio de precios en mayo de 2026 y soporte de MCP en su ADK CLI [12].

**Elegí Botpress si** querés un constructor alojado, centrado en LLM, con muchas integraciones listas. **Elegí
Parla si** querés una alternativa a Botpress autoalojada y de código abierto.

### Voiceflow

Voiceflow es una plataforma alojada para diseñar agentes de voz y chat, con roles de equipo y observabilidad. Su
página de precios ofrece facturación por uso para agencias y precio a pedido para empresas, y los entornos de
producción se alojan en Voiceflow [13]. Los agentes pueden usar herramientas MCP de servidores accesibles desde
internet, y Voiceflow también ofrece un servidor MCP alojado para administrar agentes [14].

**Elegí Voiceflow si** querés una herramienta de diseño colaborativo pulida y un runtime alojado. **Elegí Parla
si** necesitás todo en tu propia máquina, incluida la voz local.

## Lo que Parla todavía no tiene

Ser honestos con lo que falta importa más que una lista larga de funciones. Esto está en la hoja de ruta (ver
[ROADMAP_es.md](ROADMAP_es.md)):

- **Canales:** API HTTP, widget web, WhatsApp (Cloud API), Telegram y teléfono. Todavía no hay Messenger, Teams ni Slack.
- **Telefonía:** llamadas entrantes por Twilio o jambonz (la voz la reconoce el proveedor, turnos pedido/respuesta,
  sin campañas salientes ni audio en streaming); sin conectores de AudioCodes ni de centros de contacto (CCaaS).
- **Escalado horizontal:** Parla es un solo proceso con archivos en disco; está pensado para un servidor chico.
- **Inicio de sesión único con SAML** (el SSO es solo OIDC, ver [sso_es.md](sso_es.md)).

Si alguna de estas es un requisito excluyente hoy, probablemente te convenga una de las plataformas de arriba.

## Cuándo conviene Parla

- Querés un **bot de voz on-premise** o un chatbot que funcione sin GPU y sin mandar datos a la nube.
- Querés una **plataforma de IA conversacional gratuita y de código abierto**, sin plan pago ni funciones open core.
- Armás bots para usuarios hispanohablantes y te sirve el reconocimiento de fechas en español rioplatense y una
  interfaz en español.
- Querés que un asistente de IA (Claude Code, Codex, Cursor) construya y pruebe el bot por vos mediante MCP.

## Fuentes

1. Rasa, "Behind the release notes: product updates, spring 2026" — https://rasa.com/blog/behind-the-release-notes-product-updates-spring-2026
2. Macha, "Rasa AI: complete guide" (terceros) — https://www.getmacha.com/blog/rasa-ai-complete-guide
3. Macha, "Cognigy: complete guide" (terceros) — https://www.getmacha.com/blog/cognigy-complete-guide
4. Cognigy, "Automated Knowledge Synchronization and More with Cognigy.AI 2026.5" — https://www.cognigy.com/product-updates/2026.5 ; MCP en agentes — https://www.cognigy.com/product-updates/model-context-protocol-mcp
5. eesel AI, "Kore.ai pricing 2026" (terceros) — https://www.eesel.ai/blog/kore-ai-pricing
6. Help Net Security, "Kore.ai unveils AI-native platform for enterprise multi-agent systems" (mayo de 2026) — https://www.helpnetsecurity.com/2026/05/22/kore-ai-unveils-ai-native-platform-for-enterprise-multiagent-systems/
7. Google Cloud, precios de Conversational Agents (Dialogflow CX) — https://cloud.google.com/products/conversational-agents/pricing
8. Google Cloud, playbooks de Dialogflow CX — https://docs.cloud.google.com/dialogflow/cx/docs/concept/playbook
9. Microsoft, guía de licenciamiento de Copilot Studio — https://www.microsoft.com/licensing/guidance/microsoft-copilot-studio ; resumen de Copilot Credits — https://learn.microsoft.com/microsoft-copilot-studio/copilot-credits-overview
10. Microsoft, "New and improved: multi-agent orchestration, connected experiences" — https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/new-and-improved-multi-agent-orchestration-connected-experiences ; "MCP is now generally available in Microsoft Copilot Studio" — https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/model-context-protocol-mcp-is-now-generally-available-in-microsoft-copilot-studio
11. Botpress, "Botpress v12 (and self-hosted versions)" — https://botpress.com/docs/learn/guides/advanced/v12 ; repositorio — https://github.com/botpress/v12
12. eesel AI, "Botpress pricing 2026" (terceros) — https://www.eesel.ai/blog/botpress-pricing ; Agents Index, Botpress (terceros) — https://agentsindex.ai/botpress.md
13. Voiceflow, precios — https://www.voiceflow.com/pricing
14. Documentación de Voiceflow, herramienta MCP — https://docs.voiceflow.com/documentation/build/tools/mcp-tool ; resumen de MCP — https://www.voiceflow.com/docs/mcp/overview

## Marcas y correcciones

Todos los nombres de productos y empresas son marcas comerciales o marcas registradas de sus respectivos
titulares. Se usan aquí solo para identificar los productos comparados. Parla no está afiliado, respaldado ni
patrocinado por ninguna de estas empresas.

¿Encontraste algo desactualizado o incorrecto? Las correcciones son bienvenidas: abrí un issue o un pull request
con un enlace a la fuente.
