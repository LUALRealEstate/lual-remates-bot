from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable, List

from app.bootstrap import build_manager
from app.conversation_manager import BotResult, ConversationManager


class TestHarness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp_dir.name)
        os.environ["ENABLE_LLM_ASSIST"] = "false"
        os.environ["OPENAI_TURN_UNDERSTANDING_ENABLED"] = "false"
        os.environ["STATE_STORAGE_DIR"] = str(self.runtime_root / "state")
        os.environ["CLOSER_CONSOLE_LOG_PATH"] = str(self.runtime_root / "closer_notifications.log")
        os.environ["LIVE_API_LOG_PATH"] = str(self.runtime_root / "live_api_calls.jsonl")
        self.manager: ConversationManager = build_manager(str(root))
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
