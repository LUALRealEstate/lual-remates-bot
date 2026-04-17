from __future__ import annotations

from app.state_schema import ConversationState, ResponsePlan


class ResponseEngine:
    CANONICAL_GREETING = "¡Hola! Bienvenido a LUAL Real Estate. ¿En qué puedo ayudarte?"

    def render(self, state: ConversationState, plan: ResponsePlan) -> str:
        body = " ".join(plan.message.split())
        if not state.greeted and plan.action == "greeting":
            if body:
                return f"{self.CANONICAL_GREETING} {body}"
            return self.CANONICAL_GREETING
        return body
