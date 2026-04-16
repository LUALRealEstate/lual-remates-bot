from __future__ import annotations

import unittest

from app.guardrails import Guardrails
from app.state_schema import ConversationState, ResponsePlan, Stage, TurnSignals


class GuardrailTests(unittest.TestCase):
    def test_rejects_ambiguous_name(self) -> None:
        self.assertFalse(Guardrails.can_capture_name("sí"))
        self.assertFalse(Guardrails.can_capture_name("cuánto tiempo"))
        self.assertTrue(Guardrails.can_capture_name("Omar"))

    def test_rejects_ambiguous_schedule(self) -> None:
        self.assertFalse(Guardrails.can_capture_schedule("ok"))
        self.assertFalse(Guardrails.can_capture_schedule("claro"))
        self.assertTrue(Guardrails.can_capture_schedule("4pm"))
        self.assertTrue(Guardrails.can_capture_schedule("mañana por la tarde"))

    def test_blocks_qualification_without_property(self) -> None:
        state = ConversationState(phone_number="+1")
        plan = ResponsePlan(action="ask_cash", message="...", stage=Stage.QUALIFICATION_CASH)
        result = Guardrails.enforce_transition(state, plan, TurnSignals(raw_text="si", normalized_text="si"))
        self.assertFalse(result.valid)

    def test_blocks_repeated_handoff(self) -> None:
        state = ConversationState(phone_number="+1", handoff_done=True, stage=Stage.HANDED_OFF)
        plan = ResponsePlan(action="handoff_complete", message="...", stage=Stage.HANDED_OFF)
        result = Guardrails.enforce_transition(state, plan, TurnSignals(raw_text="hola", normalized_text="hola"))
        self.assertFalse(result.valid)
