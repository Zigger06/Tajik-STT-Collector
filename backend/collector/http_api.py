from __future__ import annotations

import json
import mimetypes
import re
import secrets
import tempfile
import threading
import time
import traceback
import zipfile
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Type
from urllib.parse import parse_qs, urlparse

from .security import DeviceSecurity, RateLimitError
from .service import CollectorError, CollectorService, NotFoundError


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
REVIEW_MEDIA_TTL_SECONDS = 5 * 60
REVIEW_MEDIA_MAX_USES = 3


@dataclass
class ReviewMediaGrant:
    recording_id: str
    reviewer_id: str
    expires_at: float
    remaining_uses: int


class ReviewMediaGrantStore:
    """Short-lived bearer capabilities for reviewer audio.

    Tokens live only in process memory, are scoped to one recording + reviewer,
    expire quickly, have a small successful-download budget, and are invalidated
    as soon as the reviewer submits the review. They are never persisted.
    """

    def __init__(
        self,
        ttl_seconds: int = REVIEW_MEDIA_TTL_SECONDS,
        max_uses: int = REVIEW_MEDIA_MAX_USES,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl_seconds = max(30, min(int(ttl_seconds), 15 * 60))
        self.max_uses = max(1, min(int(max_uses), 5))
        self.clock = clock
        self._items: dict[str, ReviewMediaGrant] = {}
        self._lock = threading.Lock()

    def issue(self, recording_id: str, reviewer_id: str) -> str:
        now = self.clock()
        with self._lock:
            self._purge_locked(now)
            # One current audio assignment per reviewer. Requesting a new task
            # makes older media capabilities for that reviewer useless.
            stale = [
                token for token, grant in self._items.items()
                if grant.reviewer_id == reviewer_id
            ]
            for token in stale:
                self._items.pop(token, None)
            token = secrets.token_urlsafe(32)
            self._items[token] = ReviewMediaGrant(
                recording_id=recording_id,
                reviewer_id=reviewer_id,
                expires_at=now + self.ttl_seconds,
                remaining_uses=self.max_uses,
            )
            return token

    def peek(self, token: str, recording_id: str) -> ReviewMediaGrant | None:
        """Validate a capability without spending a full-download use.

        Android MediaPlayer commonly probes/streams one playback with HTTP Range
        requests. Those byte-range requests are parts of the same download and
        must not burn the tiny full-download budget one request at a time.
        """
        if not token:
            return None
        now = self.clock()
        with self._lock:
            self._purge_locked(now)
            grant = self._items.get(token)
            if grant is None or grant.recording_id != recording_id:
                return None
            return ReviewMediaGrant(
                recording_id=grant.recording_id,
                reviewer_id=grant.reviewer_id,
                expires_at=grant.expires_at,
                remaining_uses=grant.remaining_uses,
            )

    def consume(self, token: str, recording_id: str) -> ReviewMediaGrant | None:
        if not token:
            return None
        now = self.clock()
        with self._lock:
            self._purge_locked(now)
            grant = self._items.get(token)
            if grant is None or grant.recording_id != recording_id:
                return None
            grant.remaining_uses -= 1
            result = ReviewMediaGrant(
                recording_id=grant.recording_id,
                reviewer_id=grant.reviewer_id,
                expires_at=grant.expires_at,
                remaining_uses=grant.remaining_uses,
            )
            if grant.remaining_uses <= 0:
                self._items.pop(token, None)
            return result

    def invalidate(self, recording_id: str, reviewer_id: str) -> None:
        with self._lock:
            stale = [
                token for token, grant in self._items.items()
                if grant.recording_id == recording_id and grant.reviewer_id == reviewer_id
            ]
            for token in stale:
                self._items.pop(token, None)

    def _purge_locked(self, now: float) -> None:
        stale = [
            token for token, grant in self._items.items()
            if grant.expires_at <= now or grant.remaining_uses <= 0
        ]
        for token in stale:
            self._items.pop(token, None)


def make_handler(
    service: CollectorService,
    api_key: str,
    admin_file: str | Path,
    public_base_url: str = "",
    allow_admin: bool = True,
    security_context: DeviceSecurity | None = None,
    review_grants: ReviewMediaGrantStore | None = None,
) -> Type[BaseHTTPRequestHandler]:
    del public_base_url  # Kept for compatibility with the existing launcher/API.
    admin_path = Path(admin_file).resolve()
    security = security_context or DeviceSecurity(service)
    grants = review_grants or ReviewMediaGrantStore()

    class CollectorRequestHandler(BaseHTTPRequestHandler):
        server_version = "TajikSTTCollector"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)

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

                if parsed.path == "/api/v1/me/recordings":
                    volunteer_id = self._authenticated_volunteer("data", allow_revoked=True)
                    self._send_json(
                        {
                            "recordings": service.list_volunteer_recordings(volunteer_id),
                            "consent_active": service.volunteer_consent_active(volunteer_id),
                        }
                    )
                    return
                if parsed.path == "/api/v1/me/recordings/archive":
                    volunteer_id = self._authenticated_volunteer("data", allow_revoked=True)
                    self._serve_my_archive(volunteer_id)
                    return
                own_recording_id = self._own_audio_id(parsed.path)
                if own_recording_id is not None:
                    volunteer_id = self._authenticated_volunteer("data", allow_revoked=True)
                    self._serve_file(
                        service.volunteer_recording_path(volunteer_id, own_recording_id),
                        "audio/wav",
                    )
                    return

                if parsed.path.startswith("/media/") and parsed.path.endswith(".wav"):
                    recording_id = parsed.path.removeprefix("/media/").removesuffix(".wav")
                    token = query.get("review_token", [""])[0]
                    is_range_request = bool(self.headers.get("Range", "").strip())
                    grant = (
                        grants.peek(token, recording_id)
                        if is_range_request
                        else grants.consume(token, recording_id)
                    )
                    if grant is None:
                        raise _RouteNotFound()
                    self._serve_file(
                        self._review_media_path(recording_id, grant.reviewer_id),
                        "audio/wav",
                        allow_ranges=True,
                    )
                    return

                if parsed.path in (
                    "/api/v1/tasks/recording",
                    "/api/v1/tasks/recording-batch",
                ):
                    volunteer_id = self._authenticated_volunteer("task")
                    excluded = query.get("exclude_text_ids", [""])[0]
                    excluded_text_ids = [
                        int(value) for value in excluded.split(",") if value.strip()
                    ][:100]
                    if parsed.path == "/api/v1/tasks/recording-batch":
                        limit = int(query.get("limit", ["10"])[0])
                        if not 1 <= limit <= 20:
                            raise CollectorError("limit must be between 1 and 20")
                        tasks: list[dict] = []
                        selected = list(excluded_text_ids)
                        for _ in range(limit):
                            task = service.get_recording_task(volunteer_id, selected)
                            if task is None:
                                break
                            tasks.append(task)
                            selected.append(int(task["id"]))
                        self._send_json({"tasks": tasks})
                    else:
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
                    task = service.get_audio_review_task(volunteer_id)
                    if task is not None:
                        task = dict(task)
                        token = grants.issue(task["id"], volunteer_id)
                        task["audio_url"] = f"/media/{task['id']}.wav?review_token={token}"
                        task["audio_access_ttl_seconds"] = grants.ttl_seconds
                        task["audio_access_max_uses"] = grants.max_uses
                    self._send_json({"task": task})
                else:
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
            except RateLimitError as exc:
                self._log_rate_limit(exc)
                self._send_error(exc.status_code, str(exc), retry_after=exc.retry_after)
            except CollectorError as exc:
                self._send_error(exc.status_code, str(exc))
            except ValueError:
                self._send_error(HTTPStatus.BAD_REQUEST, "numeric parameter is invalid")
            except Exception:  # pragma: no cover - last-resort server protection
                traceback.print_exc()
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal server error")

        def do_HEAD(self) -> None:  # noqa: N802
            """Serve reviewer media metadata without spending a download use."""
            try:
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                if parsed.path.startswith("/media/") and parsed.path.endswith(".wav"):
                    recording_id = parsed.path.removeprefix("/media/").removesuffix(".wav")
                    token = query.get("review_token", [""])[0]
                    grant = grants.peek(token, recording_id)
                    if grant is None:
                        raise _RouteNotFound()
                    self._serve_file(
                        self._review_media_path(recording_id, grant.reviewer_id),
                        "audio/wav",
                        allow_ranges=True,
                        head_only=True,
                    )
                    return
                self._send_error(HTTPStatus.NOT_FOUND, "route not found")
            except CollectorError as exc:
                self._send_error(exc.status_code, str(exc))
            except Exception:  # pragma: no cover
                traceback.print_exc()
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal server error")

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

                if parsed.path == "/api/v1/me/revoke-consent":
                    volunteer_id = self._authenticated_volunteer("data", allow_revoked=True)
                    self._send_json(service.revoke_consent(volunteer_id))
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
                    if content_type not in (
                        "audio/wav",
                        "audio/x-wav",
                        "application/octet-stream",
                    ):
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
                    recording_id = body.get("recording_id", "")
                    result = service.submit_audio_review(
                        recording_id=recording_id,
                        volunteer_id=volunteer_id,
                        verdict=body.get("verdict", ""),
                        reason=body.get("reason", ""),
                    )
                    grants.invalidate(recording_id, volunteer_id)
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
            except Exception:  # pragma: no cover - last-resort server protection
                traceback.print_exc()
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal server error")

        def do_DELETE(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/api/v1/me/recordings":
                    volunteer_id = self._authenticated_volunteer("data", allow_revoked=True)
                    self._send_json(service.delete_all_volunteer_recordings(volunteer_id))
                    return
                recording_id = self._own_recording_delete_id(parsed.path)
                if recording_id is not None:
                    volunteer_id = self._authenticated_volunteer("data", allow_revoked=True)
                    self._send_json(
                        service.delete_volunteer_recording(volunteer_id, recording_id)
                    )
                    return
                self._send_error(HTTPStatus.NOT_FOUND, "route not found")
            except RateLimitError as exc:
                self._log_rate_limit(exc)
                self._send_error(exc.status_code, str(exc), retry_after=exc.retry_after)
            except CollectorError as exc:
                self._send_error(exc.status_code, str(exc))
            except Exception:  # pragma: no cover - last-resort server protection
                traceback.print_exc()
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal server error")

        def _authenticated_volunteer(
            self,
            category: str,
            *,
            allow_revoked: bool = False,
        ) -> str:
            volunteer_id = self.headers.get("X-Volunteer-Id", "")
            return security.authenticate(
                volunteer_id,
                self._bearer_secret(),
                category,
                self._client_ip(),
                allow_revoked=allow_revoked,
            )

        def _bearer_secret(self) -> str:
            authorization = self.headers.get("Authorization", "")
            prefix = "Bearer "
            if not authorization.startswith(prefix):
                return ""
            return authorization[len(prefix) :].strip()

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

        @staticmethod
        def _own_audio_id(path: str) -> str | None:
            prefix = "/api/v1/me/recordings/"
            suffix = "/audio"
            if not path.startswith(prefix) or not path.endswith(suffix):
                return None
            value = path[len(prefix) : -len(suffix)].strip("/")
            if not value or "/" in value or "\\" in value:
                return None
            return value

        @staticmethod
        def _own_recording_delete_id(path: str) -> str | None:
            prefix = "/api/v1/me/recordings/"
            if not path.startswith(prefix):
                return None
            value = path[len(prefix) :].strip("/")
            if not value or "/" in value or "\\" in value or value == "archive":
                return None
            return value

        def _review_media_path(self, recording_id: str, reviewer_id: str) -> Path:
            with service.database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT r.file_path
                    FROM recordings r
                    JOIN volunteers owner ON owner.id = r.volunteer_id
                    WHERE r.id = ?
                      AND r.status = 'pending'
                      AND owner.consent_active = 1
                      AND r.volunteer_id <> ?
                      AND NOT EXISTS (
                          SELECT 1 FROM audio_reviews ar
                          WHERE ar.recording_id = r.id AND ar.volunteer_id = ?
                      )
                    """,
                    (recording_id, reviewer_id, reviewer_id),
                ).fetchone()
            if not row:
                raise _RouteNotFound()
            path = Path(row["file_path"]).resolve()
            audio_root = service.audio_dir.resolve()
            if path.parent != audio_root:
                raise _RouteNotFound()
            if not path.exists() or not path.is_file():
                raise _RouteNotFound()
            return path

        def _serve_my_archive(self, volunteer_id: str) -> None:
            recordings = service.list_volunteer_recordings(volunteer_id)
            with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b") as spool:
                exported_metadata: list[dict] = []
                with zipfile.ZipFile(spool, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for recording in recordings:
                        try:
                            path = service.volunteer_recording_path(
                                volunteer_id, recording["id"]
                            )
                        except NotFoundError:
                            continue
                        archive.write(path, arcname=f"{recording['id']}.wav")
                        exported_metadata.append(recording)
                    archive.writestr(
                        "recordings.json",
                        json.dumps(exported_metadata, ensure_ascii=False, indent=2),
                    )
                spool.seek(0, 2)
                length = spool.tell()
                spool.seek(0)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="tajik-stt-my-recordings.zip"',
                )
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self._send_security_headers()
                self.end_headers()
                while True:
                    chunk = spool.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        def _serve_admin(self) -> None:
            if not admin_path.exists():
                self._send_error(HTTPStatus.NOT_FOUND, "admin page not found")
                return
            self._serve_file(admin_path, "text/html; charset=utf-8")

        def _serve_file(
            self,
            path: Path,
            content_type: str | None = None,
            *,
            allow_ranges: bool = False,
            head_only: bool = False,
        ) -> None:
            try:
                size = path.stat().st_size
            except OSError:
                self._send_error(HTTPStatus.NOT_FOUND, "file not found")
                return

            start = 0
            end = max(0, size - 1)
            status = HTTPStatus.OK
            range_header = self.headers.get("Range", "").strip() if allow_ranges else ""
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
                if match is None or (not match.group(1) and not match.group(2)):
                    self._send_range_not_satisfiable(size)
                    return
                start_text, end_text = match.groups()
                try:
                    if start_text:
                        start = int(start_text)
                        end = int(end_text) if end_text else size - 1
                    else:
                        suffix_length = int(end_text)
                        if suffix_length <= 0:
                            raise ValueError
                        start = max(0, size - suffix_length)
                        end = size - 1
                except ValueError:
                    self._send_range_not_satisfiable(size)
                    return
                end = min(end, size - 1)
                if size <= 0 or start < 0 or start >= size or end < start:
                    self._send_range_not_satisfiable(size)
                    return
                status = HTTPStatus.PARTIAL_CONTENT

            length = 0 if size <= 0 else end - start + 1
            self.send_response(status)
            self.send_header(
                "Content-Type",
                content_type
                or mimetypes.guess_type(path.name)[0]
                or "application/octet-stream",
            )
            self.send_header("Content-Length", str(length))
            if allow_ranges:
                self.send_header("Accept-Ranges", "bytes")
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.end_headers()
            if head_only or length <= 0:
                return

            try:
                with path.open("rb") as handle:
                    handle.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = handle.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except OSError:
                # Headers may already be sent; terminate this response quietly.
                return

        def _send_range_not_satisfiable(self, size: int) -> None:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.end_headers()

        def _send_json(self, value: object, status: int = HTTPStatus.OK) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(data)

        def _send_error(
            self,
            status: int,
            message: str,
            retry_after: int | None = None,
        ) -> None:
            data = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if retry_after is not None:
                self.send_header("Retry-After", str(retry_after))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(data)

        def _send_security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Permissions-Policy",
                "camera=(), geolocation=(), microphone=()",
            )

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
            # BaseHTTPRequestHandler never logs Authorization headers. Reviewer
            # capabilities are in short-lived URLs for Android MediaPlayer, so
            # redact them before printing the request line as well.
            message = format % args
            message = re.sub(r"(review_token=)[^& ]+", r"\1<redacted>", message)
            print(f"{self.client_address[0]} - {message}")

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
        service,
        api_key,
        admin_file,
        public_base_url,
        allow_admin=allow_admin,
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
    if public_host != "127.0.0.1":
        raise ValueError("The online public API target must bind to 127.0.0.1 only")

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
