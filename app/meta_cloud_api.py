from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from app.config import Settings


META_WEBHOOK_PATH = "/meta/webhook"


class MetaCloudAPIError(RuntimeError):
    """Raised when a Meta Cloud API request or webhook step fails."""


@dataclass
class MetaInboundMessage:
    phone_number: str
    text: str
    metadata: Dict[str, Any]


def _log_preview(text: str, limit: int = 160) -> str:
    cleaned = text.replace("\n", " ").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def is_meta_webhook_verification(path: str) -> bool:
    return urlparse(path).path == META_WEBHOOK_PATH


def verify_meta_webhook(path: str, settings: Settings) -> tuple[int, bytes, str]:
    parsed = urlparse(path)
    params = parse_qs(parsed.query)
    mode = params.get("hub.mode", [""])[0]
    token = params.get("hub.verify_token", [""])[0]
    challenge = params.get("hub.challenge", [""])[0]

    if mode == "subscribe" and token and token == (settings.whatsapp_verify_token or ""):
        return 200, challenge.encode("utf-8"), "text/plain"
    return 403, b"forbidden", "text/plain"


def extract_meta_inbound_messages(payload: Dict[str, Any]) -> List[MetaInboundMessage]:
    inbound_messages: List[MetaInboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = value.get("contacts", [])
            messages = value.get("messages", [])
            if not messages:
                continue
            contact_name = contacts[0].get("profile", {}).get("name") if contacts else None
            for message in messages:
                phone_number = message.get("from") or (contacts[0].get("wa_id") if contacts else None)
                text = _extract_message_text(message)
                if not phone_number or not text:
                    continue
                metadata = {
                    "source": "meta_webhook",
                    "meta_message_id": message.get("id"),
                    "meta_timestamp": message.get("timestamp"),
                    "meta_type": message.get("type"),
                    "contact_name": contact_name,
                    "raw_message": message,
                    "raw_contacts": contacts,
                    "raw_value_metadata": value.get("metadata", {}),
                }
                inbound_messages.append(
                    MetaInboundMessage(
                        phone_number=phone_number,
                        text=text,
                        metadata=metadata,
                    )
                )
    return inbound_messages


def _extract_message_text(message: Dict[str, Any]) -> str:
    message_type = message.get("type")
    if message_type == "text":
        return message.get("text", {}).get("body", "").strip()
    if message_type == "button":
        return message.get("button", {}).get("text", "").strip()
    if message_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            return (
                interactive.get("button_reply", {}).get("title")
                or interactive.get("button_reply", {}).get("id", "")
            ).strip()
        if interactive_type == "list_reply":
            return (
                interactive.get("list_reply", {}).get("title")
                or interactive.get("list_reply", {}).get("id", "")
            ).strip()
    if message_type in {"image", "video", "document"}:
        section = message.get(message_type, {})
        caption = section.get("caption", "").strip()
        if caption:
            return caption
        return f"[{message_type}]"
    if message_type == "location":
        return "[ubicacion]"
    if message_type == "audio":
        return "[audio]"
    return ""


def meta_graph_messages_url(settings: Settings) -> str:
    if not settings.whatsapp_phone_number_id:
        raise MetaCloudAPIError("WHATSAPP_PHONE_NUMBER_ID is not configured.")
    version = settings.whatsapp_graph_api_version.strip() or "v23.0"
    base_url = settings.whatsapp_graph_api_base_url.strip().rstrip("/")
    return f"{base_url}/{version}/{settings.whatsapp_phone_number_id}/messages"


def sanitize_meta_phone_number(phone_number: str) -> str:
    return re.sub(r"[^\d]", "", phone_number)


def send_meta_text_message(
    *,
    settings: Settings,
    to_phone: str,
    message: str,
) -> tuple[int, str]:
    if not settings.whatsapp_access_token:
        raise MetaCloudAPIError("WHATSAPP_ACCESS_TOKEN is not configured.")

    url = meta_graph_messages_url(settings)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": sanitize_meta_phone_number(to_phone),
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message,
        },
    }
    print(
        "[meta_graph] send_attempt "
        f"to={payload['to']} url={url} text='{_log_preview(message)}'",
        flush=True,
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.whatsapp_timeout_seconds,
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(
                "[meta_graph] send_success "
                f"to={payload['to']} status={response.status} body='{_log_preview(body)}'",
                flush=True,
            )
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(
            "[meta_graph] send_error "
            f"to={payload['to']} status={exc.code} body='{_log_preview(body)}'",
            flush=True,
        )
        raise MetaCloudAPIError(f"Meta Cloud API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        print(
            "[meta_graph] send_error "
            f"to={payload['to']} status=connection_error body='{_log_preview(str(exc))}'",
            flush=True,
        )
        raise MetaCloudAPIError(f"Meta Cloud API connection error: {exc}") from exc
