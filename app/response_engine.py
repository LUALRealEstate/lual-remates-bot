from __future__ import annotations

from app.state_schema import ConversationState, ResponsePlan


class ResponseEngine:
    CANONICAL_GREETING = "¡Hola! Bienvenido a LUAL Real Estate. ¿En qué puedo ayudarte?"

    def render(self, state: ConversationState, plan: ResponsePlan) -> str:
        body = self._normalize_message(plan.message)
        if not state.greeted and plan.action == "greeting":
            if body:
                return f"{self.CANONICAL_GREETING} {body}"
            return self.CANONICAL_GREETING
        return body

    def _normalize_message(self, message: str) -> str:
        lines = [" ".join(line.split()) for line in message.strip().splitlines()]
        meaningful_lines = [line for line in lines if line]
        return "\n\n".join(meaningful_lines)
