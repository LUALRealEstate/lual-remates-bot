from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

from app.catalog_store import CatalogStore, normalize_text
from app.config import Settings
from app.guardrails import Guardrails
from app.llm_client import OpenAIClientError, OpenAIResponsesClient
from app.state_schema import ConversationState, CustomerProfile, Stage, TriState, TurnSignals


PROPERTY_ID_RE = re.compile(r"\b([A-Z]{2}-[A-Z]{2}-\d{2})\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b(\d{1,2}(?::\d{2})?\s?(?:am|pm))\b", re.IGNORECASE)


class TurnUnderstanding:
    def __init__(
        self,
        *,
        settings: Settings,
        catalog_store: CatalogStore,
        llm_client: OpenAIResponsesClient | None = None,
    ) -> None:
        self.settings = settings
        self.catalog_store = catalog_store
        self.llm_client = llm_client
        self.prompt_path = self.settings.project_root / "config" / "openai_turn_understanding_prompt.txt"

    def analyze(self, text: str, state: ConversationState) -> TurnSignals:
        normalized = normalize_text(text)
        signals = TurnSignals(raw_text=text, normalized_text=normalized)

        self._detect_greeting(signals)
        self._detect_catalog_intent(signals)
        self._detect_search_change(signals)
        self._detect_city_and_zone(signals)
        self._detect_property_reference(signals)
        self._detect_affirmations(signals)
        self._detect_requested_advisor(signals)
        self._detect_profile(signals)
        self._detect_objection(signals)
        self._detect_qualification_signals(signals, state)
        self._detect_contact_fields(signals, state)

        if self._should_call_llm(signals):
            self._merge_llm_support(signals)

        if signals.zone and not signals.city:
            signals.city = self.catalog_store.infer_city_from_zone(signals.zone)

        if (
            signals.zone
            and signals.mentions_property_interest
            and not signals.selected_property_id
        ):
            matches = self.catalog_store.search(city=signals.city, zone=signals.zone)
            if len(matches) == 1:
                signals.selected_property_id = matches[0].id

        return signals

    def _detect_greeting(self, signals: TurnSignals) -> None:
        tokens = {"hola", "buenas", "buen día", "buen dia", "que tal", "qué tal"}
        signals.greeting = any(token in signals.normalized_text for token in tokens)

    def _detect_catalog_intent(self, signals: TurnSignals) -> None:
        catalog_phrases = [
            "catalogo",
            "catálogo",
            "ver propiedades",
            "quiero ver propiedades",
            "me interesa una propiedad",
            "quiero informes",
            "vengo de anuncio",
            "me interesa",
        ]
        signals.wants_catalog = any(phrase in signals.normalized_text for phrase in catalog_phrases)
        signals.wants_info = any(
            phrase in signals.normalized_text
            for phrase in ["como funciona", "cómo funciona", "informes", "no entiendo bien"]
        )
        signals.asks_next_step = any(
            phrase in signals.normalized_text
            for phrase in ["que sigue", "qué sigue", "que pasa despues", "qué pasa después"]
        )
        signals.mentions_property_interest = any(
            phrase in signals.normalized_text
            for phrase in ["me interesa", "quiero esa", "quiero el de", "si me interesa", "sí me interesa"]
        )

    def _detect_search_change(self, signals: TurnSignals) -> None:
        phrases = [
            "cambiar de zona",
            "cambiar de ciudad",
            "mejor en",
            "mejor busca",
            "otra zona",
            "otra opcion",
            "otra opción",
            "tambien en",
            "también en",
            "ahora en",
        ]
        signals.explicit_search_change = any(phrase in signals.normalized_text for phrase in phrases)

    def _detect_city_and_zone(self, signals: TurnSignals) -> None:
        for alias, city in sorted(
            self.catalog_store.CITY_ALIASES.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if alias in signals.normalized_text:
                signals.city = city
                break

        for alias, zone in sorted(
            self.catalog_store.ZONE_ALIASES.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if alias in signals.normalized_text:
                signals.zone = zone
                break

    def _detect_property_reference(self, signals: TurnSignals) -> None:
        match = PROPERTY_ID_RE.search(signals.raw_text.upper())
        if match:
            signals.selected_property_id = match.group(1).upper()

    def _detect_affirmations(self, signals: TurnSignals) -> None:
        affirmatives = {"si", "sí", "claro", "va", "ok", "sale", "si por favor", "sí por favor"}
        negatives = {"no", "para nada", "no gracias", "no me funciona"}
        normalized = signals.normalized_text
        signals.affirmative = normalized in affirmatives or normalized.startswith("si ")
        signals.negative = normalized in negatives or normalized.startswith("no ")

    def _detect_requested_advisor(self, signals: TurnSignals) -> None:
        advisor_phrases = [
            "asesor",
            "que me contacte un asesor",
            "que me llame un asesor",
            "quiero hablar con un asesor",
            "quiero que me contacte",
        ]
        signals.requested_advisor = any(phrase in signals.normalized_text for phrase in advisor_phrases)

    def _detect_profile(self, signals: TurnSignals) -> None:
        patrimonial_markers = ["vivir", "habitar", "mi familia", "patrimonio", "para mi"]
        inversion_markers = ["invertir", "inversion", "inversión", "plusvalia", "plusvalía", "rentar", "revender"]
        if any(token in signals.normalized_text for token in patrimonial_markers):
            signals.customer_profile = CustomerProfile.PATRIMONIAL
        elif any(token in signals.normalized_text for token in inversion_markers):
            signals.customer_profile = CustomerProfile.INVERSIONISTA

    def _detect_objection(self, signals: TurnSignals) -> None:
        objection_map = {
            "timeline": [
                "cuanto tiempo",
                "cuánto tiempo",
                "cuanto tarda",
                "cuánto tarda",
                "cuando me la entregan",
                "cuándo me la entregan",
                "entrega",
            ],
            "financing": ["acepta credito", "acepta crédito", "acepta infonavit", "acepta fovissste"],
            "how_it_works": [
                "como funciona",
                "cómo funciona",
                "como es el proceso",
                "cómo es el proceso",
                "cual es el proceso",
                "cuál es el proceso",
                "explicame el proceso",
                "explícame el proceso",
                "proceso",
                "no entiendo bien",
                "no entiendo",
            ],
            "first_time": ["es mi primera vez"],
            "legality": ["es legal", "eso es legal", "fraude"],
            "safety": ["es seguro", "seguro?"],
            "next_step": ["que sigue", "qué sigue", "que pasa despues", "qué pasa después"],
        }
        for objection, patterns in objection_map.items():
            if any(pattern in signals.normalized_text for pattern in patterns):
                signals.objection = objection
                break

    def _detect_qualification_signals(self, signals: TurnSignals, state: ConversationState) -> None:
        normalized = signals.normalized_text
        cash_yes_markers = ["contado", "recursos propios", "transferencia", "cheque", "capital liquido", "capital líquido"]
        cash_no_markers = ["infonavit", "fovissste", "credito hipotecario", "crédito hipotecario", "financiamiento", "credito bancario"]
        timeline_yes_markers = ["puedo esperar", "no me urge", "entiendo el proceso", "me funciona", "si me funciona", "sí me funciona"]
        timeline_no_markers = ["me urge", "la necesito ya", "entrega inmediata", "mudarme pronto", "mudanza pronta", "quiero algo listo"]
        product_yes_markers = ["entiendo que es remate", "entiendo que es cesion de derechos", "entiendo que hay proceso", "entiendo el modelo"]
        product_no_markers = ["quiero compra normal", "quiero algo tradicional", "no quiero litigio", "no quiero esperar escrituras"]

        if any(marker in normalized for marker in cash_yes_markers):
            signals.cash_signal = TriState.TRUE
        elif any(marker in normalized for marker in cash_no_markers) and any(
            marker in normalized for marker in ["seria con", "sería con", "dependo de", "quiero usar", "sería infonavit", "tengo"]
        ):
            signals.cash_signal = TriState.FALSE

        if any(marker in normalized for marker in timeline_yes_markers):
            signals.timeline_signal = TriState.TRUE
        elif any(marker in normalized for marker in timeline_no_markers):
            signals.timeline_signal = TriState.FALSE

        if any(marker in normalized for marker in product_yes_markers):
            signals.product_signal = TriState.TRUE
        elif any(marker in normalized for marker in product_no_markers):
            signals.product_signal = TriState.FALSE

        if state.stage == Stage.QUALIFICATION_CASH and signals.cash_signal == TriState.UNKNOWN:
            if signals.affirmative:
                signals.cash_signal = TriState.TRUE
            elif signals.negative:
                signals.cash_signal = TriState.FALSE

        if state.stage == Stage.OBJECTION_HANDLING and state.pending_step == "ask_cash":
            if signals.cash_signal == TriState.UNKNOWN and signals.affirmative:
                signals.cash_signal = TriState.TRUE
            elif signals.cash_signal == TriState.UNKNOWN and signals.negative:
                signals.cash_signal = TriState.FALSE

        if state.stage == Stage.QUALIFICATION_TIMELINE and signals.timeline_signal == TriState.UNKNOWN:
            if signals.affirmative:
                signals.timeline_signal = TriState.TRUE
            elif signals.negative:
                signals.timeline_signal = TriState.FALSE

        if state.stage == Stage.OBJECTION_HANDLING and state.pending_step == "ask_timeline":
            if signals.timeline_signal == TriState.UNKNOWN and signals.affirmative:
                signals.timeline_signal = TriState.TRUE
            elif signals.timeline_signal == TriState.UNKNOWN and signals.negative:
                signals.timeline_signal = TriState.FALSE

        if (
            state.stage == Stage.QUALIFICATION_PRODUCT_UNDERSTANDING
            and signals.product_signal == TriState.UNKNOWN
        ):
            if signals.affirmative:
                signals.product_signal = TriState.TRUE
            elif signals.negative:
                signals.product_signal = TriState.FALSE

        if state.stage == Stage.OBJECTION_HANDLING and state.pending_step == "ask_product":
            if signals.product_signal == TriState.UNKNOWN and signals.affirmative:
                signals.product_signal = TriState.TRUE
            elif signals.product_signal == TriState.UNKNOWN and signals.negative:
                signals.product_signal = TriState.FALSE

    def _detect_contact_fields(self, signals: TurnSignals, state: ConversationState) -> None:
        schedule_candidate = self._extract_schedule(signals.raw_text)
        if schedule_candidate and Guardrails.can_capture_schedule(schedule_candidate):
            signals.schedule_candidate = schedule_candidate

        if state.stage in {Stage.PENDING_NAME, Stage.CONTACT_CAPTURE} or state.pending_step == "ask_name":
            name_candidate = self._extract_name(signals.raw_text)
            if name_candidate and Guardrails.can_capture_name(name_candidate):
                signals.name_candidate = name_candidate
        elif state.stage == Stage.PENDING_SCHEDULE and not state.name:
            name_candidate = self._extract_name(signals.raw_text)
            if name_candidate and Guardrails.can_capture_name(name_candidate):
                signals.name_candidate = name_candidate

    def _extract_name(self, raw_text: str) -> Optional[str]:
        normalized = normalize_text(raw_text)
        patterns = [
            r"(?:me llamo|soy)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ ]{2,40})",
            r"^([A-Za-zÁÉÍÓÚÑáéíóúñ]{2,20})(?:,|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if not match:
                continue
            candidate = match.group(1).strip(" ,.")
            if normalize_text(candidate) in {"esta bien si le llaman", "está bien si le llaman"}:
                continue
            return " ".join(part.capitalize() for part in candidate.split())

        if "," in raw_text:
            left = raw_text.split(",", 1)[0].strip(" ,.")
            if left and left.replace(" ", "").isalpha() and len(left) <= 30:
                return " ".join(part.capitalize() for part in left.split())

        if normalized.replace(" ", "").isalpha() and 2 <= len(normalized) <= 24:
            return " ".join(part.capitalize() for part in raw_text.strip().split())
        return None

    def _extract_schedule(self, raw_text: str) -> Optional[str]:
        if TIME_RE.search(raw_text):
            return TIME_RE.search(raw_text).group(1).strip()

        lowered = normalize_text(raw_text)
        phrases = [
            "mañana por la tarde",
            "manana por la tarde",
            "mañana por la mañana",
            "manana por la manana",
            "hoy por la tarde",
            "hoy por la mañana",
            "hoy por la noche",
        ]
        for phrase in phrases:
            if phrase in lowered:
                return phrase.replace("manana", "mañana").replace("manana", "mañana")
        return None

    def _should_call_llm(self, signals: TurnSignals) -> bool:
        if not self.settings.openai_turn_understanding_enabled:
            return False
        if not self.llm_client or not self.llm_client.is_enabled():
            return False
        if len(signals.normalized_text) < 12:
            return False
        deterministic_hits = [
            signals.wants_catalog,
            signals.wants_info,
            signals.asks_next_step,
            signals.mentions_property_interest,
            signals.city,
            signals.zone,
            signals.selected_property_id,
            signals.objection,
            signals.name_candidate,
            signals.schedule_candidate,
            signals.customer_profile != CustomerProfile.UNKNOWN,
            signals.cash_signal != TriState.UNKNOWN,
            signals.timeline_signal != TriState.UNKNOWN,
            signals.product_signal != TriState.UNKNOWN,
        ]
        return not any(deterministic_hits)

    def _merge_llm_support(self, signals: TurnSignals) -> None:
        instructions = Path(self.prompt_path).read_text(encoding="utf-8")
        try:
            result = self.llm_client.complete(
                prompt_name="turn_understanding",
                instructions=instructions,
                input_text=signals.raw_text,
            )
        except OpenAIClientError:
            return

        signals.llm_trace = result.trace
        try:
            parsed = json.loads(result.text.strip().strip("`"))
        except json.JSONDecodeError:
            return

        if not signals.city and parsed.get("city") in {"Tijuana", "Ciudad de México"}:
            signals.city = parsed["city"]
        if not signals.zone and isinstance(parsed.get("zone"), str):
            signals.zone = parsed["zone"]
        if not signals.objection and parsed.get("objection"):
            signals.objection = str(parsed["objection"])
        if signals.customer_profile == CustomerProfile.UNKNOWN and parsed.get("customer_profile"):
            profile = str(parsed["customer_profile"])
            if profile in {CustomerProfile.PATRIMONIAL.value, CustomerProfile.INVERSIONISTA.value}:
                signals.customer_profile = CustomerProfile(profile)
        for field_name, current_value in (
            ("cash_signal", signals.cash_signal),
            ("timeline_signal", signals.timeline_signal),
            ("product_signal", signals.product_signal),
        ):
            if current_value != TriState.UNKNOWN:
                continue
            llm_value = parsed.get(field_name)
            if llm_value in {TriState.TRUE.value, TriState.FALSE.value}:
                setattr(signals, field_name, TriState(llm_value))
        if not signals.requested_advisor and parsed.get("requested_advisor") is True:
            signals.requested_advisor = True
        if not signals.mentions_property_interest and parsed.get("mentions_property_interest") is True:
            signals.mentions_property_interest = True
