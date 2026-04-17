from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable, List

from app.bootstrap import build_manager, build_whatsapp_adapter
from app.conversation_manager import BotResult, ConversationManager
from app.transport_adapter import IncomingMessage, WhatsAppAdapter


class TestHarness:
    def __init__(self, root: Path, env_overrides: dict | None = None) -> None:
        self.root = root
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp_dir.name)
        overrides = env_overrides or {}
        os.environ["ENABLE_LLM_ASSIST"] = "false"
        os.environ["OPENAI_TURN_UNDERSTANDING_ENABLED"] = "false"
        os.environ["STATE_STORAGE_DIR"] = str(self.runtime_root / "state")
        os.environ["CLOSER_CONSOLE_LOG_PATH"] = str(self.runtime_root / "closer_notifications.log")
        os.environ["LIVE_API_LOG_PATH"] = str(self.runtime_root / "live_api_calls.jsonl")
        os.environ["CLOSER_NOTIFICATION_ENABLED"] = "true"
        os.environ["CLOSER_NOTIFICATION_METHOD"] = "console"
        os.environ["CLOSER_PHONE_NUMBER"] = "5210000000000"
        os.environ["WHATSAPP_MODE"] = "stub"
        os.environ["WHATSAPP_WEBHOOK_ENABLED"] = "false"
        os.environ["WHATSAPP_OUTBOUND_ENABLED"] = "false"
        os.environ["WHATSAPP_OUTBOUND_URL"] = ""
        os.environ["WHATSAPP_AUTH_TOKEN"] = ""
        os.environ["WHATSAPP_SOURCE_NUMBER"] = ""
        os.environ["WHATSAPP_TIMEOUT_SECONDS"] = "5"
        os.environ["WHATSAPP_DISPATCH_LOG_PATH"] = str(self.runtime_root / "whatsapp_dispatch.log")
        for key, value in overrides.items():
            os.environ[key] = value
        self.manager: ConversationManager = build_manager(str(root))
        self.adapter: WhatsAppAdapter = build_whatsapp_adapter(str(root))
        self.phone = "+5216640000000"

    def close(self) -> None:
        self.temp_dir.cleanup()

    @property
    def closer_log_path(self) -> Path:
        return self.runtime_root / "closer_notifications.log"

    def send(self, text: str) -> BotResult:
        return self.manager.handle_message(self.phone, text)

    def run(self, messages: Iterable[str]) -> List[BotResult]:
        return [self.send(message) for message in messages]

    def send_via_adapter(self, text: str, metadata: dict | None = None):
        return self.adapter.process_incoming(
            IncomingMessage(
                phone_number=self.phone,
                message=text,
                metadata=metadata or {},
            )
        )

    @property
    def whatsapp_dispatch_log_path(self) -> Path:
        return self.runtime_root / "whatsapp_dispatch.log"
