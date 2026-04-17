from __future__ import annotations

from dataclasses import dataclass

from app.catalog_store import CatalogStore
from app.closer_handoff import CloserHandoffService, LeadSummary
from app.config import Settings
from app.guardrails import Guardrails
from app.response_engine import ResponseEngine
from app.state_machine import StateMachine
from app.state_schema import ConversationState
from app.state_store import StateStore
from app.turn_understanding import TurnUnderstanding


@dataclass
class BotResult:
    reply_text: str
    state: ConversationState
    handoff_summary: LeadSummary | None = None


class ConversationManager:
    def __init__(
        self,
        *,
        settings: Settings,
        state_store: StateStore,
        catalog_store: CatalogStore,
        understanding: TurnUnderstanding,
        state_machine: StateMachine,
        response_engine: ResponseEngine,
        closer_handoff: CloserHandoffService,
    ) -> None:
        self.settings = settings
        self.state_store = state_store
        self.catalog_store = catalog_store
        self.understanding = understanding
        self.state_machine = state_machine
        self.response_engine = response_engine
        self.closer_handoff = closer_handoff

    def handle_message(
        self,
        phone_number: str,
        text: str,
        metadata: dict | None = None,
    ) -> BotResult:
        _ = metadata
        state = self.state_store.load(phone_number)
        state.push_message("user", text)

        signals = self.understanding.analyze(text, state)
        plan = self.state_machine.advance(state, signals)

        guardrail_result = Guardrails.enforce_transition(state, plan, signals)
        if not guardrail_result.valid:
            plan = self.state_machine._plan(
                action="guardrail_recovery",
                message="Mantengamos el hilo actual para no perder contexto. Dime si quieres seguir con esta opción o cambiar la búsqueda de forma explícita.",
                stage=state.stage,
                pending_step=state.pending_step,
                pending_question=state.pending_question,
            )

        reply = self.response_engine.render(state, plan)

        if not state.greeted and plan.action != "post_handoff_ack":
            state.greeted = True

        state.stage = plan.stage
        state.pending_step = plan.pending_step
        state.pending_question = plan.pending_question
        state.mark_action(plan.action)
        state.push_message("assistant", reply)

        handoff_summary = None
        if plan.trigger_handoff and not state.handoff_done:
            state.handoff_done = True
            state.lead_ready_for_closer = True
            handoff_summary = self.closer_handoff.handoff(state)

        self.state_store.save(state)
        return BotResult(reply_text=reply, state=state, handoff_summary=handoff_summary)
