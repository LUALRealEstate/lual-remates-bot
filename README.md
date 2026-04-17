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
- `runtime_entrypoint.py`: entrada operativa tipo webhook / runtime.
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
- `CLOSER_NOTIFICATION_ENABLED`: activa o desactiva el aviso al closer.
- `CLOSER_PHONE_NUMBER`: destino preparado para integración posterior.
- `ADMIN_USER`: usuario administrativo de referencia.
- `CLOSER_CONSOLE_LOG_PATH`: log local de notificaciones.
- `WHATSAPP_MODE`: `stub` o `production`.
- `WHATSAPP_WEBHOOK_ENABLED`: referencia de modo webhook activo.
- `WHATSAPP_OUTBOUND_ENABLED`: activa el envío saliente por HTTP.
- `WHATSAPP_OUTBOUND_URL`: endpoint del runtime/proveedor saliente.
- `WHATSAPP_AUTH_TOKEN`: token opcional para el POST saliente.
- `WHATSAPP_SOURCE_NUMBER`: identificador del número origen.
- `WHATSAPP_TIMEOUT_SECONDS`: timeout del dispatch saliente.
- `WHATSAPP_DISPATCH_LOG_PATH`: log local de dispatch/stub de WhatsApp.
- `STATE_STORAGE_DIR`: carpeta de estado local.
- `LIVE_API_LOG_PATH`: log JSONL de llamadas reales a OpenAI.

## Ejecutar localmente

```bash
cd "/Users/lualrealestate/lual bot v4/lual_remates_bot"
python3 main.py --phone +5215550000000
```

## Entrada operativa tipo WhatsApp

Procesar un mensaje aislado y obtener JSON:

```bash
cd "/Users/lualrealestate/lual bot v4/lual_remates_bot"
python3 runtime_entrypoint.py message --phone +5215550000000 --text "hola"
```

Levantar un webhook simple local:

```bash
cd "/Users/lualrealestate/lual bot v4/lual_remates_bot"
python3 runtime_entrypoint.py serve --host 127.0.0.1 --port 8787
```

Payload esperado para `POST /whatsapp/incoming`:

```json
{
  "phone_number": "+5215550000000",
  "message": "hola",
  "metadata": {
    "source": "whatsapp-webhook"
  }
}
```

## Correr pruebas

```bash
cd "/Users/lualrealestate/lual bot v4/lual_remates_bot"
python3 -m unittest discover -s tests -v
```

## Modos operativos

Modo local / consola:

- `CLOSER_NOTIFICATION_METHOD=console`
- `WHATSAPP_MODE=stub`
- `WHATSAPP_OUTBOUND_ENABLED=false`

Modo WhatsApp stub:

- `CLOSER_NOTIFICATION_METHOD=whatsapp`
- `CLOSER_PHONE_NUMBER=<SET_ME>`
- `WHATSAPP_MODE=stub`
- `WHATSAPP_OUTBOUND_ENABLED=false`

Modo producción por webhook saliente:

- `CLOSER_NOTIFICATION_METHOD=whatsapp`
- `CLOSER_PHONE_NUMBER=<SET_ME>`
- `WHATSAPP_MODE=production`
- `WHATSAPP_WEBHOOK_ENABLED=true`
- `WHATSAPP_OUTBOUND_ENABLED=true`
- `WHATSAPP_OUTBOUND_URL=https://tu-runtime-o-proveedor/outbound`
- `WHATSAPP_AUTH_TOKEN=<TOKEN_SI_APLICA>`

## Integración hacia producción

1. Mantener `ConversationManager` como núcleo y conectar el webhook entrante a `runtime_entrypoint.py` o `WhatsAppAdapter`.
2. Configurar `WHATSAPP_OUTBOUND_URL` para que el bot envíe respuestas y handoffs al runtime real.
3. Guardar el estado por número de teléfono en un store persistente de producción.
4. Reutilizar el resumen de `CloserHandoffService` para CRM, panel o canal interno.
