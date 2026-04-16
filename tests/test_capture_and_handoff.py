from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.state_schema import Stage
from tests.test_support import TestHarness


ROOT = Path(__file__).resolve().parents[1]


class CaptureAndHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = TestHarness(ROOT)

    def tearDown(self) -> None:
        self.harness.close()

    def _qualify_until_name(self) -> None:
        self.harness.run(
            [
                "hola",
                "me interesa el de zona rio",
                "si tengo recursos propios",
                "si me funciona",
                "entiendo que es remate y quiero que me contacte un asesor",
            ]
        )

    def test_name_and_schedule_separate(self) -> None:
        self._qualify_until_name()
        result_name = self.harness.send("Omar")
        self.assertEqual(result_name.state.stage, Stage.PENDING_SCHEDULE)
        result_schedule = self.harness.send("4pm")
        self.assertEqual(result_schedule.state.stage, Stage.HANDED_OFF)
        self.assertEqual(result_schedule.state.name, "Omar")
        self.assertEqual(result_schedule.state.appointment_preference.lower(), "4pm")

    def test_name_and_schedule_combined(self) -> None:
        self._qualify_until_name()
        result = self.harness.send("Omar, está bien si le llaman a las 4pm")
        self.assertEqual(result.state.stage, Stage.HANDED_OFF)
        self.assertEqual(result.state.name, "Omar")
        self.assertEqual(result.state.appointment_preference.lower(), "4pm")

    def test_handoff_writes_compact_notification(self) -> None:
        self._qualify_until_name()
        self.harness.send("Omar, está bien si le llaman a las 4pm")
        payload = json.loads(self.harness.closer_log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        self.assertEqual(payload["name"], "Omar")
        self.assertEqual(payload["phone_number"], self.harness.phone)
        self.assertIn("Lead calificado", payload["ready_reason"])
