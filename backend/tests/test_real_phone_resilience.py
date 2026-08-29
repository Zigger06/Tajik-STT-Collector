from __future__ import annotations

import unittest
from pathlib import Path

from collector.online_server import ONLINE_RATE_RULES


ROOT = Path(__file__).resolve().parents[2]


class RealPhoneResilienceRegressionTest(unittest.TestCase):
    def test_online_upload_budget_allows_full_recording_sessions(self) -> None:
        device_rules = ONLINE_RATE_RULES["upload"]["device"]
        self.assertTrue(any(rule.limit >= 120 and rule.window_seconds <= 600 for rule in device_rules))
        self.assertTrue(any(rule.limit >= 600 and rule.window_seconds == 3600 for rule in device_rules))

    def test_upload_worker_retries_server_outage_without_manual_refresh(self) -> None:
        worker = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/data/UploadWorker.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("BackoffPolicy.LINEAR", worker)
        self.assertIn("15, TimeUnit.SECONDS", worker)
        self.assertIn("Result.retry()", worker)

    def test_app_start_repairs_server_url_and_reschedules_pending_queue(self) -> None:
        main = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/MainActivity.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("ServerConfig.resolve(current.serverUrl)", main)
        self.assertIn("store.saveSettings(current)", main)
        self.assertIn("store.pendingRecordings().isNotEmpty()", main)
        self.assertIn("UploadWorker.schedule(applicationContext)", main)

    def test_audio_reader_stops_at_declared_content_length(self) -> None:
        api = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ApiClient.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("var remaining = expected", api)
        self.assertIn("while (remaining > 0)", api)
        self.assertIn("Audio response ended early", api)
        self.assertIn("cachedOwnRecordingAudio", api)

    def test_my_data_download_prefetches_then_saves_cache_only(self) -> None:
        screen = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/MyDataScreen.kt"
        ).read_text(encoding="utf-8")
        prefetch = screen.index("ApiClient(settings).ownRecordingAudio(recordingId)")
        launch = screen.index('saveRecordingLauncher.launch("$recordingId.wav")')
        self.assertLess(prefetch, launch)
        self.assertIn("cachedOwnRecordingAudio(recordingId)", screen)
        callback_start = screen.index("val saveRecordingLauncher")
        callback_end = screen.index("LaunchedEffect(Unit)", callback_start)
        callback = screen[callback_start:callback_end]
        self.assertNotIn("ownRecordingAudio(recordingId)", callback)


if __name__ == "__main__":
    unittest.main()
