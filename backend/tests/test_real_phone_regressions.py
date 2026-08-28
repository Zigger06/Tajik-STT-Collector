from __future__ import annotations

import hashlib
import io
import secrets
import tempfile
import unittest
import uuid
import wave
from pathlib import Path

from collector.database import Database
from collector.security import DeviceSecurity, RateLimitError, RateRule
from collector.storage_aware_service import StorageAwareCollectorService


ROOT = Path(__file__).resolve().parents[2]


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


def make_wav(duration_ms: int = 800, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    frames = b"\x00\x00" * (sample_rate * duration_ms // 1000)
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return buffer.getvalue()


class RealPhoneBackendRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = StorageAwareCollectorService(
            Database(root / "collector.db"),
            root / "audio",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_audio_review_skips_stale_database_row_when_wav_is_missing(self) -> None:
        owner_id = str(uuid.uuid4())
        reviewer_id = str(uuid.uuid4())
        self.service.register_volunteer(owner_id, "Owner tester", consent=True)
        self.service.register_volunteer(reviewer_id, "Reviewer tester", consent=True)
        self.service.import_texts(
            [
                {"text": "Матни якум барои санҷиши файли гумшуда."},
                {"text": "Матни дуюм барои санҷиши файли мавҷуда."},
            ],
            approved=True,
        )
        with self.service.database.connect() as connection:
            text_ids = [
                row["id"]
                for row in connection.execute("SELECT id FROM texts ORDER BY id").fetchall()
            ]

        missing_id = str(uuid.uuid4())
        valid_id = str(uuid.uuid4())
        self.service.submit_recording(
            missing_id,
            text_ids[0],
            owner_id,
            duration_ms=800,
            sample_rate=16000,
            audio=make_wav(),
        )
        self.service.submit_recording(
            valid_id,
            text_ids[1],
            owner_id,
            duration_ms=800,
            sample_rate=16000,
            audio=make_wav(),
        )
        with self.service.database.connect() as connection:
            connection.execute(
                "UPDATE recordings SET created_at = ? WHERE id = ?",
                ("2020-01-01T00:00:00.000Z", missing_id),
            )
            connection.execute(
                "UPDATE recordings SET created_at = ? WHERE id = ?",
                ("2021-01-01T00:00:00.000Z", valid_id),
            )
            missing_path = Path(
                connection.execute(
                    "SELECT file_path FROM recordings WHERE id = ?", (missing_id,)
                ).fetchone()["file_path"]
            )
        missing_path.unlink()

        task = self.service.get_audio_review_task(reviewer_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["id"], valid_id)

    def test_authenticated_refreshes_do_not_consume_new_device_registration_budget(self) -> None:
        rules = {
            "registration": {
                "device": (RateRule(1, 3600),),
                "ip": (RateRule(1, 3600),),
            }
        }
        security = DeviceSecurity(
            self.service,
            challenge_difficulty=4,
            rate_rules=rules,
        )
        ip = "203.0.113.25"
        volunteer_id = str(uuid.uuid4())
        secret = secrets.token_urlsafe(32)
        challenge = security.issue_registration_challenge(volunteer_id, secret, ip)
        security.register_volunteer(
            volunteer_id=volunteer_id,
            secret=secret,
            display_name="Rate-safe tester",
            consent=True,
            challenge_nonce=challenge["nonce"],
            challenge_proof=solve_pow(challenge["nonce"], challenge["difficulty"]),
            ip=ip,
        )

        # These are authenticated profile refreshes, not new identities. They must
        # remain usable even after the strict one-new-registration budget is spent.
        for _ in range(10):
            refreshed = security.register_volunteer(
                volunteer_id=volunteer_id,
                secret=secret,
                display_name="Rate-safe tester",
                consent=True,
                ip=ip,
            )
            self.assertEqual(refreshed["id"], volunteer_id)

        # Anti-Sybil protection is still active for a genuinely new credential.
        other_id = str(uuid.uuid4())
        other_secret = secrets.token_urlsafe(32)
        other_challenge = security.issue_registration_challenge(other_id, other_secret, ip)
        with self.assertRaises(RateLimitError):
            security.register_volunteer(
                volunteer_id=other_id,
                secret=other_secret,
                display_name="Another tester",
                consent=True,
                challenge_nonce=other_challenge["nonce"],
                challenge_proof=solve_pow(
                    other_challenge["nonce"], other_challenge["difficulty"]
                ),
                ip=ip,
            )


class RealPhoneAndroidContractTest(unittest.TestCase):
    def test_queue_stats_cache_and_prompt_consumption_contracts(self) -> None:
        local_store = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/data/LocalStore.kt"
        ).read_text(encoding="utf-8")
        worker = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/data/UploadWorker.kt"
        ).read_text(encoding="utf-8")
        api = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ApiClient.kt"
        ).read_text(encoding="utf-8")
        ui = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/CollectorApp.kt"
        ).read_text(encoding="utf-8")

        revoked_block = local_store.split("fun markParticipationRevoked()", 1)[1].split(
            "fun markParticipationResumed()", 1
        )[0]
        self.assertNotIn("clearPendingRecordings()", revoked_block)
        self.assertIn("fun cachedVolunteerStats()", local_store)
        self.assertIn("fun saveVolunteerStats", local_store)
        self.assertNotIn("api.registerVolunteer()", worker)
        self.assertIn("store.saveVolunteerStats(api.volunteerStats())", worker)
        self.assertIn("fun discardRecordingTask", api)
        self.assertIn(
            "ApiClient.discardRecordingTask(settings.volunteerId, currentTask.id)",
            ui,
        )
        self.assertIn("delay(400)", ui)
        self.assertIn("delay(60_000)", ui)
        self.assertNotIn("LaunchedEffect(screen, pendingCount)", ui)

    def test_my_data_theme_layout_and_safe_error_contracts(self) -> None:
        activity = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/MainActivity.kt"
        ).read_text(encoding="utf-8")
        my_data = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/MyDataScreen.kt"
        ).read_text(encoding="utf-8")
        errors = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/UiError.kt"
        ).read_text(encoding="utf-8")

        self.assertIn(".background(MaterialTheme.colorScheme.background)", activity)
        self.assertIn(".navigationBarsPadding()", activity)
        self.assertIn("Icons.Default.DarkMode", activity)
        self.assertIn("Icons.Default.LightMode", activity)
        self.assertNotIn('Text("Мавзӯи торик", modifier', activity)

        self.assertIn('Text("Нусхаи маҳаллӣ"', my_data)
        self.assertIn("Icons.Default.Info", my_data)
        self.assertIn("showLocalCopyInfo", my_data)
        self.assertIn(
            "Пас аз фиристодани сабти овоз, нусха дар телефон нигоҳ дошта мешавад.",
            my_data,
        )
        self.assertIn("ButtonDefaults.buttonColors", my_data)
        self.assertIn("errorContainer", my_data)
        self.assertIn("userFacingError", my_data)
        self.assertIn("UnknownHostException", errors)
        self.assertIn("ApiException", errors)
        self.assertNotIn("Unable to resolve host", my_data)


if __name__ == "__main__":
    unittest.main()
