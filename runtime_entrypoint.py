from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from app.bootstrap import build_whatsapp_adapter
from app.meta_cloud_api import (
    META_WEBHOOK_PATH,
    extract_meta_inbound_messages,
    is_meta_webhook_verification,
    verify_meta_webhook,
)
from app.transport_adapter import IncomingMessage


def handle_single_message(
    *,
    phone_number: str,
    message: str,
    metadata: dict | None = None,
    project_root: str | None = None,
) -> dict:
    adapter = build_whatsapp_adapter(project_root)
    result = adapter.process_incoming(
        IncomingMessage(
            phone_number=phone_number,
            message=message,
            metadata=metadata or {},
        )
    )
    payload = {
        "phone_number": result.phone_number,
        "reply_text": result.reply_text,
        "state": result.state,
        "handoff_summary": result.handoff_summary,
    }
    if result.outbound_result:
        payload["outbound_result"] = result.outbound_result.__dict__
    return payload


def serve_http(host: str, port: int, project_root: str | None = None) -> None:
    adapter = build_whatsapp_adapter(project_root)
    settings = adapter.settings

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if is_meta_webhook_verification(self.path):
                status, body, content_type = verify_meta_webhook(self.path, settings)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if urlparse(self.path).path == "/health":
                body = b'{"status":"ok"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path not in {"/whatsapp/incoming", META_WEBHOOK_PATH}:
                self.send_response(404)
                self.end_headers()
                return

            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(raw_body or "{}")
                if path == META_WEBHOOK_PATH:
                    results = []
                    inbound_messages = extract_meta_inbound_messages(payload)
                    for inbound in inbound_messages:
                        result = adapter.process_incoming(
                            IncomingMessage(
                                phone_number=inbound.phone_number,
                                message=inbound.text,
                                metadata=inbound.metadata,
                            )
                        )
                        results.append(
                            {
                                "phone_number": result.phone_number,
                                "reply_text": result.reply_text,
                                "state": result.state,
                                "handoff_summary": result.handoff_summary,
                                "outbound_result": result.outbound_result.__dict__
                                if result.outbound_result
                                else None,
                            }
                        )
                    response_payload = {
                        "processed_messages": len(results),
                        "results": results,
                    }
                else:
                    incoming = IncomingMessage(
                        phone_number=payload["phone_number"],
                        message=payload["message"],
                        metadata=payload.get("metadata", {}),
                    )
                    result = adapter.process_incoming(incoming)
                    response_payload = {
                        "phone_number": result.phone_number,
                        "reply_text": result.reply_text,
                        "state": result.state,
                        "handoff_summary": result.handoff_summary,
                        "outbound_result": result.outbound_result.__dict__
                        if result.outbound_result
                        else None,
                    }
                body = json.dumps(response_payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
            except Exception as exc:  # pragma: no cover - defensive runtime path
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(400)

            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"WhatsApp runtime escuchando en http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Runtime entrypoint for WhatsApp-style integration.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    message_parser = subparsers.add_parser("message", help="Process one inbound message")
    message_parser.add_argument("--phone", required=True)
    message_parser.add_argument("--text", required=True)
    message_parser.add_argument("--metadata-json", default="{}")
    message_parser.add_argument("--project-root", default=None)

    serve_parser = subparsers.add_parser("serve", help="Run a simple webhook-compatible HTTP server")
    serve_parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    serve_parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    serve_parser.add_argument("--project-root", default=None)

    args = parser.parse_args()

    if args.command == "message":
        payload = handle_single_message(
            phone_number=args.phone,
            message=args.text,
            metadata=json.loads(args.metadata_json or "{}"),
            project_root=args.project_root,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.command == "serve":
        serve_http(args.host, args.port, args.project_root)


if __name__ == "__main__":
    main()
