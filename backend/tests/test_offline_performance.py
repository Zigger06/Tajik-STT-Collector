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
from http.server import ThreadingHTTPServer
from pathlib import Path

from collector.database import Database
from collector.http_api import ReviewMediaGrantStore, make_handler
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


class OfflinePerformanceContractTest(unittest.TestCase):
    def test_android_recording_hot_path_is_cached_and_persistent(self) -> None:
        local_store = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/data/LocalStore.kt"
        ).read_text(encoding="utf-8")
        api = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ApiClient.kt"
        ).read_text(encoding="utf-8")
        activity = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/MainActivity.kt"
        ).read_text(encoding="utf-8")
        uploader = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/data/UploadWorker.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("const val RECORDING_BATCH_SIZE = 5", local_store)
        self.assertIn("const val RECORDING_TASK_CACHE_TARGET = 20", local_store)
        self.assertIn("cached_recording_tasks", local_store)
        self.assertIn("fun cacheRecordingTasks", local_store)
        self.assertIn("db.delete(\n                \"cached_recording_tasks\"", local_store)
        self.assertIn("/api/v1/tasks/recording-batch", api)
        self.assertIn("cachedRecordingTask(excludeTextIds)?.let", api)
        self.assertIn("fun seedRecordingTasks", api)
        self.assertIn("store.cachedRecordingTasks()", activity)
        self.assertIn("RECORDING_TASK_CACHE_TARGET - store.cachedRecordingTaskCount()", activity)
        self.assertIn("store.cacheRecordingTasks(fresh)", uploader)
        self.assertIn("ExistingWorkPolicy.KEEP", uploader)
        self.assertLess(
            uploader.index("api.uploadRecording(recording)"),
            uploader.index("store.removePending(recording.id)"),
        )


class BatchAndRangeHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.admin = root / "admin.html"
        self.admin.write_text("<html>ok</html>", encoding="utf-8")
        self.service = CollectorService(Database(root / "collector.db"), root / "audio")
        self.security = DeviceSecurity(self.service, challenge_difficulty=4)
        self.identities: list[tuple[str, str]] = []
        for index in range(2):
            volunteer_id = str(uuid.uuid4())
            secret = secrets.token_urlsafe(32)
            challenge = self.security.issue_registration_challenge(
                volunteer_id, secret, "127.0.0.1"
            )
            self.security.register_volunteer(
                volunteer_id=volunteer_id,
                secret=secret,
                display_name=f"Offline tester {index}",
                consent=True,
                challenge_nonce=challenge["nonce"],
                challenge_proof=solve_pow(challenge["nonce"], challenge["difficulty"]),
                ip="127.0.0.1",
            )
            self.identities.append((volunteer_id, secret))

        self.service.import_texts(
            [{"text": f"Матни офлайн барои сабти рақами {index}."} for index in range(1, 8)],
            approved=True,
        )
        with self.service.database.connect() as connection:
            first_text_id = connection.execute(
                "SELECT id FROM texts ORDER BY id LIMIT 1"
            ).fetchone()["id"]
        self.recording_id = str(uuid.uuid4())
        self.service.submit_recording(
            self.recording_id,
            first_text_id,
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
        *,
        method: str = "GET",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        headers = self.auth_headers(index) if index is not None else {}
        headers.update(extra_headers or {})
        request = urllib.request.Request(
            self.base + path,
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.read(), dict(response.headers.items())

    def test_recording_batch_returns_unique_prompts_in_one_request(self) -> None:
        status, raw, _ = self.request(
            "/api/v1/tasks/recording-batch?limit=5",
            index=1,
        )
        self.assertEqual(status, 200)
        tasks = json.loads(raw)["tasks"]
        self.assertEqual(len(tasks), 5)
        self.assertEqual(len({task["id"] for task in tasks}), 5)

        with self.assertRaises(urllib.error.HTTPError) as too_many:
            self.request("/api/v1/tasks/recording-batch?limit=21", index=1)
        self.assertEqual(too_many.exception.code, 400)

    def test_media_range_and_head_do_not_burn_full_download_budget(self) -> None:
        status, raw, _ = self.request("/api/v1/tasks/audio-review", index=1)
        self.assertEqual(status, 200)
        task = json.loads(raw)["task"]
        self.assertEqual(task["id"], self.recording_id)
        audio_path = task["audio_url"]

        status, body, headers = self.request(
            audio_path,
            extra_headers={"Range": "bytes=0-43"},
        )
        self.assertEqual(status, 206)
        self.assertEqual(len(body), 44)
        self.assertEqual(headers.get("Accept-Ranges"), "bytes")
        self.assertTrue(headers.get("Content-Range", "").startswith("bytes 0-43/"))

        head_status, head_body, head_headers = self.request(audio_path, method="HEAD")
        self.assertEqual(head_status, 200)
        self.assertEqual(head_body, b"")
        self.assertEqual(head_headers.get("Accept-Ranges"), "bytes")

        # Range and HEAD are one streaming playback's probes, so both full-download
        # uses remain available. Plain full GETs still obey the original use limit.
        self.assertEqual(self.request(audio_path)[0], 200)
        self.assertEqual(self.request(audio_path)[0], 200)
        with self.assertRaises(urllib.error.HTTPError) as exhausted:
            self.request(audio_path)
        self.assertEqual(exhausted.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
