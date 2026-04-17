from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.test_support import TestHarness


ROOT = Path(__file__).resolve().parents[1]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _MetaCaptureHandler(BaseHTTPRequestHandler):
    received_requests: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length).decode("utf-8")
        self.__class__.received_requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": json.loads(raw_body or "{}"),
            }
        )
        payload = json.dumps({"messages": [{"id": "wamid.test"}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class MetaTransportIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = TestHarness(ROOT)

    def tearDown(self) -> None:
        self.harness.close()

    def _start_runtime(self, env_overrides: dict[str, str] | None = None) -> tuple[subprocess.Popen, int]:
        port = _find_free_port()
        env = os.environ.copy()
        env.update(
            {
                "ENABLE_LLM_ASSIST": "false",
                "OPENAI_TURN_UNDERSTANDING_ENABLED": "false",
                "STATE_STORAGE_DIR": str(self.harness.runtime_root / f"runtime_state_{port}"),
                "CLOSER_CONSOLE_LOG_PATH": str(self.harness.runtime_root / f"runtime_closer_{port}.log"),
                "LIVE_API_LOG_PATH": str(self.harness.runtime_root / f"runtime_live_{port}.jsonl"),
                "WHATSAPP_DISPATCH_LOG_PATH": str(self.harness.runtime_root / f"runtime_whatsapp_{port}.log"),
                "WHATSAPP_MODE": "meta",
                "WHATSAPP_WEBHOOK_ENABLED": "true",
                "WHATSAPP_OUTBOUND_ENABLED": "false",
                "WHATSAPP_VERIFY_TOKEN": "verify-token-lual",
                "HOST": "127.0.0.1",
                "PORT": str(port),
            }
        )
        if env_overrides:
            env.update(env_overrides)
        process = subprocess.Popen(
            ["python3", "runtime_entrypoint.py", "serve", "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self._stop_runtime, process)
        self._wait_for_health(port)
        return process, port

    def _stop_runtime(self, process: subprocess.Popen) -> None:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()

    def _wait_for_health(self, port: int) -> None:
        health_url = f"http://127.0.0.1:{port}/health"
        last_error: Exception | None = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(health_url, timeout=1) as response:
                    if response.status == 200:
                        return
            except Exception as exc:  # pragma: no cover - retry path
                last_error = exc
                time.sleep(0.1)
        raise AssertionError(f"Runtime did not become healthy on port {port}: {last_error}")

    def test_meta_webhook_verification_returns_challenge(self) -> None:
        _, port = self._start_runtime()
        verify_url = (
            f"http://127.0.0.1:{port}/meta/webhook"
            "?hub.mode=subscribe&hub.verify_token=verify-token-lual&hub.challenge=abc123"
        )
        with urllib.request.urlopen(verify_url, timeout=2) as response:
            body = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertEqual(body, "abc123")

    def test_meta_webhook_post_processes_inbound_message(self) -> None:
        _, port = self._start_runtime({"WHATSAPP_MODE": "stub"})
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "contacts": [
                                    {
                                        "wa_id": "5216641234567",
                                        "profile": {"name": "Omar"},
                                    }
                                ],
                                "messages": [
                                    {
                                        "from": "5216641234567",
                                        "id": "wamid.inbound.1",
                                        "timestamp": "1710000000",
                                        "type": "text",
                                        "text": {"body": "hola"},
                                    }
                                ],
                            },
                        }
                    ]
                }
            ],
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/meta/webhook",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(body["processed_messages"], 1)
        self.assertEqual(body["results"][0]["phone_number"], "5216641234567")
        self.assertEqual(body["results"][0]["state"]["stage"], "discovery")
        self.assertEqual(
            body["results"][0]["reply_text"],
            "¡Hola! Bienvenido a LUAL Real Estate. ¿En qué puedo ayudarte?",
        )

    def test_meta_outbound_and_handoff_use_graph_api_transport(self) -> None:
        _MetaCaptureHandler.received_requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MetaCaptureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.harness.close()
            harness = TestHarness(
                ROOT,
                env_overrides={
                    "CLOSER_NOTIFICATION_METHOD": "whatsapp",
                    "CLOSER_PHONE_NUMBER": "5216161249340",
                    "WHATSAPP_MODE": "meta",
                    "WHATSAPP_PHONE_NUMBER_ID": "1234567890",
                    "WHATSAPP_ACCESS_TOKEN": "meta-test-token",
                    "WHATSAPP_GRAPH_API_VERSION": "v99.0",
                    "WHATSAPP_GRAPH_API_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                },
            )
            self.addCleanup(harness.close)
            for message in [
                "hola",
                "me interesa el de zona rio",
                "si tengo recursos propios",
                "si me funciona",
                "entiendo que es remate y quiero que me contacte un asesor",
                "Omar, está bien si le llaman a las 4pm",
            ]:
                harness.send_via_adapter(message)
        finally:
            server.shutdown()
            server.server_close()

        self.assertGreaterEqual(len(_MetaCaptureHandler.received_requests), 2)
        self.assertTrue(
            all(
                request["path"] == "/v99.0/1234567890/messages"
                for request in _MetaCaptureHandler.received_requests
            )
        )
        self.assertTrue(
            all(
                request["headers"].get("Authorization") == "Bearer meta-test-token"
                for request in _MetaCaptureHandler.received_requests
            )
        )
        lead_payloads = [
            request["body"]
            for request in _MetaCaptureHandler.received_requests
            if request["body"].get("to") == "5216640000000"
        ]
        closer_payloads = [
            request["body"]
            for request in _MetaCaptureHandler.received_requests
            if request["body"].get("to") == "5216161249340"
        ]
        self.assertGreaterEqual(len(lead_payloads), 1)
        self.assertEqual(len(closer_payloads), 1)
        self.assertEqual(closer_payloads[0]["messaging_product"], "whatsapp")
        self.assertEqual(closer_payloads[0]["type"], "text")
        self.assertIn("Lead listo para closer LUAL", closer_payloads[0]["text"]["body"])
