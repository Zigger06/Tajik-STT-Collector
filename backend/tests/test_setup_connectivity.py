from __future__ import annotations

import unittest
from pathlib import Path

from collector.online_server import ANDROID_REGISTRATION_DIFFICULTY


ROOT = Path(__file__).resolve().parents[2]


class SetupConnectivityRegressionTest(unittest.TestCase):
    def test_first_registration_pow_is_phone_friendly(self) -> None:
        # 16 bits is ~8x less work than the old 19-bit challenge while the
        # registration rate limits remain the main anti-abuse boundary.
        self.assertEqual(ANDROID_REGISTRATION_DIFFICULTY, 16)

        server = (ROOT / "backend/server.py").read_text(encoding="utf-8")
        self.assertIn("serve_online_fast_registration", server)

    def test_server_config_has_fast_embedded_fallback(self) -> None:
        config = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ServerConfig.kt"
        ).read_text(encoding="utf-8")
        public_config = (ROOT / "docs/app-config.json").read_text(encoding="utf-8")

        self.assertIn('BUILT_IN_SERVER_URL', config)
        self.assertIn('https://mlscientist06.tailbc3525.ts.net', config)
        self.assertIn('callTimeout(900, TimeUnit.MILLISECONDS)', config)
        self.assertNotIn('connectTimeout(8, TimeUnit.SECONDS)', config)
        self.assertIn('https://mlscientist06.tailbc3525.ts.net', public_config)

    def test_stale_cached_url_cannot_shadow_current_deployment(self) -> None:
        config = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ServerConfig.kt"
        ).read_text(encoding="utf-8")

        # This exact early return caused upgraded phones to stay pinned forever to
        # an obsolete https:// Funnel address stored in SharedPreferences.
        self.assertNotIn("if (isValid(cached)) return@withContext cached", config)
        self.assertIn("isValid(remoteUrl) -> remoteUrl", config)
        self.assertIn("isValid(BUILT_IN_SERVER_URL) -> BUILT_IN_SERVER_URL", config)
        self.assertIn("isValid(cached) -> cached", config)
        self.assertLess(
            config.index("isValid(remoteUrl) -> remoteUrl"),
            config.index("isValid(cached) -> cached"),
        )
        self.assertLess(
            config.index("isValid(BUILT_IN_SERVER_URL) -> BUILT_IN_SERVER_URL"),
            config.index("isValid(cached) -> cached"),
        )

    def test_setup_transport_error_is_short_and_nontechnical(self) -> None:
        errors = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/ui/UiError.kt"
        ).read_text(encoding="utf-8")
        self.assertIn('"Сервер Дастнорас аст"', errors)
        self.assertNotIn("Unable to resolve host", errors)
        self.assertNotIn("No address associated with hostname", errors)


if __name__ == "__main__":
    unittest.main()
