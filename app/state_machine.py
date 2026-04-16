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

        if state.stage == Stage.HANDED_OFF:
            return self._post_handoff_plan()

        if signals.explicit_search_change and (signals.city or signals.zone):
            self._reset_search_context(state)

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
            return self._plan(
                action="greeting",
                message="Puedo ayudarte a ubicar una oportunidad en Tijuana o Ciudad de México. ¿Qué ciudad o zona te interesa?",
                stage=Stage.DISCOVERY,
                pending_step="discover_location",
                pending_question="¿Qué ciudad o zona te interesa?",
            )

        if state.stage in {Stage.DISCOVERY, Stage.CATALOG, Stage.NO_MATCH, Stage.ALTERNATIVE_DISCOVERY}:
            return self._plan(
                action="ask_location",
                message="Dime si buscas en Tijuana o Ciudad de México, o si ya traes una zona específica.",
                stage=Stage.DISCOVERY,
                pending_step="discover_location",
                pending_question="¿Qué ciudad o zona te interesa?",
            )

        if state.stage == Stage.PROPERTY_ACTIVE:
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
                message="Si esta opción te interesa, revisamos rápido si hace fit contigo.",
                stage=Stage.PROPERTY_ACTIVE,
                pending_step="confirm_property_interest",
                pending_question="¿Te interesa esta opción?",
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
            pending_question="¿Qué ciudad o zona te interesa?",
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
            if signals.mentions_property_interest or signals.requested_advisor:
                return self._ask_cash_plan(state, include_property_context=True)
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
                alternatives = self.catalog_store.alternatives_for(city, zone)
                alternatives_text = ", ".join(alternatives)
                return self._plan(
                    action="show_no_match",
                    message=(
                        f"En {zone} ahorita no tenemos inventario. "
                        f"Sí puedo enseñarte alternativas cercanas en {alternatives_text}. "
                        "Si quieres, dime cuál te interesa."
                    ),
                    stage=Stage.NO_MATCH,
                    pending_step="alternative_search",
                    pending_question="¿Qué alternativa quieres revisar?",
                )
            matches = self.catalog_store.search(city=city, zone=zone)
            state.last_catalog_property_ids = [item.id for item in matches]
            self._activate_property(state, matches[0].id)
            if signals.mentions_property_interest:
                return self._ask_cash_plan(state, include_property_context=True)
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
            lines = self.catalog_store.short_catalog_lines(matches[:4])
            lines_text = " | ".join(lines)
            return self._plan(
                action="show_city_catalog",
                message=(
                    f"Claro, te muestro lo que tenemos disponible en {city}: {lines_text}. "
                    "Si ya traes una zona en mente, dímela y te ubico la opción más cercana."
                ),
                stage=Stage.CATALOG,
                pending_step="choose_property",
                pending_question="¿Qué zona te interesa?",
            )
        return None

    def _show_property_plan(self, state: ConversationState) -> ResponsePlan:
        property_item = self.catalog_store.find_by_id(state.selected_property_id)
        summary = self.catalog_store.summarize_property(property_item)
        return self._plan(
            action="show_property",
            message=(
                f"Tengo activa esta opción: {summary} "
                "Si te interesa, revisamos rápido si hace fit contigo."
            ),
            stage=Stage.PROPERTY_ACTIVE,
            pending_step="confirm_property_interest",
            pending_question="¿Te interesa esta opción?",
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
        lead_in = ""
        if include_property_context and state.selected_property_summary:
            lead_in = f"Tengo activa esta opción: {state.selected_property_summary} "
        return self._plan(
            action="ask_cash",
            message=f"{lead_in}Estas oportunidades se manejan con recursos propios. ¿Es tu caso?".strip(),
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
            message="Solo para confirmar: este tipo de operaciones no son de entrega inmediata, hay un proceso. ¿Eso te funciona?",
            stage=Stage.QUALIFICATION_TIMELINE,
            pending_step="ask_timeline",
            pending_question="¿Te funciona que no sea entrega inmediata?",
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
                "Y para seguir bien alineados: aquí se adquieren derechos sobre una propiedad en remate, "
                "no es una compra tradicional con escrituración inmediata. ¿Lo tienes claro?"
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
                message="Perfecto. Para pasarte con un asesor, ¿me compartes tu nombre?",
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
            message="Para pasarte con el asesor necesito tu nombre.",
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
                "Aquí no hay entrega inmediata y el proceso puede extenderse a mediano o largo plazo. "
                "No manejamos tiempos exactos como compromiso comercial."
            ),
            "financing": (
                "Estas oportunidades se manejan solo con recursos propios. "
                "No aplica crédito hipotecario, Infonavit ni Fovissste."
            ),
            "how_it_works": (
                "Claro. Aquí no compras una casa lista para habitar; adquieres derechos sobre una propiedad "
                "en remate con proceso de regularización."
            ),
            "first_time": (
                "Sin problema. Lo importante es ubicar una opción que te interese y luego validar si el modelo "
                "hace fit contigo."
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
            "discover_location": "¿Qué ciudad o zona te interesa?",
            "choose_property": "¿Qué zona te interesa?",
            "alternative_search": "¿Qué alternativa quieres revisar?",
            "confirm_property_interest": "¿Te interesa esta opción?",
            "ask_cash": "¿Cuentas con recursos propios para invertir?",
            "ask_timeline": "¿Te funciona que no sea entrega inmediata?",
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
