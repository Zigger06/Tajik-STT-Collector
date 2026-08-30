from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from collector.database import Database
from collector.storage_aware_service import (
    StorageAwareCollectorService,
    VOLUNTEER_TEXT_HOURLY_LIMIT,
    VolunteerTextRateLimitError,
)


ROOT = Path(__file__).resolve().parents[2]


class PersistentVolunteerTextQuotaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "collector.db")
        self.service = StorageAwareCollectorService(self.database, self.root / "audio")
        self.volunteer_id = str(uuid.uuid4())
        self.service.register_volunteer(
            self.volunteer_id,
            "Quota tester",
            consent=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def sentences(start: int, count: int) -> list[str]:
        return [f"Ҷумлаи нави санҷишӣ рақами {index}." for index in range(start, start + count)]

    def test_batch_counts_actual_sentences_and_survives_server_restart(self) -> None:
        self.assertEqual(VOLUNTEER_TEXT_HOURLY_LIMIT, 60)
        first = self.service.submit_text_batch(
            self.volunteer_id,
            self.sentences(0, 50),
        )
        second = self.service.submit_text_batch(
            self.volunteer_id,
            self.sentences(50, 10),
        )
        self.assertEqual(first["inserted"], 50)
        self.assertEqual(second["inserted"], 10)

        with self.assertRaises(VolunteerTextRateLimitError):
            self.service.submit_text(
                self.volunteer_id,
                "Ин ҷумла бояд аз лимити соатона гузарад.",
            )

        restarted = StorageAwareCollectorService(self.database, self.root / "audio")
        with self.assertRaises(VolunteerTextRateLimitError):
            restarted.submit_text_batch(
                self.volunteer_id,
                ["Ин ҷумла баъди бозоғозии сервер ҳам бояд маҳдуд шавад."],
            )

    def test_duplicates_do_not_consume_semantic_quota(self) -> None:
        original = self.sentences(100, 20)
        result = self.service.submit_text_batch(self.volunteer_id, original)
        duplicate = self.service.submit_text_batch(self.volunteer_id, original)
        self.assertEqual(result["inserted"], 20)
        self.assertEqual(duplicate["inserted"], 0)
        self.assertEqual(duplicate["duplicates"], 20)

        another = self.service.submit_text_batch(
            self.volunteer_id,
            self.sentences(200, 40),
        )
        self.assertEqual(another["inserted"], 40)

    def test_quota_lookup_has_dedicated_index(self) -> None:
        with self.database.connect() as connection:
            indexes = {
                row["name"] for row in connection.execute("PRAGMA index_list(texts)")
            }
        self.assertIn("idx_texts_submitter_created", indexes)


class SnakeGameContractTest(unittest.TestCase):
    def test_snake_is_native_offline_and_has_requested_launcher(self) -> None:
        game = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/SnakeGameScreen.kt"
        ).read_text(encoding="utf-8")
        activity = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/MainActivity.kt"
        ).read_text(encoding="utf-8")
        collector = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/CollectorApp.kt"
        ).read_text(encoding="utf-8")

        self.assertIn('Text("𓆙 Бозӣ")', collector)
        self.assertIn('"𓆙 Бозӣ"', game)
        self.assertIn("onGame: () -> Unit", collector)
        self.assertIn("onGame = { showSnakeGame = true }", activity)
        self.assertIn("SnakeGameScreen", activity)
        self.assertIn("detectDragGestures", game)
        self.assertIn("SNAKE_GRID_SIZE", game)
        self.assertIn("best_score", game)
        self.assertIn("Icons.Default.Pause", game)
        self.assertIn("Icons.Default.Refresh", game)
        self.assertNotIn("SnakeControls", game)
        self.assertNotIn('Text("↑")', game)
        self.assertNotIn('Text("↓")', game)
        self.assertNotIn('Text("←")', game)
        self.assertNotIn('Text("→")', game)
        self.assertNotIn("ApiClient", game)
        self.assertNotIn("UploadWorker", game)
        self.assertNotIn("http://", game)
        self.assertNotIn("https://", game)


if __name__ == "__main__":
    unittest.main()
