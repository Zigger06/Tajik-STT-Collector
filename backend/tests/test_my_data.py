from __future__ import annotations

import hashlib
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
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from collector.database import Database
from collector.http_api import make_handler
from collector.security import DeviceSecurity
from collector.service import CollectorService, ForbiddenError


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


class MyDataHttpTest(unittest.TestCase):
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
                display_name=f"My data tester {index}",
                consent=True,
                challenge_nonce=challenge["nonce"],
                challenge_proof=solve_pow(challenge["nonce"], challenge["difficulty"]),
                ip="127.0.0.1",
            )
            self.identities.append((volunteer_id, secret))

        self.service.import_texts(
            [
                {"text": "Матни якум барои назорати маълумот."},
                {"text": "Матни дуюм барои назорати маълумот."},
                {"text": "Матни сеюм барои назорати маълумот."},
            ],
            approved=True,
        )
        self.text_ids = []
        with self.service.database.connect() as connection:
            self.text_ids = [
                row["id"]
                for row in connection.execute("SELECT id FROM texts ORDER BY id").fetchall()
            ]

        self.recording_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        self.service.submit_recording(
            self.recording_ids[0],
            self.text_ids[0],
            self.identities[0][0],
            duration_ms=800,
            sample_rate=16000,
            audio=make_wav(),
        )
        self.service.submit_recording(
            self.recording_ids[1],
            self.text_ids[1],
            self.identities[1][0],
            duration_ms=800,
            sample_rate=16000,
            audio=make_wav(),
        )

        handler = make_handler(
            self.service,
            "",
            self.admin,
            allow_admin=False,
            security_context=self.security,
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

    def auth_headers(self, identity_index: int) -> dict[str, str]:
        volunteer_id, secret = self.identities[identity_index]
        return {
            "X-Volunteer-Id": volunteer_id,
            "Authorization": f"Bearer {secret}",
        }

    def request(
        self,
        path: str,
        identity_index: int,
        method: str = "GET",
        body: dict | None = None,
    ) -> tuple[int, bytes, dict]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = self.auth_headers(identity_index)
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.read(), dict(response.headers.items())

    def approve_first_recording(self) -> None:
        recording_id = self.recording_ids[0]
        self.service.submit_audio_review(recording_id, self.identities[1][0], "approve")
        self.service.submit_audio_review(recording_id, self.identities[2][0], "approve")

    def test_view_download_and_archive_are_strictly_owner_scoped(self) -> None:
        status, raw, _ = self.request("/api/v1/me/recordings", 0)
        self.assertEqual(status, 200)
        payload = json.loads(raw)
        self.assertTrue(payload["consent_active"])
        self.assertEqual([item["id"] for item in payload["recordings"]], [self.recording_ids[0]])
        self.assertNotIn("volunteer_id", payload["recordings"][0])

        status, audio, _ = self.request(
            f"/api/v1/me/recordings/{self.recording_ids[0]}/audio", 0
        )
        self.assertEqual(status, 200)
        self.assertTrue(audio.startswith(b"RIFF"))

        with self.assertRaises(urllib.error.HTTPError) as foreign:
            self.request(f"/api/v1/me/recordings/{self.recording_ids[1]}/audio", 0)
        self.assertEqual(foreign.exception.code, 404)

        # Knowing a recording UUID is no longer enough to fetch reviewer media.
        with self.assertRaises(urllib.error.HTTPError) as raw_media:
            urllib.request.urlopen(
                self.base + f"/media/{self.recording_ids[1]}.wav", timeout=3
            )
        self.assertEqual(raw_media.exception.code, 404)

        status, archive_bytes, headers = self.request(
            "/api/v1/me/recordings/archive", 0
        )
        self.assertEqual(status, 200)
        self.assertIn("application/zip", headers.get("Content-Type", ""))
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = set(archive.namelist())
            self.assertIn(f"{self.recording_ids[0]}.wav", names)
            self.assertNotIn(f"{self.recording_ids[1]}.wav", names)
            self.assertIn("recordings.json", names)

    def test_delete_one_removes_source_reviews_and_future_export(self) -> None:
        self.approve_first_recording()
        first_path = self.service.volunteer_recording_path(
            self.identities[0][0], self.recording_ids[0]
        )
        before = self.service.export_dataset(Path(self.temp.name) / "export-before")
        self.assertEqual(before["exported"], 1)

        status, raw, _ = self.request(
            f"/api/v1/me/recordings/{self.recording_ids[0]}", 0, method="DELETE"
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)["deleted"])
        self.assertFalse(first_path.exists())

        with self.service.database.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM recordings WHERE id = ?", (self.recording_ids[0],)
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM audio_reviews WHERE recording_id = ?",
                    (self.recording_ids[0],),
                ).fetchone()[0],
                0,
            )

        after = self.service.export_dataset(Path(self.temp.name) / "export-after")
        self.assertEqual(after["exported"], 0)

    def test_delete_all_removes_only_the_authenticated_owners_recordings(self) -> None:
        third_recording = str(uuid.uuid4())
        self.service.submit_recording(
            third_recording,
            self.text_ids[2],
            self.identities[0][0],
            duration_ms=800,
            sample_rate=16000,
            audio=make_wav(),
        )
        status, raw, _ = self.request(
            "/api/v1/me/recordings", 0, method="DELETE"
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["deleted"], 2)

        with self.service.database.connect() as connection:
            owner_zero = connection.execute(
                "SELECT COUNT(*) FROM recordings WHERE volunteer_id = ?",
                (self.identities[0][0],),
            ).fetchone()[0]
            owner_one = connection.execute(
                "SELECT COUNT(*) FROM recordings WHERE volunteer_id = ?",
                (self.identities[1][0],),
            ).fetchone()[0]
        self.assertEqual(owner_zero, 0)
        self.assertEqual(owner_one, 1)

    def test_revoke_consent_stops_contribution_and_future_export_but_keeps_my_data(self) -> None:
        self.approve_first_recording()
        before = self.service.export_dataset(Path(self.temp.name) / "export-active")
        self.assertEqual(before["exported"], 1)

        status, raw, _ = self.request(
            "/api/v1/me/revoke-consent", 0, method="POST", body={}
        )
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(raw)["consent_active"])

        with self.assertRaises(urllib.error.HTTPError) as blocked:
            self.request("/api/v1/volunteers/stats", 0)
        self.assertEqual(blocked.exception.code, 403)

        # My Data remains available specifically so the user can download/delete.
        status, raw, _ = self.request("/api/v1/me/recordings", 0)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(raw)["consent_active"])

        after = self.service.export_dataset(Path(self.temp.name) / "export-revoked")
        self.assertEqual(after["exported"], 0)

        volunteer_id, secret = self.identities[0]
        with self.assertRaises(ForbiddenError):
            self.security.register_volunteer(
                volunteer_id=volunteer_id,
                secret=secret,
                display_name="My data tester 0",
                consent=True,
                ip="127.0.0.1",
            )

    def test_reviewer_task_hides_owner_identity_and_uses_assignment_capability(self) -> None:
        status, raw, _ = self.request("/api/v1/tasks/audio-review", 2)
        self.assertEqual(status, 200)
        task = json.loads(raw)["task"]
        self.assertIsNotNone(task)
        self.assertNotIn("volunteer_id", task)
        self.assertNotIn("display_name", task)
        self.assertIn("review_token=", task["audio_url"])

        with urllib.request.urlopen(self.base + task["audio_url"], timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.read().startswith(b"RIFF"))


if __name__ == "__main__":
    unittest.main()
