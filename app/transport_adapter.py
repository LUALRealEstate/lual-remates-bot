from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.config import Settings
from app.conversation_manager import BotResult, ConversationManager
from app.whatsapp_transport import OutboundDispatchResult, WhatsAppTransportClient


@dataclass
class IncomingMessage:
    phone_number: str
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterResult:
    phone_number: str
    reply_text: str
    state: Dict[str, Any]
    handoff_summary: Optional[Dict[str, Any]] = None
    outbound_result: Optional[OutboundDispatchResult] = None


class WhatsAppAdapter:
    def __init__(
        self,
        *,
        manager: ConversationManager,
        settings: Settings,
        outbound_client: WhatsAppTransportClient | None = None,
    ) -> None:
        self.manager = manager
        self.settings = settings
        self.outbound_client = outbound_client or WhatsAppTransportClient(settings)

    def process_incoming(self, incoming: IncomingMessage) -> AdapterResult:
        bot_result: BotResult = self.manager.handle_message(
            incoming.phone_number,
            incoming.message,
            metadata=incoming.metadata,
        )
        outbound_result = None
        should_dispatch = self.settings.whatsapp_outbound_enabled or self.settings.whatsapp_mode == "meta"
        if should_dispatch:
            outbound_result = self.outbound_client.send_text(
                to_phone=incoming.phone_number,
                message=bot_result.reply_text,
                metadata={
                    "direction": "lead_reply",
                    "phone_number": incoming.phone_number,
                    **incoming.metadata,
                },
            )

        return AdapterResult(
            phone_number=incoming.phone_number,
            reply_text=bot_result.reply_text,
            state=bot_result.state.to_dict(),
            handoff_summary=bot_result.handoff_summary.to_dict()
            if bot_result.handoff_summary
            else None,
            outbound_result=outbound_result,
        )
