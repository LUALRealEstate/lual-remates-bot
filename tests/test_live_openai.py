from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from app.bootstrap import get_live_client
from app.config import get_settings


ROOT = Path(__file__).resolve().parents[1]


class OpenAILiveTests(unittest.TestCase):
    def test_live_responses_api_call(self) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            self.skipTest("OPENAI_API_KEY no está configurada.")

        os.environ["ENABLE_LLM_ASSIST"] = "true"
        client = get_live_client(str(ROOT))
        result = client.complete(
            prompt_name="live_probe",
            instructions="Responde en una sola línea con la palabra LISTO y una frase corta sobre remates hipotecarios.",
            input_text="Prueba de integración local para LUAL.",
        )
        self.assertTrue(result.trace.response_id)
        self.assertGreater(result.trace.latency_ms, 0)
        self.assertIn("LISTO", result.text.upper())

        settings = get_settings(str(ROOT))
        artifact_path = settings.project_root / "artifacts" / "openai_live_probe.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(
                {
                    "model": result.trace.model,
                    "response_id": result.trace.response_id,
                    "latency_ms": result.trace.latency_ms,
                    "output_text": result.text,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
