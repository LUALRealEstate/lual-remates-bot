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
- `WHATSAPP_MODE`: `stub`, `production` o `meta`.
- `WHATSAPP_WEBHOOK_ENABLED`: referencia de modo webhook activo.
- `WHATSAPP_OUTBOUND_ENABLED`: activa el envío saliente por HTTP.
- `WHATSAPP_OUTBOUND_URL`: endpoint del runtime/proveedor saliente.
- `WHATSAPP_AUTH_TOKEN`: token opcional para el POST saliente.
- `WHATSAPP_SOURCE_NUMBER`: identificador del número origen.
- `WHATSAPP_PHONE_NUMBER_ID`: ID del número de WhatsApp Cloud API.
- `WHATSAPP_ACCESS_TOKEN`: token permanente de Meta Cloud API.
- `WHATSAPP_VERIFY_TOKEN`: token usado por Meta para verificar el webhook.
- `WHATSAPP_GRAPH_API_VERSION`: versión del Graph API, por defecto `v23.0`.
- `WHATSAPP_GRAPH_API_BASE_URL`: override opcional para pruebas locales del transporte.
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

Ruta de webhook para Meta Cloud API:

- `GET /meta/webhook` para verificación.
- `POST /meta/webhook` para mensajes entrantes.

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

Modo Meta Cloud API:

- `CLOSER_NOTIFICATION_METHOD=whatsapp`
- `CLOSER_PHONE_NUMBER=<SET_ME>`
- `WHATSAPP_MODE=meta`
- `WHATSAPP_WEBHOOK_ENABLED=true`
- `WHATSAPP_OUTBOUND_ENABLED=true`
- `WHATSAPP_PHONE_NUMBER_ID=<META_PHONE_NUMBER_ID>`
- `WHATSAPP_ACCESS_TOKEN=<META_PERMANENT_TOKEN>`
- `WHATSAPP_VERIFY_TOKEN=<TOKEN_QUE_TAMBIEN_PONES_EN_META>`
- `WHATSAPP_GRAPH_API_VERSION=v23.0`

Para Railway, configura la URL del webhook como:

- `https://TU-DOMINIO-RAILWAY/meta/webhook`

La verificación de Meta llegará por GET con `hub.mode`, `hub.verify_token` y `hub.challenge`. El servidor devuelve el `hub.challenge` cuando el token coincide.

## Integración hacia producción

1. Mantener `ConversationManager` como núcleo y usar `runtime_entrypoint.py serve` como webhook Railway.
2. En Meta, apuntar el webhook a `/meta/webhook` y suscribir eventos de mensajes.
3. Configurar `WHATSAPP_MODE=meta` para que respuestas y handoff usen la misma integración de Graph API.
4. Guardar el estado por número de teléfono en un store persistente de producción.
