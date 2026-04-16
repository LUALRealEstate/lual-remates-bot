from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import Settings
from app.state_schema import LLMTrace


class OpenAIClientError(RuntimeError):
    """Raised when a live OpenAI request fails."""


@dataclass
class LLMResult:
    text: str
    trace: LLMTrace
    raw_response: Dict[str, Any]


class OpenAIResponsesClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.endpoint = "https://api.openai.com/v1/responses"
        self.settings.live_api_log_path.parent.mkdir(parents=True, exist_ok=True)

    def is_enabled(self) -> bool:
        return self.settings.openai_enabled

    def complete(
        self,
        *,
        prompt_name: str,
        instructions: str,
        input_text: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> LLMResult:
        if not self.settings.openai_api_key:
            raise OpenAIClientError("OPENAI_API_KEY is not configured.")

        payload: Dict[str, Any] = {
            "model": self.settings.openai_model,
            "instructions": instructions,
            "input": input_text,
            "store": False,
            "max_output_tokens": 300,
        }

        if self.settings.openai_model.startswith("gpt-5"):
            payload["reasoning"] = {"effort": "minimal"}

        if metadata:
            payload["metadata"] = metadata

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.openai_api_key}",
            },
            method="POST",
        )

        started_at = time.perf_counter()
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.settings.openai_timeout_seconds,
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OpenAIClientError(f"OpenAI HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise OpenAIClientError(f"OpenAI connection error: {exc}") from exc

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        payload = json.loads(body)
        text = self._extract_output_text(payload)
        trace = LLMTrace(
            model=payload.get("model", self.settings.openai_model),
            response_id=payload.get("id", "unknown"),
            latency_ms=latency_ms,
            prompt_name=prompt_name,
        )
        self._log_live_call(trace=trace, output_text=text)
        return LLMResult(text=text, trace=trace, raw_response=payload)

    def _extract_output_text(self, payload: Dict[str, Any]) -> str:
        texts = []
        for output_item in payload.get("output", []):
            if output_item.get("type") != "message":
                continue
            for content_item in output_item.get("content", []):
                if content_item.get("type") == "output_text":
                    texts.append(content_item.get("text", ""))
        return "\n".join(part.strip() for part in texts if part and part.strip())

    def _log_live_call(self, *, trace: LLMTrace, output_text: str) -> None:
        log_entry = {
            "model": trace.model,
            "response_id": trace.response_id,
            "latency_ms": trace.latency_ms,
            "prompt_name": trace.prompt_name,
            "output_preview": output_text[:200],
        }
        with self.settings.live_api_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


class NullLLMClient:
    def is_enabled(self) -> bool:
        return False

    def complete(self, **_: Any) -> LLMResult:
        raise OpenAIClientError("Live OpenAI is disabled.")
