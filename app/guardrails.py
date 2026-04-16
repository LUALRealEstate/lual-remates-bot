from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.state_schema import ConversationState, ResponsePlan, Stage, TurnSignals


INVALID_NAME_TOKENS = {
    "si",
    "sí",
    "ok",
    "claro",
    "va",
    "sale",
    "cuanto",
    "cuánto",
    "tiempo",
    "tarda",
    "hola",
    "buenas",
}


@dataclass
class GuardrailResult:
    valid: bool
    reason: Optional[str] = None


class Guardrails:
    @staticmethod
    def can_capture_name(candidate: str | None) -> bool:
        if not candidate:
            return False
        normalized = candidate.strip().lower()
        tokens = normalized.replace(",", " ").split()
        if normalized in INVALID_NAME_TOKENS:
            return False
        if any(token in INVALID_NAME_TOKENS for token in tokens):
            return False
        if len(normalized) < 2 or any(ch.isdigit() for ch in normalized):
            return False
        return True

    @staticmethod
    def can_capture_schedule(candidate: str | None) -> bool:
        if not candidate:
            return False
        normalized = candidate.strip().lower()
        if normalized in INVALID_NAME_TOKENS:
            return False
        return any(
            token in normalized
            for token in ["am", "pm", "mañana", "manana", "tarde", "noche", "hoy", ":"]
        ) or any(ch.isdigit() for ch in normalized)

    @staticmethod
    def enforce_transition(
        state: ConversationState,
        plan: ResponsePlan,
        signals: TurnSignals,
    ) -> GuardrailResult:
        if state.property_active and not signals.explicit_search_change:
            if plan.stage in {Stage.DISCOVERY, Stage.CATALOG} and not state.handoff_done:
                return GuardrailResult(False, "Property active cannot regress to discovery/catalog.")

        if not state.property_active and plan.stage in {
            Stage.QUALIFICATION_CASH,
            Stage.QUALIFICATION_TIMELINE,
            Stage.QUALIFICATION_PRODUCT_UNDERSTANDING,
        }:
            return GuardrailResult(False, "Qualification cannot start without active property.")

        if state.no_match_context and state.alternative_catalog_context and not state.property_active:
            if plan.stage in {
                Stage.QUALIFICATION_CASH,
                Stage.QUALIFICATION_TIMELINE,
                Stage.QUALIFICATION_PRODUCT_UNDERSTANDING,
            }:
                return GuardrailResult(False, "Alternative search cannot jump into qualification.")

        if state.handoff_done and plan.action == "handoff_complete":
            return GuardrailResult(False, "Handoff cannot repeat.")

        if state.advisor_offer_accepted and plan.action == "offer_advisor":
            return GuardrailResult(False, "Advisor confirmation cannot repeat.")

        if state.name and plan.action == "ask_name":
            return GuardrailResult(False, "Name capture cannot repeat.")

        if state.appointment_preference and plan.action == "ask_schedule":
            return GuardrailResult(False, "Schedule capture cannot repeat.")

        if state.greeted and plan.action == "greeting":
            return GuardrailResult(False, "Greeting cannot repeat.")

        return GuardrailResult(True)
