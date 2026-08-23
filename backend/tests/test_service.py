from __future__ import annotations

import io
import json
import tempfile
import unittest
import uuid
import wave
from pathlib import Path

from collector.database import Database
from collector.service import CollectorService, ConflictError


def make_wav(duration_ms: int = 1000, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    frames = b"\x00\x00" * (sample_rate * duration_ms // 1000)
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return buffer.getvalue()


class CollectorServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = CollectorService(Database(root / "collector.db"), root / "audio")
        self.volunteers = [str(uuid.uuid4()) for _ in range(4)]
        for index, volunteer_id in enumerate(self.volunteers):
            self.service.register_volunteer(
                volunteer_id,
                f"Volunteer {index}",
                region="Dushanbe",
                consent=True,
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_full_review_record_and_export_flow(self) -> None:
        imported = self.service.import_texts(
            [{"text": "Имрӯз ҳаво хеле хуб аст.", "source": "unit-test"}]
        )
        self.assertEqual(imported["inserted"], 1)

        task = self.service.get_text_review_task(self.volunteers[0])
        self.assertIsNotNone(task)
        text_id = task["id"]
        first = self.service.submit_text_review(text_id, self.volunteers[0], "correct")
        self.assertEqual(first["status"], "pending_review")
        second = self.service.submit_text_review(text_id, self.volunteers[1], "correct")
        self.assertEqual(second["status"], "approved")

        recording_task = self.service.get_recording_task(self.volunteers[0])
        self.assertEqual(recording_task["id"], text_id)
        recording_id = str(uuid.uuid4())
        submitted = self.service.submit_recording(
            recording_id,
            text_id,
            self.volunteers[0],
            duration_ms=1000,
            sample_rate=16000,
            audio=make_wav(),
        )
        self.assertEqual(submitted["status"], "pending")

        stats = self.service.volunteer_stats(self.volunteers[0])
        self.assertEqual(stats["submitted"], 1)
        self.assertEqual(stats["pending_review"], 1)

        audio_task = self.service.get_audio_review_task(self.volunteers[1])
        self.assertEqual(audio_task["id"], recording_id)
        self.assertEqual(audio_task["audio_url"], f"/media/{recording_id}.wav")
        self.assertNotIn("key", audio_task["audio_url"])

        with self.assertRaises(ConflictError):
            self.service.submit_audio_review(
                recording_id, self.volunteers[0], "approve"
            )
        review_one = self.service.submit_audio_review(
            recording_id, self.volunteers[1], "approve"
        )
        self.assertEqual(review_one["status"], "pending")
        review_two = self.service.submit_audio_review(
            recording_id, self.volunteers[2], "approve"
        )
        self.assertEqual(review_two["status"], "approved")
        stats = self.service.volunteer_stats(self.volunteers[0])
        self.assertEqual(stats["submitted"], 1)
        self.assertEqual(stats["approved"], 1)
        self.assertEqual(stats["pending_review"], 0)

        output = Path(self.temp.name) / "export"
        exported = self.service.export_dataset(output)
        self.assertEqual(exported["exported"], 1)
        manifest = [json.loads(line) for line in (output / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(manifest[0]["text"], "Имрӯз ҳаво хеле хуб аст.")
        self.assertTrue((output / manifest[0]["audio"]).exists())
        self.assertTrue((output / "audio" / f"{recording_id}.txt").exists())

    def test_correction_waits_for_admin(self) -> None:
        self.service.import_texts([{"text": "Матни хатодор аст."}])
        task = self.service.get_text_review_task(self.volunteers[0])
        result = self.service.submit_text_review(
            task["id"], self.volunteers[0], "correction", "Матни дуруст аст."
        )
        self.assertEqual(result["status"], "needs_admin")
        pending = self.service.list_needs_admin()
        self.assertEqual(pending[0]["corrections"], "Матни дуруст аст.")
        resolved = self.service.resolve_text(
            task["id"], "approve", "Матни дуруст аст."
        )
        self.assertEqual(resolved["status"], "approved")

    def test_recording_task_excludes_texts_staged_on_phone(self) -> None:
        self.service.import_texts(
            [
                {"text": "Матни якум барои сабти гурӯҳӣ."},
                {"text": "Матни дуюм барои сабти гурӯҳӣ."},
            ],
            approved=True,
        )
        first = self.service.get_recording_task(self.volunteers[0])
        second = self.service.get_recording_task(
            self.volunteers[0],
            excluded_text_ids=[first["id"]],
        )
        self.assertIsNotNone(second)
        self.assertNotEqual(second["id"], first["id"])


if __name__ == "__main__":
    unittest.main()
