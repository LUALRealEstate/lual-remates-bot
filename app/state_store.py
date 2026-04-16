from __future__ import annotations

import json
from pathlib import Path

from app.state_schema import ConversationState


class StateStore:
    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, phone_number: str) -> Path:
        safe_phone = "".join(ch for ch in phone_number if ch.isdigit() or ch in {"+", "_"})
        safe_phone = safe_phone or "anonymous"
        return self.storage_dir / f"{safe_phone}.json"

    def load(self, phone_number: str) -> ConversationState:
        path = self._path_for(phone_number)
        if not path.exists():
            return ConversationState(phone_number=phone_number)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ConversationState.from_dict(payload)

    def save(self, state: ConversationState) -> None:
        path = self._path_for(state.phone_number)
        path.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def reset(self, phone_number: str) -> None:
        path = self._path_for(phone_number)
        if path.exists():
            path.unlink()
