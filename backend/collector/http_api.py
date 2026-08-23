from __future__ import annotations

import json
import mimetypes
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type
from urllib.parse import parse_qs, urlparse

from .service import CollectorError, CollectorService


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024


def make_handler(
    service: CollectorService,
    api_key: str,
    admin_file: str | Path,
    public_base_url: str = "",
    allow_admin: bool = True,
) -> Type[BaseHTTPRequestHandler]:
    admin_path = Path(admin_file)

    class CollectorRequestHandler(BaseHTTPRequestHandler):
        server_version = "TajikSTTCollector/0.1"

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors_headers()
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Project-Key")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if parsed.path in ("/", "/admin"):
                    if allow_admin:
                        self._serve_admin()
                    else:
                        self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                    return
                if parsed.path == "/health":
                    self._send_json({"ok": True, "service": "tajik-stt-collector"})
                    return
                if not self._is_authorized(parsed):
                    self._send_error(HTTPStatus.UNAUTHORIZED, "invalid project key")
                    return

                query = parse_qs(parsed.query)
                if parsed.path == "/api/v1/stats" and allow_admin:
                    self._send_json(service.stats())
                elif parsed.path == "/api/v1/tasks/recording":
                    excluded = query.get("exclude_text_ids", [""])[0]
                    excluded_text_ids = [
                        int(value) for value in excluded.split(",") if value.strip()
                    ]
                    task = service.get_recording_task(
                        self._required_query(query, "volunteer_id"),
                        excluded_text_ids,
                    )
                    self._send_json({"task": task})
                elif parsed.path == "/api/v1/volunteers/stats":
                    stats = service.volunteer_stats(
                        self._required_query(query, "volunteer_id")
                    )
                    self._send_json(stats)
                elif parsed.path == "/api/v1/tasks/text-review":
                    task = service.get_text_review_task(self._required_query(query, "volunteer_id"))
                    self._send_json({"task": task})
                elif parsed.path == "/api/v1/tasks/audio-review":
                    volunteer_id = self._required_query(query, "volunteer_id")
                    task = service.get_audio_review_task(volunteer_id)
                    self._send_json({"task": task})
                elif parsed.path == "/api/v1/admin/texts/needs-admin" and allow_admin:
                    self._send_json({"texts": service.list_needs_admin()})
                elif parsed.path.startswith("/media/") and parsed.path.endswith(".wav"):
                    recording_id = parsed.path.removeprefix("/media/").removesuffix(".wav")
                    self._serve_file(service.recording_path(recording_id), "audio/wav")
                else:
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
            except CollectorError as exc:
                self._send_error(exc.status_code, str(exc))
            except Exception as exc:  # pragma: no cover - last-resort server protection
                traceback.print_exc()
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if not self._is_authorized(parsed):
                    self._send_error(HTTPStatus.UNAUTHORIZED, "invalid project key")
                    return
                query = parse_qs(parsed.query)

                if parsed.path == "/api/v1/volunteers":
                    body = self._read_json()
                    result = service.register_volunteer(
                        volunteer_id=body.get("id", ""),
                        display_name=body.get("display_name", ""),
                        region=body.get("region", ""),
                        dialect=body.get("dialect", ""),
                        consent=body.get("consent") is True,
                    )
                    self._send_json(result, HTTPStatus.CREATED)
                elif parsed.path == "/api/v1/recordings":
                    content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
                    if content_type not in ("audio/wav", "audio/x-wav", "application/octet-stream"):
                        raise CollectorError("Content-Type must be audio/wav")
                    length = self._content_length(MAX_AUDIO_BYTES)
                    audio = self.rfile.read(length)
                    result = service.submit_recording(
                        recording_id=self._required_query(query, "recording_id"),
                        text_id=int(self._required_query(query, "text_id")),
                        volunteer_id=self._required_query(query, "volunteer_id"),
                        duration_ms=int(self._required_query(query, "duration_ms")),
                        sample_rate=int(query.get("sample_rate", ["16000"])[0]),
                        audio=audio,
                    )
                    self._send_json(result, HTTPStatus.CREATED)
                elif parsed.path == "/api/v1/text-reviews":
                    body = self._read_json()
                    result = service.submit_text_review(
                        text_id=int(body.get("text_id", 0)),
                        volunteer_id=body.get("volunteer_id", ""),
                        verdict=body.get("verdict", ""),
                        correction=body.get("correction", ""),
                    )
                    self._send_json(result, HTTPStatus.CREATED)
                elif parsed.path == "/api/v1/audio-reviews":
                    body = self._read_json()
                    result = service.submit_audio_review(
                        recording_id=body.get("recording_id", ""),
                        volunteer_id=body.get("volunteer_id", ""),
                        verdict=body.get("verdict", ""),
                        reason=body.get("reason", ""),
                    )
                    self._send_json(result, HTTPStatus.CREATED)
                elif parsed.path == "/api/v1/admin/texts/import" and allow_admin:
                    body = self._read_json()
                    raw_texts = body.get("texts", [])
                    if not isinstance(raw_texts, list):
                        raise CollectorError("texts must be a JSON array")
                    items = [
                        item if isinstance(item, dict) else {"text": str(item)}
                        for item in raw_texts
                    ]
                    result = service.import_texts(
                        items=items,
                        default_source=body.get("source", ""),
                        approved=body.get("approved") is True,
                        required_recordings=int(body.get("required_recordings", 5)),
                    )
                    self._send_json(result, HTTPStatus.CREATED)
                elif parsed.path == "/api/v1/admin/texts/resolve" and allow_admin:
                    body = self._read_json()
                    result = service.resolve_text(
                        text_id=int(body.get("text_id", 0)),
                        action=body.get("action", ""),
                        content=body.get("content", ""),
                    )
                    self._send_json(result)
                else:
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
            except ValueError:
                self._send_error(HTTPStatus.BAD_REQUEST, "numeric parameter is invalid")
            except CollectorError as exc:
                self._send_error(exc.status_code, str(exc))
            except Exception as exc:  # pragma: no cover - last-resort server protection
                traceback.print_exc()
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

        def _is_authorized(self, parsed) -> bool:
            if not allow_admin:
                return True
            supplied = self.headers.get("X-Project-Key", "")
            return bool(api_key) and supplied == api_key

        def _read_json(self) -> dict:
            length = self._content_length(MAX_JSON_BYTES)
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CollectorError("request body must be valid UTF-8 JSON") from exc
            if not isinstance(body, dict):
                raise CollectorError("JSON body must be an object")
            return body

        def _content_length(self, maximum: int) -> int:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise CollectorError("invalid Content-Length") from exc
            if length <= 0 or length > maximum:
                raise CollectorError("request body size is invalid")
            return length

        @staticmethod
        def _required_query(query: dict, name: str) -> str:
            value = query.get(name, [""])[0]
            if not value:
                raise CollectorError(f"missing query parameter: {name}")
            return value

        def _serve_admin(self) -> None:
            if not admin_path.exists():
                self._send_error(HTTPStatus.NOT_FOUND, "admin page not found")
                return
            self._serve_file(admin_path, "text/html; charset=utf-8")

        def _serve_file(self, path: Path, content_type: str | None = None) -> None:
            try:
                data = path.read_bytes()
            except OSError:
                self._send_error(HTTPStatus.NOT_FOUND, "file not found")
                return
            self.send_response(HTTPStatus.OK)
            self._cors_headers()
            self.send_header(
                "Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, value: object, status: int = HTTPStatus.OK) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_error(self, status: int, message: str) -> None:
            self._send_json({"error": message}, status)

        def _cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")

        def log_message(self, format: str, *args) -> None:
            print(f"{self.client_address[0]} - {format % args}")

    return CollectorRequestHandler


def serve(
    service: CollectorService,
    host: str,
    port: int,
    api_key: str,
    admin_file: str | Path,
    public_base_url: str = "",
    allow_admin: bool = True,
) -> None:
    handler = make_handler(
        service, api_key, admin_file, public_base_url, allow_admin=allow_admin
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Tajik STT Collector: http://127.0.0.1:{port}/admin")
    print(f"Android API: http://<PC-IP>:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


def serve_online(
    service: CollectorService,
    public_host: str,
    public_port: int,
    admin_host: str,
    admin_port: int,
    admin_key: str,
    admin_file: str | Path,
) -> None:
    """Run a Funnel-facing API and a separate computer-only admin panel."""
    public_handler = make_handler(
        service,
        "",
        admin_file,
        allow_admin=False,
    )
    admin_handler = make_handler(
        service,
        admin_key,
        admin_file,
        allow_admin=True,
    )
    public_server = ThreadingHTTPServer((public_host, public_port), public_handler)
    admin_server = ThreadingHTTPServer((admin_host, admin_port), admin_handler)
    public_thread = threading.Thread(target=public_server.serve_forever, daemon=True)
    public_thread.start()

    print(f"Public Android API target: http://{public_host}:{public_port}")
    print(f"Private admin panel: http://127.0.0.1:{admin_port}/admin")
    print("The admin panel is not exposed through Tailscale Funnel.")
    print("Press Ctrl+C to stop both servers.")
    try:
        admin_server.serve_forever()
    except KeyboardInterrupt:
        print("\nServers stopped.")
    finally:
        admin_server.server_close()
        public_server.shutdown()
        public_server.server_close()
        public_thread.join(timeout=2)
