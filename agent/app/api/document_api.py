"""Document Write/Read REST API.

Lightweight HTTP layer on top of the Parent Orchestrator runtime.
Uses Python's built-in http.server for the skeleton; can be swapped
to FastAPI/Flask in production.

Endpoints:
  POST /documents/{docId}/user-input  — save user edit
  GET  /documents/{docId}             — full state (fallback)
  POST /documents/{docId}/review      — trigger review
  POST /documents/{docId}/export      — trigger DOCX export
"""

from __future__ import annotations

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from agent.lib.storage.dynamodb import DocumentStore, DocumentNotFoundError
from agent.lib.schema.document_state import DocumentState
from agent.lib.storage.conversation_history import ConversationHistoryStore


store = DocumentStore()
history_store = ConversationHistoryStore()


def _set_nested(obj: dict, path: str, value: Any) -> None:
    """Set a value in a nested dict using a JSON-pointer-style path."""
    parts = [p for p in path.strip("/").split("/") if p]
    current = obj
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    if parts:
        current[parts[-1]] = value


class DocumentAPIHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: Any) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _parse_doc_id(self) -> str | None:
        # /documents/{docId}/...
        parts = self.path.strip("/").split("/")
        return parts[1] if len(parts) >= 2 and parts[0] == "documents" else None

    def do_GET(self) -> None:
        doc_id = self._parse_doc_id()
        if not doc_id:
            self._send_json(400, {"error": "missing doc_id"})
            return

        parts = self.path.strip("/").split("/")
        action = parts[2] if len(parts) >= 3 else ""

        if action == "history":
            # Parse query string for session_id
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            session_id = qs.get("session_id", [None])[0]
            item = history_store.load(doc_id, session_id)
            if not item:
                self._send_json(200, {
                    "document_id": doc_id,
                    "session_id": session_id or "",
                    "messages": [],
                    "bounded_window": 20,
                    "total_count": 0,
                })
            else:
                self._send_json(200, item)
            return

        try:
            doc = store.get(doc_id)
            self._send_json(200, doc.model_dump(mode="json"))
        except DocumentNotFoundError:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        doc_id = self._parse_doc_id()
        if not doc_id:
            self._send_json(400, {"error": "missing doc_id"})
            return

        parts = self.path.strip("/").split("/")
        action = parts[2] if len(parts) >= 3 else ""

        if action == "user-input":
            body = self._read_body()
            try:
                doc = store.get(doc_id)
            except DocumentNotFoundError:
                doc = DocumentState(document_id=doc_id)
            data = doc.model_dump(mode="json")
            _set_nested(data, body.get("path", ""), body.get("value"))
            updated = DocumentState.model_validate(data)
            store.put(updated)
            self._send_json(200, {"status": "ok", "version": updated.version})

        elif action == "history":
            body = self._read_body()
            session_id = body.get("session_id", "default")
            messages = body.get("messages", [])
            bounded_window = body.get("bounded_window", 20)
            item = history_store.save(doc_id, session_id, messages, bounded_window=bounded_window)
            self._send_json(200, {
                "status": "ok",
                "document_id": doc_id,
                "session_id": session_id,
                "total_count": len(messages),
                "bounded_window": bounded_window,
            })

        elif action == "review":
            self._send_json(200, {"status": "review_requested", "doc_id": doc_id})

        elif action == "export":
            self._send_json(200, {"status": "export_requested", "doc_id": doc_id})

        else:
            self._send_json(400, {"error": f"unknown action: {action}"})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass  # suppress logs in skeleton


def create_server(port: int = 8080) -> HTTPServer:
    return HTTPServer(("0.0.0.0", port), DocumentAPIHandler)


if __name__ == "__main__":
    server = create_server()
    print(f"Document API running on http://localhost:8080")
    server.serve_forever()
