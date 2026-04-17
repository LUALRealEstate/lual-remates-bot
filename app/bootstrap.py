from __future__ import annotations

from app.catalog_store import CatalogStore
from app.closer_handoff import CloserHandoffService
from app.config import Settings, get_settings
from app.conversation_manager import ConversationManager
from app.llm_client import NullLLMClient, OpenAIResponsesClient
from app.response_engine import ResponseEngine
from app.state_machine import StateMachine
from app.state_store import StateStore
from app.transport_adapter import WhatsAppAdapter
from app.turn_understanding import TurnUnderstanding


def build_manager(project_root: str | None = None) -> ConversationManager:
    settings = get_settings(project_root)
    catalog_store = CatalogStore(settings.project_root / "data" / "catalog.json")
    state_store = StateStore(settings.state_storage_dir)
    llm_client = OpenAIResponsesClient(settings) if settings.openai_enabled else NullLLMClient()
    understanding = TurnUnderstanding(
        settings=settings,
        catalog_store=catalog_store,
        llm_client=llm_client if isinstance(llm_client, OpenAIResponsesClient) else None,
    )
    state_machine = StateMachine(catalog_store=catalog_store)
    response_engine = ResponseEngine()
    closer_handoff = CloserHandoffService(settings)
    return ConversationManager(
        settings=settings,
        state_store=state_store,
        catalog_store=catalog_store,
        understanding=understanding,
        state_machine=state_machine,
        response_engine=response_engine,
        closer_handoff=closer_handoff,
    )


def get_live_client(project_root: str | None = None) -> OpenAIResponsesClient:
    settings = get_settings(project_root)
    return OpenAIResponsesClient(settings)


def build_whatsapp_adapter(project_root: str | None = None) -> WhatsAppAdapter:
    settings = get_settings(project_root)
    manager = build_manager(project_root)
    return WhatsAppAdapter(manager=manager, settings=settings)
