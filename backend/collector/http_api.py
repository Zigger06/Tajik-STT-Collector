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

from .security import DeviceSecurity, RateLimitError
from .service import CollectorError, CollectorService


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024


def make_handler(
    service: CollectorService,
    api_key: str,
    admin_file: str | Path,
    public_base_url: str = "",
    allow_admin: bool = True,
    security_context: DeviceSecurity | None = None,
) -> Type[BaseHTTPRequestHandler]:
    admin_path = Path(admin_file)
    security = security_context or DeviceSecurity(service)

    class CollectorRequestHandler(BaseHTTPRequestHandler):
        server_version = "TajikSTTCollector/0.2"

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
                if parsed.path == "/api/v1/registration-challenge":
                    volunteer_id = self.headers.get("X-Volunteer-Id", "")
                    secret = self._bearer_secret()
                    challenge = security.issue_registration_challenge(
                        volunteer_id, secret, self._client_ip()
                    )
                    self._send_json(challenge)
                    return

                if parsed.path == "/api/v1/stats":
                    self._require_admin_route()
                    self._send_json(service.stats())
                    return
                if parsed.path == "/api/v1/admin/texts/needs-admin":
                    self._require_admin_route()
                    self._send_json({"texts": service.list_needs_admin()})
                    return

                # Reviewer media gets dedicated short-lived assignment tokens in
                # security stage 4. Until then preserve the existing UUID media
                # flow so this stage does not break Android playback.
                if parsed.path.startswith("/media/") and parsed.path.endswith(".wav"):
                    recording_id = parsed.path.removeprefix("/media/").removesuffix(".wav")
                    self._serve_file(service.recording_path(recording_id), "audio/wav")
                    return

                query = parse_qs(parsed.query)
                if parsed.path == "/api/v1/tasks/recording":
                    volunteer_id = self._authenticated_volunteer("task")
                    excluded = query.get("exclude_text_ids", [""])[0]
                    excluded_text_ids = [
                        int(value) for value in excluded.split(",") if value.strip()
                    ]
                    task = service.get_recording_task(volunteer_id, excluded_text_ids)
                    self._send_json({"task": task})
                elif parsed.path == "/api/v1/volunteers/stats":
                    volunteer_id = self._authenticated_volunteer("stats")
                    self._send_json(service.volunteer_stats(volunteer_id))
                elif parsed.path == "/api/v1/tasks/text-review":
                    volunteer_id = self._authenticated_volunteer("task")
                    self._send_json({"task": service.get_text_review_task(volunteer_id)})
                elif parsed.path == "/api/v1/tasks/audio-review":
                    volunteer_id = self._authenticated_volunteer("task")
                    self._send_json({"task": service.get_audio_review_task(volunteer_id)})
                else:
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
            except RateLimitError as exc:
                self._log_rate_limit(exc)
                self._send_error(exc.status_code, str(exc), retry_after=exc.retry_after)
            except CollectorError as exc:
                self._send_error(exc.status_code, str(exc))
            except ValueError:
                self._send_error(HTTPStatus.BAD_REQUEST, "numeric parameter is invalid")
            except Exception as exc:  # pragma: no cover - last-resort server protection
                traceback.print_exc()
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)

                if parsed.path == "/api/v1/admin/texts/import":
                    self._require_admin_route()
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
                    return
                if parsed.path == "/api/v1/admin/texts/resolve":
                    self._require_admin_route()
                    body = self._read_json()
                    result = service.resolve_text(
                        text_id=int(body.get("text_id", 0)),
                        action=body.get("action", ""),
                        content=body.get("content", ""),
                    )
                    self._send_json(result)
                    return

                query = parse_qs(parsed.query)
                if parsed.path == "/api/v1/volunteers":
                    body = self._read_json()
                    result = security.register_volunteer(
                        volunteer_id=body.get("id", ""),
                        secret=self._bearer_secret(),
                        display_name=body.get("display_name", ""),
                        region=body.get("region", ""),
                        dialect=body.get("dialect", ""),
                        consent=body.get("consent") is True,
                        challenge_nonce=self.headers.get("X-Registration-Nonce", ""),
                        challenge_proof=self.headers.get("X-Registration-Proof", ""),
                        ip=self._client_ip(),
                    )
                    self._send_json(result, HTTPStatus.CREATED)
                elif parsed.path == "/api/v1/texts":
                    volunteer_id = self._authenticated_volunteer("text")
                    body = self._read_json()
                    result = service.submit_text(
                        volunteer_id=volunteer_id,
                        content=body.get("text", ""),
                        source=body.get("source", ""),
                    )
                    self._send_json(result, HTTPStatus.CREATED)
                elif parsed.path == "/api/v1/recordings":
                    volunteer_id = self._authenticated_volunteer("upload")
                    content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
                    if content_type not in ("audio/wav", "audio/x-wav", "application/octet-stream"):
                        raise CollectorError("Content-Type must be audio/wav")
                    length = self._content_length(MAX_AUDIO_BYTES)
                    audio = self.rfile.read(length)
                    result = service.submit_recording(
                        recording_id=self._required_query(query, "recording_id"),
                        text_id=int(self._required_query(query, "text_id")),
                        volunteer_id=volunteer_id,
                        duration_ms=int(self._required_query(query, "duration_ms")),
                        sample_rate=int(query.get("sample_rate", ["16000"])[0]),
                        audio=audio,
                    )
                    self._send_json(result, HTTPStatus.CREATED)
                elif parsed.path == "/api/v1/text-reviews":
                    volunteer_id = self._authenticated_volunteer("review")
                    body = self._read_json()
                    result = service.submit_text_review(
                        text_id=int(body.get("text_id", 0)),
                        volunteer_id=volunteer_id,
                        verdict=body.get("verdict", ""),
                        correction=body.get("correction", ""),
                    )
                    self._send_json(result, HTTPStatus.CREATED)
                elif parsed.path == "/api/v1/audio-reviews":
                    volunteer_id = self._authenticated_volunteer("review")
                    body = self._read_json()
                    result = service.submit_audio_review(
                        recording_id=body.get("recording_id", ""),
                        volunteer_id=volunteer_id,
                        verdict=body.get("verdict", ""),
                        reason=body.get("reason", ""),
                    )
                    self._send_json(result, HTTPStatus.CREATED)
                else:
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
            except RateLimitError as exc:
                self._log_rate_limit(exc)
                self._send_error(exc.status_code, str(exc), retry_after=exc.retry_after)
            except ValueError:
                self._send_error(HTTPStatus.BAD_REQUEST, "numeric parameter is invalid")
            except CollectorError as exc:
                self._send_error(exc.status_code, str(exc))
            except Exception as exc:  # pragma: no cover - last-resort server protection
                traceback.print_exc()
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

        def _authenticated_volunteer(self, category: str) -> str:
            volunteer_id = self.headers.get("X-Volunteer-Id", "")
            return security.authenticate(
                volunteer_id,
                self._bearer_secret(),
                category,
                self._client_ip(),
            )

        def _bearer_secret(self) -> str:
            authorization = self.headers.get("Authorization", "")
            prefix = "Bearer "
            if not authorization.startswith(prefix):
                return ""
            return authorization[len(prefix):].strip()

        def _require_admin_route(self) -> None:
            if not allow_admin:
                raise _RouteNotFound()
            supplied = self.headers.get("X-Project-Key", "")
            if not api_key or supplied != api_key:
                raise _AdminUnauthorized()

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
            self.send_header(
                "Content-Type",
                content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, value: object, status: int = HTTPStatus.OK) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_error(self, status: int, message: str, retry_after: int | None = None) -> None:
            data = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if retry_after is not None:
                self.send_header("Retry-After", str(retry_after))
            self.end_headers()
            self.wfile.write(data)

        def _client_ip(self) -> str:
            return self.client_address[0] if self.client_address else ""

        def _log_rate_limit(self, error: RateLimitError) -> None:
            volunteer_id = self.headers.get("X-Volunteer-Id", "")
            volunteer_hint = volunteer_id[:8] if volunteer_id else "unregistered"
            print(
                f"[abuse] rate_limited ip={self._client_ip()} "
                f"volunteer={volunteer_hint} retry_after={error.retry_after}s"
            )

        def log_message(self, format: str, *args) -> None:
            # BaseHTTPRequestHandler logs request lines, but never Authorization
            # headers. Volunteer IDs are no longer carried in normal API URLs.
            print(f"{self.client_address[0]} - {format % args}")

    return CollectorRequestHandler


class _RouteNotFound(CollectorError):
    status_code = 404

    def __init__(self):
        super().__init__("route not found")


class _AdminUnauthorized(CollectorError):
    status_code = 401

    def __init__(self):
        super().__init__("invalid project key")


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
    if admin_host != "127.0.0.1":
        raise ValueError("The online admin panel must bind to 127.0.0.1 only")

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
