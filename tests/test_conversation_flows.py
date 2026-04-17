from __future__ import annotations

import unittest
from pathlib import Path

from app.state_schema import Stage
from tests.test_support import TestHarness


ROOT = Path(__file__).resolve().parents[1]


class ConversationFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = TestHarness(ROOT)

    def tearDown(self) -> None:
        self.harness.close()

    def test_greeting_and_discovery(self) -> None:
        result = self.harness.send("hola")
        self.assertEqual(result.reply_text, "¡Hola! Bienvenido a LUAL Real Estate. ¿En qué puedo ayudarte?")
        self.assertEqual(result.state.stage, Stage.DISCOVERY)

    def test_catalog_by_city(self) -> None:
        results = self.harness.run(["hola", "tijuana"])
        self.assertIn("Zona Río", results[-1].reply_text)
        self.assertIn("Playas de Tijuana", results[-1].reply_text)
        self.assertNotIn("TJ-ZR-01", results[-1].reply_text)
        self.assertEqual(results[-1].state.stage, Stage.CATALOG)

    def test_selection_by_zone_sets_property_active(self) -> None:
        results = self.harness.run(["hola", "tijuana", "zona rio"])
        state = results[-1].state
        self.assertTrue(state.property_active)
        self.assertEqual(state.selected_property_id, "TJ-ZR-01")
        self.assertEqual(state.stage, Stage.PROPERTY_ACTIVE)
        self.assertIn("Tenemos un departamento disponible en Zona Río, Tijuana.", results[-1].reply_text)
        self.assertNotIn("TJ-ZR-01", results[-1].reply_text)

    def test_no_match_then_city_alternative_stays_in_catalog(self) -> None:
        results = self.harness.run(["hola", "villafontana", "cdmx"])
        state = results[-1].state
        self.assertFalse(state.property_active)
        self.assertEqual(state.stage, Stage.CATALOG)
        self.assertIn("Ciudad de México", results[-1].reply_text)
        self.assertNotIn("recursos propios", results[-1].reply_text.lower())

    def test_no_match_then_zone_alternative_does_not_jump_to_qualification(self) -> None:
        results = self.harness.run(["hola", "villafontana", "cacho"])
        state = results[-1].state
        self.assertTrue(state.property_active)
        self.assertEqual(state.stage, Stage.PROPERTY_ACTIVE)

    def test_concrete_property_interest_shows_property_without_catalog_dump(self) -> None:
        results = self.harness.run(["hola", "me interesa el de zona rio"])
        state = results[-1].state
        self.assertEqual(state.stage, Stage.PROPERTY_ACTIVE)
        self.assertTrue(state.property_active)
        self.assertEqual(state.selected_property_id, "TJ-ZR-01")
        self.assertIn("Tenemos un departamento disponible en Zona Río, Tijuana.", results[-1].reply_text)
        self.assertNotIn("TJ-ZR-01", results[-1].reply_text)

    def test_affirmation_after_property_active_advances_to_cash(self) -> None:
        results = self.harness.run(["hola", "zona rio", "si"])
        self.assertEqual(results[-1].state.stage, Stage.QUALIFICATION_CASH)
        self.assertIn("recursos propios", results[-1].reply_text.lower())

    def test_timeline_objection_resumes_flow(self) -> None:
        results = self.harness.run(["hola", "zona rio", "si", "si", "cuanto tiempo", "si"])
        self.assertIn("mediano o largo plazo", results[-2].reply_text.lower())
        self.assertEqual(results[-1].state.stage, Stage.QUALIFICATION_PRODUCT_UNDERSTANDING)
        self.assertEqual(results[-1].state.action_history.count("answer_timeline_objection"), 1)

    def test_financing_objection_resumes_cash_without_regression(self) -> None:
        results = self.harness.run(["hola", "zona rio", "si", "acepta crédito", "si tengo recursos propios"])
        self.assertIn("no aplica crédito", results[-2].reply_text.lower())
        self.assertEqual(results[-1].state.stage, Stage.QUALIFICATION_TIMELINE)
        self.assertEqual(results[-1].state.action_history.count("answer_financing_objection"), 1)

    def test_first_time_objection_does_not_break_property_flow(self) -> None:
        results = self.harness.run(["hola", "zona rio", "es mi primera vez"])
        self.assertEqual(results[-1].state.stage, Stage.OBJECTION_HANDLING)
        self.assertIn("te lo explico paso a paso", results[-1].reply_text.lower())

    def test_fast_advisor_acceptance_skips_reconfirmation(self) -> None:
        results = self.harness.run(
            [
                "hola",
                "me interesa el de zona rio",
                "si tengo recursos propios",
                "si me funciona",
                "entiendo que es remate y quiero que me contacte un asesor",
            ]
        )
        self.assertEqual(results[-1].state.stage, Stage.PENDING_NAME)
        self.assertNotIn("te conecto con un asesor", results[-1].reply_text.lower())

    def test_process_question_answers_briefly_and_resumes_flow(self) -> None:
        results = self.harness.run(["hola", "zona rio", "como es el proceso"])
        self.assertEqual(results[-1].state.stage, Stage.OBJECTION_HANDLING)
        self.assertIn("no es una compra tradicional", results[-1].reply_text.lower())
        self.assertIn("¿te interesa esta opción?", results[-1].reply_text.lower())
        self.assertNotIn("tj-zr-01", results[-1].reply_text.lower())

    def test_full_flow_uses_natural_commercial_copy_until_handoff(self) -> None:
        results = self.harness.run(
            [
                "hola",
                "quiero ver propiedades",
                "zona rio",
                "si",
                "si",
                "si",
                "si",
                "Omar",
                "4pm",
            ]
        )
        self.assertEqual(results[0].reply_text, "¡Hola! Bienvenido a LUAL Real Estate. ¿En qué puedo ayudarte?")
        self.assertEqual(
            results[1].reply_text,
            "Claro, tenemos opciones en Tijuana y CDMX. ¿Hay alguna zona o tipo de propiedad que te interese?",
        )
        self.assertIn("Tenemos un departamento disponible en Zona Río, Tijuana.", results[2].reply_text)
        self.assertIn("recursos propios", results[3].reply_text.lower())
        self.assertIn("no son de entrega inmediata", results[4].reply_text.lower())
        self.assertIn("se adquieren derechos", results[5].reply_text.lower())
        self.assertIn("te conecto con un asesor", results[6].reply_text.lower())
        self.assertEqual(results[7].reply_text, "Gracias. ¿Qué horario te funciona para la llamada?")
        self.assertIn("ya dejé tu solicitud", results[8].reply_text.lower())

    def test_message_after_handoff_stays_closed(self) -> None:
        results = self.harness.run(
            [
                "hola",
                "me interesa el de zona rio",
                "si tengo recursos propios",
                "si me funciona",
                "entiendo que es remate y quiero que me contacte un asesor",
                "Omar, está bien si le llaman a las 4pm",
                "gracias",
            ]
        )
        self.assertEqual(results[-2].state.stage, Stage.HANDED_OFF)
        self.assertEqual(results[-1].state.stage, Stage.HANDED_OFF)
        self.assertEqual(results[-1].state.action_history.count("handoff_complete"), 1)

    def test_explicit_search_change_resets_active_property(self) -> None:
        results = self.harness.run(["hola", "zona rio", "mejor en cdmx"])
        state = results[-1].state
        self.assertFalse(state.property_active)
        self.assertEqual(state.stage, Stage.CATALOG)
        self.assertIn("Ciudad de México", results[-1].reply_text)
