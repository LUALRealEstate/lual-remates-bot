from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Stage(str, Enum):
    OPENING = "opening"
    DISCOVERY = "discovery"
    CATALOG = "catalog"
    NO_MATCH = "no_match"
    ALTERNATIVE_DISCOVERY = "alternative_discovery"
    PROPERTY_ACTIVE = "property_active"
    QUALIFICATION_CASH = "qualification_cash"
    QUALIFICATION_TIMELINE = "qualification_timeline"
    QUALIFICATION_PRODUCT_UNDERSTANDING = "qualification_product_understanding"
    OBJECTION_HANDLING = "objection_handling"
    CONTACT_CAPTURE = "contact_capture"
    PENDING_NAME = "pending_name"
    PENDING_SCHEDULE = "pending_schedule"
    HANDED_OFF = "handed_off"
    CLOSED_OUT = "closed_out"


class TriState(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class CustomerProfile(str, Enum):
    PATRIMONIAL = "patrimonial"
    INVERSIONISTA = "inversionista"
    UNKNOWN = "unknown"


@dataclass
class MessageRecord:
    role: str
    text: str


@dataclass
class PropertyRecord:
    id: str
    ciudad: str
    zona: str
    tipo: str
    recamaras: int
    banos: float
    m2: int
    valor_comercial: str
    precio_oportunidad: str
    descuento_estimado: str
    resumen_corto_comercial: str


@dataclass
class LLMTrace:
    model: str
    response_id: str
    latency_ms: int
    prompt_name: str


@dataclass
class ConversationState:
    phone_number: str
    stage: Stage = Stage.OPENING
    city_interest: Optional[str] = None
    zone_interest: Optional[str] = None
    selected_property_id: Optional[str] = None
    selected_property_summary: Optional[str] = None
    property_active: bool = False
    no_match_context: bool = False
    alternative_catalog_context: bool = False
    has_cash: TriState = TriState.UNKNOWN
    accepts_timeline: TriState = TriState.UNKNOWN
    understands_product: TriState = TriState.UNKNOWN
    customer_profile: CustomerProfile = CustomerProfile.UNKNOWN
    advisor_offer_accepted: bool = False
    advisor_request_pending: bool = False
    name: Optional[str] = None
    appointment_preference: Optional[str] = None
    handoff_done: bool = False
    lead_ready_for_closer: bool = False
    pending_step: Optional[str] = None
    pending_question: Optional[str] = None
    last_bot_action: Optional[str] = None
    recent_messages: List[MessageRecord] = field(default_factory=list)
    greeted: bool = False
    handled_objections: List[str] = field(default_factory=list)
    active_objection: Optional[str] = None
    disqualification_reason: Optional[str] = None
    action_history: List[str] = field(default_factory=list)
    llm_traces: List[LLMTrace] = field(default_factory=list)
    last_catalog_property_ids: List[str] = field(default_factory=list)

    def push_message(self, role: str, text: str) -> None:
        self.recent_messages.append(MessageRecord(role=role, text=text))
        self.recent_messages = self.recent_messages[-12:]

    def mark_action(self, action: str) -> None:
        self.last_bot_action = action
        self.action_history.append(action)
        self.action_history = self.action_history[-30:]

    def add_llm_trace(self, trace: LLMTrace) -> None:
        self.llm_traces.append(trace)
        self.llm_traces = self.llm_traces[-10:]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["stage"] = self.stage.value
        payload["has_cash"] = self.has_cash.value
        payload["accepts_timeline"] = self.accepts_timeline.value
        payload["understands_product"] = self.understands_product.value
        payload["customer_profile"] = self.customer_profile.value
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ConversationState":
        payload = dict(payload)
        payload["stage"] = Stage(payload.get("stage", Stage.OPENING.value))
        payload["has_cash"] = TriState(payload.get("has_cash", TriState.UNKNOWN.value))
        payload["accepts_timeline"] = TriState(
            payload.get("accepts_timeline", TriState.UNKNOWN.value)
        )
        payload["understands_product"] = TriState(
            payload.get("understands_product", TriState.UNKNOWN.value)
        )
        payload["customer_profile"] = CustomerProfile(
            payload.get("customer_profile", CustomerProfile.UNKNOWN.value)
        )
        payload["recent_messages"] = [
            MessageRecord(**message) for message in payload.get("recent_messages", [])
        ]
        payload["llm_traces"] = [LLMTrace(**item) for item in payload.get("llm_traces", [])]
        return cls(**payload)


@dataclass
class TurnSignals:
    raw_text: str
    normalized_text: str
    greeting: bool = False
    wants_catalog: bool = False
    wants_info: bool = False
    explicit_search_change: bool = False
    requested_advisor: bool = False
    asks_next_step: bool = False
    mentions_property_interest: bool = False
    affirmative: bool = False
    negative: bool = False
    city: Optional[str] = None
    zone: Optional[str] = None
    selected_property_id: Optional[str] = None
    cash_signal: TriState = TriState.UNKNOWN
    timeline_signal: TriState = TriState.UNKNOWN
    product_signal: TriState = TriState.UNKNOWN
    customer_profile: CustomerProfile = CustomerProfile.UNKNOWN
    objection: Optional[str] = None
    name_candidate: Optional[str] = None
    schedule_candidate: Optional[str] = None
    llm_trace: Optional[LLMTrace] = None


@dataclass
class ResponsePlan:
    action: str
    message: str
    stage: Stage
    pending_step: Optional[str] = None
    pending_question: Optional[str] = None
    trigger_handoff: bool = False

