from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import secrets
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

from collector.database import Database
from collector.http_api import (
    MAX_JSON_BYTES,
    ReviewMediaGrantStore,
    make_handler,
    serve_online,
)
from collector.security import DeviceSecurity
from collector.service import CollectorService


ROOT = Path(__file__).resolve().parents[2]


def make_wav(duration_ms: int = 800, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    frames = b"\x00\x00" * (sample_rate * duration_ms // 1000)
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return buffer.getvalue()


def solve_pow(nonce: str, difficulty: int) -> str:
    counter = 0
    while True:
        digest = hashlib.sha256(f"{nonce}:{counter}".encode("utf-8")).digest()
        whole, remaining = divmod(difficulty, 8)
        ok = all(digest[index] == 0 for index in range(whole))
        if ok and remaining:
            mask = 0xFF << (8 - remaining) & 0xFF
            ok = digest[whole] & mask == 0
        if ok:
            return str(counter)
        counter += 1


class ReviewMediaGrantStoreTest(unittest.TestCase):
    def test_grant_is_reviewer_scoped_short_lived_and_use_limited(self) -> None:
        now = [100.0]
        store = ReviewMediaGrantStore(
            ttl_seconds=30,
            max_uses=2,
            clock=lambda: now[0],
        )
        recording_id = str(uuid.uuid4())
        reviewer_id = str(uuid.uuid4())
        token = store.issue(recording_id, reviewer_id)

        first = store.consume(token, recording_id)
        self.assertIsNotNone(first)
        self.assertEqual(first.reviewer_id, reviewer_id)
        self.assertEqual(first.remaining_uses, 1)
        self.assertIsNotNone(store.consume(token, recording_id))
        self.assertIsNone(store.consume(token, recording_id))

        token = store.issue(recording_id, reviewer_id)
        now[0] += 31
        self.assertIsNone(store.consume(token, recording_id))

    def test_new_assignment_invalidates_older_assignment_for_same_reviewer(self) -> None:
        store = ReviewMediaGrantStore(ttl_seconds=60, max_uses=3)
        reviewer_id = str(uuid.uuid4())
        first_recording = str(uuid.uuid4())
        second_recording = str(uuid.uuid4())
        old_token = store.issue(first_recording, reviewer_id)
        new_token = store.issue(second_recording, reviewer_id)
        self.assertIsNone(store.consume(old_token, first_recording))
        self.assertIsNotNone(store.consume(new_token, second_recording))


class PrelaunchHttpSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.admin = root / "admin.html"
        self.admin.write_text("<html>ok</html>", encoding="utf-8")
        self.service = CollectorService(Database(root / "collector.db"), root / "audio")
        self.security = DeviceSecurity(self.service, challenge_difficulty=4)
        self.identities: list[tuple[str, str]] = []
        for index in range(3):
            volunteer_id = str(uuid.uuid4())
            secret = secrets.token_urlsafe(32)
            challenge = self.security.issue_registration_challenge(
                volunteer_id, secret, "127.0.0.1"
            )
            self.security.register_volunteer(
                volunteer_id=volunteer_id,
                secret=secret,
                display_name=f"Prelaunch tester {index}",
                consent=True,
                challenge_nonce=challenge["nonce"],
                challenge_proof=solve_pow(challenge["nonce"], challenge["difficulty"]),
                ip="127.0.0.1",
            )
            self.identities.append((volunteer_id, secret))

        self.service.import_texts(
            [
                {"text": "Матни санҷишии амният барои сабти овоз."},
                {"text": "Матни дуюми санҷишӣ барои боркунии WAV."},
            ],
            approved=True,
        )
        with self.service.database.connect() as connection:
            self.text_ids = [
                row["id"]
                for row in connection.execute("SELECT id FROM texts ORDER BY id").fetchall()
            ]
        self.recording_id = str(uuid.uuid4())
        self.service.submit_recording(
            self.recording_id,
            self.text_ids[0],
            self.identities[0][0],
            duration_ms=800,
            sample_rate=16000,
            audio=make_wav(),
        )

        self.grants = ReviewMediaGrantStore(ttl_seconds=60, max_uses=2)
        handler = make_handler(
            self.service,
            "",
            self.admin,
            allow_admin=False,
            security_context=self.security,
            review_grants=self.grants,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def auth_headers(self, index: int) -> dict[str, str]:
        volunteer_id, secret = self.identities[index]
        return {
            "X-Volunteer-Id": volunteer_id,
            "Authorization": f"Bearer {secret}",
        }

    def request(
        self,
        path: str,
        index: int | None = None,
        method: str = "GET",
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        headers = self.auth_headers(index) if index is not None else {}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(
            self.base + path,
            data=body,
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.read(), dict(response.headers.items())

    def audio_task(self, reviewer_index: int = 1) -> dict:
        status, raw, _ = self.request("/api/v1/tasks/audio-review", reviewer_index)
        self.assertEqual(status, 200)
        return json.loads(raw)["task"]

    def test_media_token_is_redacted_limited_and_invalid_after_review(self) -> None:
        task = self.audio_task(1)
        self.assertEqual(task["id"], self.recording_id)
        self.assertEqual(task["audio_access_ttl_seconds"], 60)
        self.assertEqual(task["audio_access_max_uses"], 2)
        token = task["audio_url"].split("review_token=", 1)[1]

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            status, audio, _ = self.request(task["audio_url"])
        self.assertEqual(status, 200)
        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertNotIn(token, captured.getvalue())
        self.assertIn("review_token=<redacted>", captured.getvalue())

        self.assertEqual(self.request(task["audio_url"])[0], 200)
        with self.assertRaises(urllib.error.HTTPError) as exhausted:
            self.request(task["audio_url"])
        self.assertEqual(exhausted.exception.code, 404)

        # A fresh assignment works, but submitting the review kills it immediately.
        task = self.audio_task(1)
        review_body = json.dumps(
            {"recording_id": self.recording_id, "verdict": "approve", "reason": ""}
        ).encode("utf-8")
        self.assertEqual(
            self.request(
                "/api/v1/audio-reviews",
                1,
                method="POST",
                body=review_body,
                content_type="application/json",
            )[0],
            201,
        )
        with self.assertRaises(urllib.error.HTTPError) as invalidated:
            self.request(task["audio_url"])
        self.assertEqual(invalidated.exception.code, 404)

    def test_uuid_alone_admin_routes_and_global_stats_are_not_public(self) -> None:
        for path in (
            "/admin",
            "/api/v1/stats",
            "/api/v1/admin/texts/needs-admin",
        ):
            with self.assertRaises(urllib.error.HTTPError) as blocked:
                self.request(path)
            self.assertEqual(blocked.exception.code, 404)

        with self.assertRaises(urllib.error.HTTPError) as media:
            self.request(f"/media/{self.recording_id}.wav")
        self.assertEqual(media.exception.code, 404)

    def test_security_headers_and_safe_malformed_input(self) -> None:
        status, _, headers = self.request("/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertIn("microphone=()", headers.get("Permissions-Policy", ""))

        with self.assertRaises(urllib.error.HTTPError) as malformed_json:
            self.request(
                "/api/v1/texts",
                1,
                method="POST",
                body=b"{not-json",
                content_type="application/json",
            )
        self.assertEqual(malformed_json.exception.code, 400)

        with self.assertRaises(urllib.error.HTTPError) as malformed_uuid:
            self.request("/api/v1/me/recordings/not-a-uuid/audio", 1)
        self.assertEqual(malformed_uuid.exception.code, 400)

        with self.assertRaises(urllib.error.HTTPError) as traversal:
            self.request("/api/v1/me/recordings/..%2F..%2FWindows/audio", 1)
        self.assertIn(traversal.exception.code, (400, 404))

    def test_oversized_body_and_bad_wav_are_rejected(self) -> None:
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=3
        )
        connection.putrequest("POST", "/api/v1/texts")
        for name, value in self.auth_headers(1).items():
            connection.putheader(name, value)
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(MAX_JSON_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        connection.close()

        bad_audio = b"X" * 64
        path = (
            "/api/v1/recordings?recording_id="
            f"{uuid.uuid4()}&text_id={self.text_ids[1]}&duration_ms=800&sample_rate=16000"
        )
        with self.assertRaises(urllib.error.HTTPError) as bad_wav:
            self.request(
                path,
                1,
                method="POST",
                body=bad_audio,
                content_type="audio/wav",
            )
        self.assertEqual(bad_wav.exception.code, 400)

    def test_online_mode_rejects_non_loopback_public_or_admin_bind(self) -> None:
        with self.assertRaises(ValueError):
            serve_online(
                self.service,
                public_host="0.0.0.0",
                public_port=0,
                admin_host="127.0.0.1",
                admin_port=0,
                admin_key="key",
                admin_file=self.admin,
            )
        with self.assertRaises(ValueError):
            serve_online(
                self.service,
                public_host="127.0.0.1",
                public_port=0,
                admin_host="0.0.0.0",
                admin_port=0,
                admin_key="key",
                admin_file=self.admin,
            )


class FeatureRegressionMatrixTest(unittest.TestCase):
    def test_android_offline_queue_and_five_recording_batch_contract_remain_present(self) -> None:
        local_store = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/data/LocalStore.kt"
        ).read_text(encoding="utf-8")
        uploader = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/data/UploadWorker.kt"
        ).read_text(encoding="utf-8")
        ui = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/CollectorApp.kt"
        ).read_text(encoding="utf-8")
        my_data = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/MyDataScreen.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("const val RECORDING_BATCH_SIZE = 5", local_store)
        self.assertIn('"ready = 1"', local_store)
        self.assertIn("staged >= RECORDING_BATCH_SIZE", local_store)
        self.assertIn("api.uploadRecording(recording)", uploader)
        self.assertLess(
            uploader.index("api.uploadRecording(recording)"),
            uploader.index("store.removePending(recording.id)"),
        )
        for label in ("Иловаи матн", "Санҷиши матн", "Санҷиши сабт"):
            self.assertIn(label, ui)
        self.assertIn("Маълумоти ман", my_data)
        self.assertIn("Бозпас гирифтани розигӣ", my_data)


if __name__ == "__main__":
    unittest.main()
