from __future__ import annotations

import json
import os
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.test_support import TestHarness


ROOT = Path(__file__).resolve().parents[1]


class _CaptureHandler(BaseHTTPRequestHandler):
    received_payloads: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        self.__class__.received_payloads.append(json.loads(body))
        payload = json.dumps({"status": "ok"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class OperationalIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = TestHarness(ROOT)

    def tearDown(self) -> None:
        self.harness.close()

    def test_cli_local_still_runs(self) -> None:
        env = os.environ.copy()
        env["ENABLE_LLM_ASSIST"] = "false"
        env["OPENAI_TURN_UNDERSTANDING_ENABLED"] = "false"
        env["STATE_STORAGE_DIR"] = str(self.harness.runtime_root / "cli_state")
        env["CLOSER_CONSOLE_LOG_PATH"] = str(self.harness.runtime_root / "cli_closer.log")
        env["LIVE_API_LOG_PATH"] = str(self.harness.runtime_root / "cli_live.jsonl")
        env["WHATSAPP_DISPATCH_LOG_PATH"] = str(self.harness.runtime_root / "cli_whatsapp.log")
        completed = subprocess.run(
            ["python3", "main.py", "--phone", self.harness.phone],
            input="hola\nsalir\n",
            text=True,
            capture_output=True,
            cwd=str(ROOT),
            env=env,
            check=True,
        )
        self.assertIn("¡Hola! Bienvenido a LUAL Real Estate. ¿En qué puedo ayudarte?", completed.stdout)

    def test_adapter_receives_message_and_returns_response(self) -> None:
        result = self.harness.send_via_adapter("hola", {"source": "webhook"})
        self.assertEqual(result.phone_number, self.harness.phone)
        self.assertEqual(result.state["stage"], "discovery")
        self.assertEqual(result.reply_text, "¡Hola! Bienvenido a LUAL Real Estate. ¿En qué puedo ayudarte?")
        self.assertIsNone(result.handoff_summary)

    def test_runtime_entrypoint_message_mode_returns_json(self) -> None:
        env = os.environ.copy()
        env["ENABLE_LLM_ASSIST"] = "false"
        env["OPENAI_TURN_UNDERSTANDING_ENABLED"] = "false"
        env["STATE_STORAGE_DIR"] = str(self.harness.runtime_root / "runtime_state")
        env["CLOSER_CONSOLE_LOG_PATH"] = str(self.harness.runtime_root / "runtime_closer.log")
        env["LIVE_API_LOG_PATH"] = str(self.harness.runtime_root / "runtime_live.jsonl")
        env["WHATSAPP_DISPATCH_LOG_PATH"] = str(self.harness.runtime_root / "runtime_whatsapp.log")
        completed = subprocess.run(
            [
                "python3",
                "runtime_entrypoint.py",
                "message",
                "--phone",
                self.harness.phone,
                "--text",
                "hola",
            ],
            text=True,
            capture_output=True,
            cwd=str(ROOT),
            env=env,
            check=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["state"]["stage"], "discovery")
        self.assertEqual(payload["reply_text"], "¡Hola! Bienvenido a LUAL Real Estate. ¿En qué puedo ayudarte?")

    def test_console_handoff_generates_clean_summary(self) -> None:
        self.harness.run(
            [
                "hola",
                "me interesa el de zona rio",
                "si tengo recursos propios",
                "si me funciona",
                "entiendo que es remate y quiero que me contacte un asesor",
                "Omar, está bien si le llaman a las 4pm",
            ]
        )
        payload = json.loads(self.harness.closer_log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        self.assertEqual(payload["name"], "Omar")
        self.assertEqual(payload["phone_number"], self.harness.phone)
        self.assertEqual(payload["city"], "Tijuana")
        self.assertEqual(payload["zone"], "Zona Río")
        self.assertIn("Tijuana", payload["city_or_zone"])
        self.assertIn("TJ-ZR-01", payload["property_reference"])
        self.assertEqual(payload["has_cash"], "true")
        self.assertEqual(payload["accepts_timeline"], "true")
        self.assertEqual(payload["appointment_preference"].lower(), "4pm")

    def test_whatsapp_stub_notifier_uses_closer_config(self) -> None:
        self.harness.close()
        harness = TestHarness(
            ROOT,
            env_overrides={
                "CLOSER_NOTIFICATION_METHOD": "whatsapp",
                "CLOSER_PHONE_NUMBER": "5216161249340",
            },
        )
        self.addCleanup(harness.close)
        harness.run(
            [
                "hola",
                "me interesa el de zona rio",
                "si tengo recursos propios",
                "si me funciona",
                "entiendo que es remate y quiero que me contacte un asesor",
                "Omar, está bien si le llaman a las 4pm",
            ]
        )
        dispatch_lines = harness.whatsapp_dispatch_log_path.read_text(encoding="utf-8").strip().splitlines()
        last_dispatch = json.loads(dispatch_lines[-1])
        self.assertEqual(last_dispatch["payload"]["to"], "5216161249340")
        self.assertEqual(last_dispatch["result"]["channel"], "whatsapp_stub")
        self.assertEqual(last_dispatch["payload"]["metadata"]["direction"], "closer_notification")

    def test_production_outbound_posts_to_configured_url(self) -> None:
        _CaptureHandler.received_payloads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.harness.close()
            harness = TestHarness(
                ROOT,
                env_overrides={
                    "CLOSER_NOTIFICATION_METHOD": "whatsapp",
                    "CLOSER_PHONE_NUMBER": "5216161249340",
                    "WHATSAPP_OUTBOUND_ENABLED": "true",
                    "WHATSAPP_OUTBOUND_URL": f"http://127.0.0.1:{server.server_port}",
                    "WHATSAPP_MODE": "production",
                },
            )
            self.addCleanup(harness.close)
            harness.run(
                [
                    "hola",
                    "me interesa el de zona rio",
                    "si tengo recursos propios",
                    "si me funciona",
                    "entiendo que es remate y quiero que me contacte un asesor",
                    "Omar, está bien si le llaman a las 4pm",
                ]
            )
        finally:
            server.shutdown()
            server.server_close()

        self.assertGreaterEqual(len(_CaptureHandler.received_payloads), 1)
        closer_payloads = [
            payload
            for payload in _CaptureHandler.received_payloads
            if payload.get("metadata", {}).get("direction") == "closer_notification"
        ]
        self.assertEqual(len(closer_payloads), 1)
        self.assertEqual(closer_payloads[0]["to"], "5216161249340")
        self.assertIn("Lead listo para closer LUAL", closer_payloads[0]["message"])
