# LUAL Remates Bot

Bot conversacional comercial para LUAL Real Estate, construido desde cero para filtrar leads de remates hipotecarios, mostrar catálogo ficticio, responder objeciones de forma segura y escalar una sola vez a un closer o asesor.

## Qué resuelve

- Saludo canónico y tono alineado a LUAL.
- Flujo comercial específico para remates hipotecarios, no real estate tradicional.
- Estado conversacional explícito con stages definidos.
- Guardrails estructurales para evitar loops, regresiones y handoffs repetidos.
- Catálogo ficticio local con Tijuana y Ciudad de México.
- Handoff configurable a closer con resumen compacto.
- Integración real con OpenAI vía Responses API para apoyo semántico y evidencia de llamadas.

## Estructura

- `app/`: núcleo del bot.
- `config/`: contexto de marca y prompt de apoyo para OpenAI.
- `data/`: catálogo ficticio local.
- `tests/`: pruebas unitarias, de flujo y live probe con OpenAI.
- `artifacts/`: estado local, logs y evidencia de integraciones reales.

## Variables de entorno

Usa `.env.example` como base.

- `OPENAI_API_KEY`: clave real para el harness live y apoyo semántico.
- `OPENAI_MODEL`: por defecto `gpt-5-mini`.
- `OPENAI_TIMEOUT_SECONDS`: timeout del request live.
- `ENABLE_LLM_ASSIST`: activa o desactiva la capa de apoyo con OpenAI.
- `OPENAI_TURN_UNDERSTANDING_ENABLED`: activa el fallback semántico de turn understanding.
- `CLOSER_NOTIFICATION_METHOD`: `console` o `whatsapp`.
- `CLOSER_PHONE_NUMBER`: destino preparado para integración posterior.
- `ADMIN_USER`: usuario administrativo de referencia.
- `CLOSER_CONSOLE_LOG_PATH`: log local de notificaciones.
- `STATE_STORAGE_DIR`: carpeta de estado local.
- `LIVE_API_LOG_PATH`: log JSONL de llamadas reales a OpenAI.

## Ejecutar localmente

```bash
cd "/Users/lualrealestate/lual bot v4/lual_remates_bot"
python3 main.py --phone +5215550000000
```

## Correr pruebas

```bash
cd "/Users/lualrealestate/lual bot v4/lual_remates_bot"
python3 -m unittest discover -s tests -v
```

## Integración hacia producción

1. Sustituir `ConsoleNotifier` o `WhatsAppNotifierStub` por un adaptador real de WhatsApp o webhook.
2. Mantener el mismo `ConversationManager` como núcleo y conectar el transporte de entrada/salida.
3. Guardar el estado por número de teléfono en un store persistente de producción.
4. Reutilizar el mismo resumen de `CloserHandoffService` para CRM, panel o canal interno.
