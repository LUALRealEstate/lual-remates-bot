from __future__ import annotations

from typing import Optional

from app.catalog_store import CatalogStore
from app.guardrails import Guardrails
from app.state_schema import (
    ConversationState,
    CustomerProfile,
    ResponsePlan,
    Stage,
    TriState,
    TurnSignals,
)


class StateMachine:
    def __init__(self, catalog_store: CatalogStore) -> None:
        self.catalog_store = catalog_store

    def advance(self, state: ConversationState, signals: TurnSignals) -> ResponsePlan:
        if signals.llm_trace:
            state.add_llm_trace(signals.llm_trace)
        if signals.customer_profile != CustomerProfile.UNKNOWN:
            state.customer_profile = signals.customer_profile
        if signals.requested_advisor and not state.handoff_done:
            state.advisor_request_pending = True

        catalog_intent_without_location = (
            (signals.wants_catalog or signals.wants_info)
            and not signals.city
            and not signals.zone
            and not signals.selected_property_id
            and not state.property_active
        )

        if state.stage == Stage.HANDED_OFF:
            return self._post_handoff_plan()

        if signals.explicit_search_change and (signals.city or signals.zone):
            self._reset_search_context(state)

        if catalog_intent_without_location:
            return self._catalog_discovery_plan()

        if state.stage == Stage.OBJECTION_HANDLING and not signals.objection:
            state.stage = self._stage_from_pending_step(state.pending_step) or state.stage
            state.active_objection = None

        if signals.objection and state.stage != Stage.HANDED_OFF:
            return self._objection_plan(state, signals)

        if state.stage == Stage.CLOSED_OUT and not (signals.city or signals.zone or signals.wants_catalog):
            return self._plan(
                action="closed_out",
                message="Si más adelante quieres revisar otra oportunidad de remate con calma, aquí te apoyo.",
                stage=Stage.CLOSED_OUT,
            )

        location_plan = self._try_location_flow(state, signals)
        if location_plan:
            return location_plan

        if state.stage == Stage.OPENING:
            if signals.wants_catalog or signals.wants_info or signals.requested_advisor:
                return self._catalog_discovery_plan()
            return self._plan(
                action="greeting",
                message="",
                stage=Stage.DISCOVERY,
                pending_step="discover_location",
                pending_question="¿En qué puedo ayudarte?",
            )

        if state.stage in {Stage.DISCOVERY, Stage.CATALOG, Stage.NO_MATCH, Stage.ALTERNATIVE_DISCOVERY}:
            return self._catalog_discovery_plan()

        if state.stage == Stage.PROPERTY_ACTIVE:
            if signals.cash_signal != TriState.UNKNOWN:
                state.stage = Stage.QUALIFICATION_CASH
                return self._handle_cash_stage(state, signals)
            if signals.affirmative or signals.mentions_property_interest or signals.requested_advisor:
                return self._ask_cash_plan(state)
            if signals.city or signals.zone:
                return self._plan(
                    action="property_focus_guardrail",
                    message="Ya tengo activa la opción que viste. Si quieres cambiar la búsqueda, dime la nueva zona o ciudad y lo hacemos.",
                    stage=Stage.PROPERTY_ACTIVE,
                    pending_step="confirm_property_interest",
                    pending_question="¿Te interesa esta opción para revisar si hace fit contigo?",
                )
            return self._plan(
                action="reconfirm_property_interest",
                message="¿Te gustaría saber más sobre esta propiedad?",
                stage=Stage.PROPERTY_ACTIVE,
                pending_step="confirm_property_interest",
                pending_question="¿Te gustaría saber más sobre esta propiedad?",
            )

        if state.stage == Stage.QUALIFICATION_CASH:
            return self._handle_cash_stage(state, signals)
        if state.stage == Stage.QUALIFICATION_TIMELINE:
            return self._handle_timeline_stage(state, signals)
        if state.stage == Stage.QUALIFICATION_PRODUCT_UNDERSTANDING:
            return self._handle_product_stage(state, signals)
        if state.stage == Stage.CONTACT_CAPTURE:
            return self._handle_contact_capture(state, signals)
        if state.stage == Stage.PENDING_NAME:
            return self._handle_pending_name(state, signals)
        if state.stage == Stage.PENDING_SCHEDULE:
            return self._handle_pending_schedule(state, signals)

        return self._plan(
            action="fallback",
            message="Cuéntame la ciudad o zona que traes en mente y lo retomamos.",
            stage=Stage.DISCOVERY,
            pending_step="discover_location",
            pending_question="¿En qué ciudad estás interesado?",
        )

    def _try_location_flow(
        self,
        state: ConversationState,
        signals: TurnSignals,
    ) -> Optional[ResponsePlan]:
        if not (signals.city or signals.zone or signals.selected_property_id):
            return None

        if state.property_active and not signals.explicit_search_change and not signals.selected_property_id:
            return None

        if signals.selected_property_id:
            property_item = self.catalog_store.find_by_id(signals.selected_property_id)
            if not property_item:
                return None
            state.city_interest = property_item.ciudad
            state.zone_interest = property_item.zona
            self._activate_property(state, property_item.id)
            return self._show_property_plan(state)

        city = signals.city
        zone = signals.zone
        if zone and not city:
            city = self.catalog_store.infer_city_from_zone(zone)

        if zone:
            state.city_interest = city
            state.zone_interest = zone
            if not city or not self.catalog_store.zone_has_inventory(city, zone):
                state.property_active = False
                state.selected_property_id = None
                state.selected_property_summary = None
                state.no_match_context = True
                state.alternative_catalog_context = True
                return self._plan(
                    action="show_no_match",
                    message=self.catalog_store.no_inventory_pitch(city, zone),
                    stage=Stage.NO_MATCH,
                    pending_step="alternative_search",
                    pending_question="¿Qué alternativa quieres revisar?",
                )
            matches = self.catalog_store.search(city=city, zone=zone)
            state.last_catalog_property_ids = [item.id for item in matches]
            self._activate_property(state, matches[0].id)
            return self._show_property_plan(state)

        if city:
            state.city_interest = city
            state.zone_interest = None
            matches = self.catalog_store.search(city=city)
            state.no_match_context = False
            state.alternative_catalog_context = False
            state.property_active = False
            state.selected_property_id = None
            state.selected_property_summary = None
            state.last_catalog_property_ids = [item.id for item in matches]
            return self._plan(
                action="show_city_catalog",
                message=self.catalog_store.city_catalog_pitch(city),
                stage=Stage.CATALOG,
                pending_step="choose_property",
                pending_question="¿Qué zona te interesa?",
            )
        return None

    def _catalog_discovery_plan(self) -> ResponsePlan:
        return self._plan(
            action="greeting_catalog",
            message="Claro, con gusto te muestro lo que hay disponible. ¿En qué ciudad estás interesado? Tenemos opciones en Tijuana y CDMX.",
            stage=Stage.DISCOVERY,
            pending_step="discover_location",
            pending_question="¿En qué ciudad estás interesado?",
        )

    def _show_property_plan(self, state: ConversationState) -> ResponsePlan:
        property_item = self.catalog_store.find_by_id(state.selected_property_id)
        summary = self.catalog_store.selected_property_pitch(property_item)
        return self._plan(
            action="show_property",
            message=summary,
            stage=Stage.PROPERTY_ACTIVE,
            pending_step="confirm_property_interest",
            pending_question="¿Te gustaría saber más sobre esta propiedad?",
        )

    def _activate_property(self, state: ConversationState, property_id: str) -> None:
        property_item = self.catalog_store.find_by_id(property_id)
        state.selected_property_id = property_item.id
        state.selected_property_summary = self.catalog_store.summarize_property(property_item)
        state.property_active = True
        state.no_match_context = False
        state.alternative_catalog_context = False

    def _ask_cash_plan(
        self,
        state: ConversationState,
        *,
        include_property_context: bool = False,
    ) -> ResponsePlan:
        state.stage = Stage.QUALIFICATION_CASH
        return self._plan(
            action="ask_cash",
            message="Estas oportunidades se manejan con recursos propios. ¿Es tu caso?",
            stage=Stage.QUALIFICATION_CASH,
            pending_step="ask_cash",
            pending_question="¿Cuentas con recursos propios para invertir?",
        )

    def _handle_cash_stage(self, state: ConversationState, signals: TurnSignals) -> ResponsePlan:
        if state.has_cash == TriState.TRUE:
            return self._ask_timeline_plan()

        if signals.cash_signal == TriState.TRUE:
            state.has_cash = TriState.TRUE
            return self._ask_timeline_plan()

        if signals.cash_signal == TriState.FALSE:
            state.has_cash = TriState.FALSE
            state.disqualification_reason = "cash"
            return self._plan(
                action="disqualify_cash",
                message=(
                    "Por cómo se manejan estas oportunidades, aquí sí se requiere capital propio "
                    "y no aplica crédito, Infonavit ni Fovissste. Si más adelante cuentas con "
                    "recursos de contado, con gusto lo retomamos."
                ),
                stage=Stage.CLOSED_OUT,
            )

        return self._plan(
            action="ask_cash",
            message="Estas oportunidades se manejan con recursos propios. ¿Es tu caso?",
            stage=Stage.QUALIFICATION_CASH,
            pending_step="ask_cash",
            pending_question="¿Cuentas con recursos propios para invertir?",
        )

    def _ask_timeline_plan(self) -> ResponsePlan:
        return self._plan(
            action="ask_timeline",
            message="Genial. Solo para que tengas el panorama completo: este tipo de propiedades tienen un proceso que toma tiempo, no es entrega inmediata. ¿Ese tipo de proceso se alinea con lo que estás buscando?",
            stage=Stage.QUALIFICATION_TIMELINE,
            pending_step="ask_timeline",
            pending_question="¿Ese tipo de proceso se alinea con lo que estás buscando?",
        )

    def _handle_timeline_stage(self, state: ConversationState, signals: TurnSignals) -> ResponsePlan:
        if state.accepts_timeline == TriState.TRUE:
            return self._ask_product_plan()

        if signals.timeline_signal == TriState.TRUE:
            state.accepts_timeline = TriState.TRUE
            return self._ask_product_plan()

        if signals.timeline_signal == TriState.FALSE:
            state.accepts_timeline = TriState.FALSE
            state.disqualification_reason = "timeline"
            return self._plan(
                action="disqualify_timeline",
                message=(
                    "Prefiero ser transparente: como no es entrega inmediata, hoy no sería la opción correcta "
                    "si necesitas algo rápido. Si después quieres revisar una oportunidad patrimonial con proceso, aquí te apoyo."
                ),
                stage=Stage.CLOSED_OUT,
            )

        return self._ask_timeline_plan()

    def _ask_product_plan(self) -> ResponsePlan:
        return self._plan(
            action="ask_product_understanding",
            message=(
                "Perfecto. Aquí no se trata de una compra tradicional; se adquieren derechos sobre una propiedad en remate y después sigue un proceso de regularización. ¿Lo tienes claro?"
            ),
            stage=Stage.QUALIFICATION_PRODUCT_UNDERSTANDING,
            pending_step="ask_product",
            pending_question="¿Tienes claro que esto es un remate con proceso y no una compra tradicional?",
        )

    def _handle_product_stage(self, state: ConversationState, signals: TurnSignals) -> ResponsePlan:
        if signals.product_signal == TriState.TRUE:
            state.understands_product = TriState.TRUE
            return self._post_qualification_plan(state)

        if signals.product_signal == TriState.FALSE:
            state.understands_product = TriState.FALSE
            state.disqualification_reason = "product_understanding"
            return self._plan(
                action="disqualify_product",
                message=(
                    "Gracias por decírmelo. Para avanzar aquí sí es importante estar cómodo con el modelo de remate "
                    "y el proceso de regularización. Si quieres, más adelante lo revisamos con calma."
                ),
                stage=Stage.CLOSED_OUT,
            )

        if state.understands_product == TriState.TRUE:
            return self._post_qualification_plan(state)

        return self._ask_product_plan()

    def _post_qualification_plan(self, state: ConversationState) -> ResponsePlan:
        if state.advisor_request_pending:
            state.advisor_offer_accepted = True
            return self._plan(
                action="ask_name",
                message="Perfecto. ¿Me compartes tu nombre?",
                stage=Stage.PENDING_NAME,
                pending_step="ask_name",
                pending_question="¿Me compartes tu nombre?",
            )

        if state.advisor_offer_accepted:
            return self._plan(
                action="ask_name",
                message="Perfecto. ¿Me compartes tu nombre?",
                stage=Stage.PENDING_NAME,
                pending_step="ask_name",
                pending_question="¿Me compartes tu nombre?",
            )

        return self._plan(
            action="offer_advisor",
            message="Perfecto. Si quieres, te conecto con un asesor para revisar la opción a detalle. ¿Te parece bien?",
            stage=Stage.CONTACT_CAPTURE,
            pending_step="offer_advisor",
            pending_question="¿Te conecto con un asesor?",
        )

    def _handle_contact_capture(self, state: ConversationState, signals: TurnSignals) -> ResponsePlan:
        if not state.advisor_offer_accepted:
            if signals.name_candidate:
                state.advisor_offer_accepted = True
                state.name = signals.name_candidate
                if signals.schedule_candidate:
                    state.appointment_preference = signals.schedule_candidate
                    return self._handoff_plan()
                return self._plan(
                    action="ask_schedule",
                    message="Gracias. ¿Qué horario te funciona para la llamada?",
                    stage=Stage.PENDING_SCHEDULE,
                    pending_step="ask_schedule",
                    pending_question="¿Qué horario te funciona para la llamada?",
                )
            if signals.schedule_candidate:
                state.advisor_offer_accepted = True
                return self._plan(
                    action="ask_name_after_schedule_only",
                    message="Perfecto. ¿Me compartes tu nombre?",
                    stage=Stage.PENDING_NAME,
                    pending_step="ask_name",
                    pending_question="¿Me compartes tu nombre?",
                )
            if signals.affirmative or signals.requested_advisor:
                state.advisor_offer_accepted = True
                return self._plan(
                    action="ask_name",
                    message="Perfecto. ¿Me compartes tu nombre?",
                    stage=Stage.PENDING_NAME,
                    pending_step="ask_name",
                    pending_question="¿Me compartes tu nombre?",
                )
            if signals.negative:
                return self._plan(
                    action="advisor_declined",
                    message="Sin problema. Si más adelante quieres que te conecte con un asesor, lo dejamos listo.",
                    stage=Stage.CLOSED_OUT,
                )
            return self._plan(
                action="offer_advisor",
                message="Si quieres, te conecto con un asesor para revisar la opción a detalle. ¿Te parece bien?",
                stage=Stage.CONTACT_CAPTURE,
                pending_step="offer_advisor",
                pending_question="¿Te conecto con un asesor?",
            )

        return self._plan(
            action="ask_name",
            message="Perfecto. ¿Me compartes tu nombre?",
            stage=Stage.PENDING_NAME,
            pending_step="ask_name",
            pending_question="¿Me compartes tu nombre?",
        )

    def _handle_pending_name(self, state: ConversationState, signals: TurnSignals) -> ResponsePlan:
        if signals.name_candidate:
            state.name = signals.name_candidate
            if signals.schedule_candidate:
                state.appointment_preference = signals.schedule_candidate
                return self._handoff_plan()
            return self._plan(
                action="ask_schedule",
                message="Gracias. ¿Qué horario te funciona para la llamada?",
                stage=Stage.PENDING_SCHEDULE,
                pending_step="ask_schedule",
                pending_question="¿Qué horario te funciona para la llamada?",
            )

        if signals.schedule_candidate:
            return self._plan(
                action="ask_name_after_schedule_only",
                message="Perfecto. También necesito tu nombre para pasarte con el asesor.",
                stage=Stage.PENDING_NAME,
                pending_step="ask_name",
                pending_question="¿Me compartes tu nombre?",
            )

        return self._plan(
            action="ask_name",
            message="Perfecto. ¿Me compartes tu nombre?",
            stage=Stage.PENDING_NAME,
            pending_step="ask_name",
            pending_question="¿Me compartes tu nombre?",
        )

    def _handle_pending_schedule(self, state: ConversationState, signals: TurnSignals) -> ResponsePlan:
        if signals.schedule_candidate:
            state.appointment_preference = signals.schedule_candidate
            return self._handoff_plan()

        return self._plan(
            action="ask_schedule",
            message="Compárteme un horario concreto que te funcione, por ejemplo 4pm o mañana por la tarde.",
            stage=Stage.PENDING_SCHEDULE,
            pending_step="ask_schedule",
            pending_question="¿Qué horario te funciona para la llamada?",
        )

    def _handoff_plan(self) -> ResponsePlan:
        return self._plan(
            action="handoff_complete",
            message="Listo. Ya dejé tu solicitud para que un asesor de LUAL retome contigo en el horario que indicaste.",
            stage=Stage.HANDED_OFF,
            trigger_handoff=True,
        )

    def _post_handoff_plan(self) -> ResponsePlan:
        return self._plan(
            action="post_handoff_ack",
            message="Tu solicitud ya quedó registrada con el equipo. Si quieres, mientras tanto puedo aclararte una duda breve sin reabrir el proceso.",
            stage=Stage.HANDED_OFF,
        )

    def _objection_plan(self, state: ConversationState, signals: TurnSignals) -> ResponsePlan:
        objection = signals.objection or "how_it_works"
        if objection not in state.handled_objections:
            state.handled_objections.append(objection)

        current_step = state.pending_step or self._default_pending_step_for_stage(state.stage)
        resume_question = self._question_for_step(current_step)
        state.active_objection = objection

        safe_answers = {
            "timeline": (
                "Los tiempos pueden variar según cada propiedad. El asesor te puede dar información específica sobre el tiempo estimado en una llamada."
            ),
            "financing": (
                "Estas oportunidades se manejan solo con recursos propios. "
                "No aplica crédito hipotecario, Infonavit ni Fovissste."
            ),
            "how_it_works": (
                "No es una compra tradicional. Aquí se adquieren derechos sobre una propiedad en remate "
                "y después sigue un proceso de regularización, por eso no es entrega inmediata."
            ),
            "first_time": (
                "No te preocupes, te lo explico paso a paso. Primero ubicamos una oportunidad y luego validamos si este esquema hace sentido para ti."
            ),
            "legality": (
                "Es una excelente pregunta. Lo que sí te puedo decir es que LUAL trabaja estas oportunidades "
                "con respaldo jurídico e inmobiliario y la viabilidad se revisa antes de avanzar. "
                "Si quieres, te conecto con un asesor de LUAL para revisarlo a detalle."
            ),
            "safety": (
                "Es una excelente pregunta. Lo que sí te puedo decir es que LUAL acompaña al inversionista "
                "con respaldo jurídico e inmobiliario para reducir riesgos del proceso. "
                "Si quieres, te conecto con un asesor de LUAL para revisarlo a detalle."
            ),
            "next_step": (
                "Si te interesa avanzar, te conecto con un asesor para revisar la opción a detalle y explicarte el siguiente paso."
            ),
        }
        if objection == "timeline" and current_step == "ask_timeline":
            resume_question = "¿Ese tipo de proceso se alinea con lo que estás buscando?"
        if objection == "how_it_works":
            resume_question = "¿Te funciona un esquema así?"
        message = safe_answers[objection]
        if resume_question:
            message = f"{message} {resume_question}"
        return self._plan(
            action=f"answer_{objection}_objection",
            message=message,
            stage=Stage.OBJECTION_HANDLING,
            pending_step=current_step,
            pending_question=resume_question,
        )

    def _question_for_step(self, step: Optional[str]) -> Optional[str]:
        mapping = {
            "discover_location": "¿En qué ciudad estás interesado?",
            "choose_property": "¿Qué zona te interesa?",
            "alternative_search": "¿Qué alternativa quieres revisar?",
            "confirm_property_interest": "¿Te gustaría saber más sobre esta propiedad?",
            "ask_cash": "¿Cuentas con recursos propios para invertir?",
            "ask_timeline": "¿Ese tipo de proceso se alinea con lo que estás buscando?",
            "ask_product": "¿Tienes claro que esto es un remate con proceso y no una compra tradicional?",
            "offer_advisor": "¿Te conecto con un asesor?",
            "ask_name": "¿Me compartes tu nombre?",
            "ask_schedule": "¿Qué horario te funciona para la llamada?",
        }
        return mapping.get(step)

    def _default_pending_step_for_stage(self, stage: Stage) -> Optional[str]:
        return {
            Stage.DISCOVERY: "discover_location",
            Stage.CATALOG: "choose_property",
            Stage.NO_MATCH: "alternative_search",
            Stage.ALTERNATIVE_DISCOVERY: "alternative_search",
            Stage.PROPERTY_ACTIVE: "confirm_property_interest",
            Stage.QUALIFICATION_CASH: "ask_cash",
            Stage.QUALIFICATION_TIMELINE: "ask_timeline",
            Stage.QUALIFICATION_PRODUCT_UNDERSTANDING: "ask_product",
            Stage.CONTACT_CAPTURE: "offer_advisor",
            Stage.PENDING_NAME: "ask_name",
            Stage.PENDING_SCHEDULE: "ask_schedule",
        }.get(stage)

    def _stage_from_pending_step(self, step: Optional[str]) -> Optional[Stage]:
        mapping = {
            "discover_location": Stage.DISCOVERY,
            "choose_property": Stage.CATALOG,
            "alternative_search": Stage.ALTERNATIVE_DISCOVERY,
            "confirm_property_interest": Stage.PROPERTY_ACTIVE,
            "ask_cash": Stage.QUALIFICATION_CASH,
            "ask_timeline": Stage.QUALIFICATION_TIMELINE,
            "ask_product": Stage.QUALIFICATION_PRODUCT_UNDERSTANDING,
            "offer_advisor": Stage.CONTACT_CAPTURE,
            "ask_name": Stage.PENDING_NAME,
            "ask_schedule": Stage.PENDING_SCHEDULE,
        }
        return mapping.get(step)

    def _reset_search_context(self, state: ConversationState) -> None:
        state.city_interest = None
        state.zone_interest = None
        state.selected_property_id = None
        state.selected_property_summary = None
        state.property_active = False
        state.no_match_context = False
        state.alternative_catalog_context = False
        state.last_catalog_property_ids = []
        if state.stage not in {Stage.HANDED_OFF, Stage.CLOSED_OUT}:
            state.stage = Stage.DISCOVERY

    def _plan(
        self,
        *,
        action: str,
        message: str,
        stage: Stage,
        pending_step: Optional[str] = None,
        pending_question: Optional[str] = None,
        trigger_handoff: bool = False,
    ) -> ResponsePlan:
        return ResponsePlan(
            action=action,
            message=message,
            stage=stage,
            pending_step=pending_step,
            pending_question=pending_question,
            trigger_handoff=trigger_handoff,
        )
