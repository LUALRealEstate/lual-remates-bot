from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def load_dotenv(dotenv_path: Path) -> Dict[str, str]:
    loaded: Dict[str, str] = {}
    if not dotenv_path.exists():
        return loaded

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


@dataclass(frozen=True)
class Settings:
    project_root: Path
    openai_api_key: str | None
    openai_model: str
    openai_timeout_seconds: float
    enable_llm_assist: bool
    openai_turn_understanding_enabled: bool
    closer_notification_method: str
    closer_notification_enabled: bool
    closer_phone_number: str | None
    admin_user: str | None
    closer_console_log_path: Path
    whatsapp_mode: str
    whatsapp_webhook_enabled: bool
    whatsapp_outbound_enabled: bool
    whatsapp_outbound_url: str | None
    whatsapp_auth_token: str | None
    whatsapp_source_number: str | None
    whatsapp_phone_number_id: str | None
    whatsapp_access_token: str | None
    whatsapp_verify_token: str | None
    whatsapp_graph_api_version: str
    whatsapp_graph_api_base_url: str
    whatsapp_dispatch_log_path: Path
    whatsapp_timeout_seconds: float
    state_storage_dir: Path
    live_api_log_path: Path

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key and self.enable_llm_assist)


def get_settings(project_root: str | Path | None = None) -> Settings:
    root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    load_dotenv(root / ".env")

    closer_log_path = Path(
        os.environ.get("CLOSER_CONSOLE_LOG_PATH", "artifacts/closer_notifications.log")
    )
    whatsapp_dispatch_log_path = Path(
        os.environ.get("WHATSAPP_DISPATCH_LOG_PATH", "artifacts/whatsapp_dispatch.log")
    )
    state_dir = Path(os.environ.get("STATE_STORAGE_DIR", "artifacts/state"))
    live_log_path = Path(os.environ.get("LIVE_API_LOG_PATH", "artifacts/live_api_calls.jsonl"))

    return Settings(
        project_root=root,
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
        openai_timeout_seconds=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "30")),
        enable_llm_assist=_parse_bool(os.environ.get("ENABLE_LLM_ASSIST"), True),
        openai_turn_understanding_enabled=_parse_bool(
            os.environ.get("OPENAI_TURN_UNDERSTANDING_ENABLED"), True
        ),
        closer_notification_method=os.environ.get("CLOSER_NOTIFICATION_METHOD", "console").strip().lower(),
        closer_notification_enabled=_parse_bool(
            os.environ.get("CLOSER_NOTIFICATION_ENABLED"), True
        ),
        closer_phone_number=os.environ.get("CLOSER_PHONE_NUMBER"),
        admin_user=os.environ.get("ADMIN_USER"),
        closer_console_log_path=(root / closer_log_path).resolve(),
        whatsapp_mode=os.environ.get("WHATSAPP_MODE", "stub").strip().lower(),
        whatsapp_webhook_enabled=_parse_bool(
            os.environ.get("WHATSAPP_WEBHOOK_ENABLED"), False
        ),
        whatsapp_outbound_enabled=_parse_bool(
            os.environ.get("WHATSAPP_OUTBOUND_ENABLED"), False
        ),
        whatsapp_outbound_url=os.environ.get("WHATSAPP_OUTBOUND_URL"),
        whatsapp_auth_token=os.environ.get("WHATSAPP_AUTH_TOKEN"),
        whatsapp_source_number=os.environ.get("WHATSAPP_SOURCE_NUMBER"),
        whatsapp_phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID"),
        whatsapp_access_token=os.environ.get("WHATSAPP_ACCESS_TOKEN"),
        whatsapp_verify_token=os.environ.get("WHATSAPP_VERIFY_TOKEN"),
        whatsapp_graph_api_version=os.environ.get("WHATSAPP_GRAPH_API_VERSION", "v23.0"),
        whatsapp_graph_api_base_url=os.environ.get(
            "WHATSAPP_GRAPH_API_BASE_URL",
            "https://graph.facebook.com",
        ).rstrip("/"),
        whatsapp_dispatch_log_path=(root / whatsapp_dispatch_log_path).resolve(),
        whatsapp_timeout_seconds=float(os.environ.get("WHATSAPP_TIMEOUT_SECONDS", "15")),
        state_storage_dir=(root / state_dir).resolve(),
        live_api_log_path=(root / live_log_path).resolve(),
    )
