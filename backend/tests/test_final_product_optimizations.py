from __future__ import annotations

import io
import tempfile
import unittest
import uuid
import wave
from pathlib import Path

from collector.database import Database
from collector.service import CollectorError
from collector.storage_aware_service import StorageAwareCollectorService


ROOT = Path(__file__).resolve().parents[2]


def make_wav(duration_ms: int = 600, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    frames = b"\x00\x00" * (sample_rate * duration_ms // 1000)
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return buffer.getvalue()


class FinalProductBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = StorageAwareCollectorService(
            Database(root / "collector.db"),
            root / "audio",
        )
        self.volunteer_id = str(uuid.uuid4())
        self.service.register_volunteer(
            self.volunteer_id,
            "Final tester",
            consent=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_my_data_is_paginated_ten_at_a_time(self) -> None:
        self.service.import_texts(
            [{"text": f"Ҷумлаи санҷишии рақами {index}."} for index in range(12)],
            approved=True,
        )
        with self.service.database.connect() as connection:
            text_ids = [
                int(row["id"])
                for row in connection.execute("SELECT id FROM texts ORDER BY id")
            ]

        for text_id in text_ids:
            self.service.submit_recording(
                str(uuid.uuid4()),
                text_id,
                self.volunteer_id,
                duration_ms=600,
                sample_rate=16000,
                audio=make_wav(),
            )

        first = self.service.volunteer_recordings_page(self.volunteer_id, 10, 0)
        second = self.service.volunteer_recordings_page(self.volunteer_id, 10, 10)
        self.assertEqual(first["total"], 12)
        self.assertEqual(len(first["recordings"]), 10)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_offset"], 10)
        self.assertEqual(len(second["recordings"]), 2)
        self.assertFalse(second["has_more"])
        self.assertEqual(second["next_offset"], 12)

    def test_volunteer_text_batch_stores_only_short_independent_tasks(self) -> None:
        result = self.service.submit_text_batch(
            self.volunteer_id,
            [
                "Ин ҷумлаи якум аст.",
                "Ин ҷумлаи дуюм аст!",
                "Ин ҷумлаи сеюм аст?",
            ],
            source="Санҷиш",
        )
        self.assertEqual(result["inserted"], 3)
        with self.service.database.connect() as connection:
            rows = connection.execute(
                "SELECT content, source, status FROM texts ORDER BY id"
            ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(len(row["content"]) <= 300 for row in rows))
        self.assertTrue(all(row["source"] == "Санҷиш" for row in rows))
        self.assertTrue(all(row["status"] == "pending_review" for row in rows))

        with self.assertRaises(CollectorError):
            self.service.submit_text(
                self.volunteer_id,
                "а" * 301,
            )
        with self.assertRaises(CollectorError):
            self.service.submit_text_batch(
                self.volunteer_id,
                ["а" * 300 for _ in range(17)],
            )

    def test_name_change_updates_same_identity(self) -> None:
        before = self.service.stats()["volunteers"]
        updated = self.service.register_volunteer(
            self.volunteer_id,
            "Дигар ном",
            region="Душанбе",
            consent=True,
        )
        after = self.service.stats()["volunteers"]
        self.assertEqual(before, after)
        self.assertEqual(updated["id"], self.volunteer_id)
        self.assertEqual(updated["display_name"], "Дигар ном")

    def test_pagination_index_exists(self) -> None:
        with self.service.database.connect() as connection:
            indexes = {
                row["name"] for row in connection.execute("PRAGMA index_list(recordings)")
            }
        self.assertIn("idx_recordings_volunteer_created", indexes)


class FinalProductAndroidContractTest(unittest.TestCase):
    def test_audio_review_is_fetched_once_then_played_from_ram(self) -> None:
        api = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ApiClient.kt"
        ).read_text(encoding="utf-8")
        ui = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/CollectorApp.kt"
        ).read_text(encoding="utf-8")
        data_source = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/audio/ByteArrayMediaDataSource.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("suspend fun reviewAudio", api)
        self.assertIn("MAX_AUDIO_CACHE_BYTES", api)
        self.assertIn("audioBytes = api.reviewAudio(next.id, next.audioUrl)", ui)
        self.assertIn("setDataSource(ByteArrayMediaDataSource(bytes))", ui)
        self.assertNotIn("setDataSource(current.audioUrl)", ui)
        self.assertIn("class ByteArrayMediaDataSource", data_source)

    def test_my_data_loads_ten_cards_and_reuses_audio_for_download(self) -> None:
        my_data = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/MyDataScreen.kt"
        ).read_text(encoding="utf-8")
        api = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ApiClient.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("MY_DATA_PAGE_SIZE = 10", my_data)
        self.assertIn('Text("Дигар сабтҳо")', my_data)
        self.assertIn("offset = nextOffset", my_data)
        self.assertIn("ApiClient(settings).ownRecordingAudio(recording.id)", my_data)
        self.assertIn("ApiClient(settings).ownRecordingAudio(recordingId)", my_data)
        self.assertIn('snackbar.showSnackbar("Сабт шуд")', my_data)
        self.assertNotIn("Боргирии ҳамаи сабтҳо", my_data)
        self.assertIn("suspend fun ownRecordingAudio", api)
        self.assertIn("output.write(ownRecordingAudio(recordingId))", api)

    def test_text_entry_has_single_and_batch_modes_without_silent_truncation(self) -> None:
        ui = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/CollectorApp.kt"
        ).read_text(encoding="utf-8")
        api = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ApiClient.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("TextInputMode.SINGLE", ui)
        self.assertIn("TextInputMode.MULTI", ui)
        self.assertIn("300 else 5000", ui)
        self.assertIn("splitVolunteerSentences", ui)
        self.assertIn("sentences.size <= 50", ui)
        self.assertNotIn("result.take(50)", ui)
        self.assertIn("ApiClient(settings).submitTexts(sentences", ui)
        self.assertIn('jsonRequest("/api/v1/texts/batch"', api)
        self.assertIn("Тағйири ном ҳисоби нав намесозад", ui)


if __name__ == "__main__":
    unittest.main()
