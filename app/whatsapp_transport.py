from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.config import Settings
from app.meta_cloud_api import MetaCloudAPIError, send_meta_text_message


class WhatsAppDispatchError(RuntimeError):
    """Raised when outbound WhatsApp dispatch fails."""


@dataclass
class OutboundDispatchResult:
    channel: str
    target_phone: str
    success: bool
    status_code: int | None = None
    body_preview: str | None = None


class WhatsAppTransportClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.whatsapp_dispatch_log_path.parent.mkdir(parents=True, exist_ok=True)

    def send_text(
        self,
        *,
        to_phone: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OutboundDispatchResult:
        payload = {
            "channel": "whatsapp",
            "mode": self.settings.whatsapp_mode,
            "to": to_phone,
            "from": self.settings.whatsapp_source_number,
            "message": message,
            "metadata": metadata or {},
        }

        if self.settings.whatsapp_mode == "meta" and self.settings.whatsapp_outbound_enabled:
            try:
                status_code, body = send_meta_text_message(
                    settings=self.settings,
                    to_phone=to_phone,
                    message=message,
                )
            except MetaCloudAPIError as exc:
                raise WhatsAppDispatchError(str(exc)) from exc
            result = OutboundDispatchResult(
                channel="whatsapp_meta",
                target_phone=to_phone,
                success=True,
                status_code=status_code,
                body_preview=body[:200],
            )
        elif self.settings.whatsapp_outbound_enabled and self.settings.whatsapp_outbound_url:
            headers = {"Content-Type": "application/json"}
            if self.settings.whatsapp_auth_token:
                headers["Authorization"] = f"Bearer {self.settings.whatsapp_auth_token}"
            request = urllib.request.Request(
                self.settings.whatsapp_outbound_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.settings.whatsapp_timeout_seconds,
                ) as response:
                    body = response.read().decode("utf-8", errors="replace")
                    result = OutboundDispatchResult(
                        channel="whatsapp",
                        target_phone=to_phone,
                        success=True,
                        status_code=response.status,
                        body_preview=body[:200],
                    )
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise WhatsAppDispatchError(
                    f"WhatsApp outbound HTTP {exc.code}: {body}"
                ) from exc
            except urllib.error.URLError as exc:
                raise WhatsAppDispatchError(f"WhatsApp outbound connection error: {exc}") from exc
        else:
            result = OutboundDispatchResult(
                channel="whatsapp_stub",
                target_phone=to_phone,
                success=True,
                status_code=None,
                body_preview="stub dispatch",
            )

        self._log_dispatch(payload=payload, result=result)
        return result

    def _log_dispatch(self, *, payload: Dict[str, Any], result: OutboundDispatchResult) -> None:
        entry = {"payload": payload, "result": result.__dict__}
        with self.settings.whatsapp_dispatch_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
