from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
TOOLS = "{http://schemas.android.com/tools}"


class RepositorySecurityConfigTest(unittest.TestCase):
    def test_release_defaults_to_https_and_debug_explicitly_allows_lan_http(self) -> None:
        main_manifest = ET.parse(
            ROOT / "android/app/src/main/AndroidManifest.xml"
        ).getroot()
        main_application = main_manifest.find("application")
        self.assertIsNotNone(main_application)
        self.assertEqual(main_application.attrib[f"{ANDROID}usesCleartextTraffic"], "false")

        main_network = ET.parse(
            ROOT / "android/app/src/main/res/xml/network_security_config.xml"
        ).getroot()
        self.assertEqual(main_network.find("base-config").attrib["cleartextTrafficPermitted"], "false")

        debug_manifest = ET.parse(
            ROOT / "android/app/src/debug/AndroidManifest.xml"
        ).getroot()
        debug_application = debug_manifest.find("application")
        self.assertIsNotNone(debug_application)
        self.assertEqual(debug_application.attrib[f"{ANDROID}usesCleartextTraffic"], "true")
        self.assertIn(
            "android:usesCleartextTraffic",
            debug_application.attrib[f"{TOOLS}replace"],
        )

        debug_network = ET.parse(
            ROOT / "android/app/src/debug/res/xml/network_security_config.xml"
        ).getroot()
        self.assertEqual(debug_network.find("base-config").attrib["cleartextTrafficPermitted"], "true")

    def test_release_workflow_requires_signing_secrets_and_release_apk(self) -> None:
        workflow = (ROOT / ".github/workflows/publish-apk.yml").read_text(encoding="utf-8")
        self.assertIn("verifyReleaseSigningConfigured", workflow)
        self.assertIn("assembleRelease", workflow)
        self.assertIn("app/build/outputs/apk/release/app-release.apk", workflow)
        self.assertIn("apksigner", workflow)
        self.assertNotIn("app/build/outputs/apk/debug/app-debug.apk", workflow)
        for secret in (
            "ANDROID_RELEASE_KEYSTORE_BASE64",
            "ANDROID_RELEASE_STORE_PASSWORD",
            "ANDROID_RELEASE_KEY_ALIAS",
            "ANDROID_RELEASE_KEY_PASSWORD",
        ):
            self.assertIn(f"secrets.{secret}", workflow)

    def test_signing_material_is_ignored_by_git(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("*.jks", "*.keystore", "keystore.properties", "signing.properties"):
            self.assertIn(pattern, gitignore)

    def test_veracrypt_containers_and_generic_backup_wrapper_are_guarded(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("*.hc", gitignore)
        self.assertIn("*.tc", gitignore)

        wrapper = (ROOT / "backend/backup_to_encrypted_volume.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$EncryptedDestinationConfirmed", wrapper)
        self.assertIn("if (-not $EncryptedDestinationConfirmed)", wrapper)
        self.assertIn("--encrypted-destination-confirmed", wrapper)
        self.assertIn("BackupRoot must be on a different mounted volume", wrapper)
        self.assertNotIn("Remove-Item", wrapper)
        self.assertNotIn("Clear-Content", wrapper)

    def test_public_app_config_contains_only_https_server_url(self) -> None:
        config = json.loads((ROOT / "docs/app-config.json").read_text(encoding="utf-8"))
        self.assertEqual(set(config), {"server_url"})
        self.assertTrue(config["server_url"].startswith("https://"))
        self.assertNotIn("tajik-stt-local", json.dumps(config))

    def test_android_uses_bearer_credential_not_volunteer_id_in_urls_or_bodies(self) -> None:
        api = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/network/ApiClient.kt"
        ).read_text(encoding="utf-8")
        local_store = (
            ROOT
            / "android/app/src/main/java/com/zigger06/tajiksttcollector/data/LocalStore.kt"
        ).read_text(encoding="utf-8")

        self.assertIn('header("Authorization", "Bearer ${settings.deviceSecret}")', api)
        self.assertIn('header("X-Volunteer-Id", settings.volunteerId)', api)
        self.assertNotIn('addQueryParameter("volunteer_id"', api)
        self.assertNotIn('.put("volunteer_id"', api)
        self.assertIn('preferences.getString("device_secret", null)', local_store)
        self.assertIn("DeviceCredential.generateSecret()", local_store)

    def test_backend_does_not_take_volunteer_identity_from_query_or_json(self) -> None:
        http_api = (ROOT / "backend/collector/http_api.py").read_text(encoding="utf-8")
        security = (ROOT / "backend/collector/security.py").read_text(encoding="utf-8")

        self.assertIn("_authenticated_volunteer", http_api)
        self.assertIn('self.headers.get("X-Volunteer-Id", "")', http_api)
        self.assertIn("_bearer_secret()", http_api)
        self.assertNotIn('self._required_query(query, "volunteer_id")', http_api)
        self.assertNotIn('body.get("volunteer_id"', http_api)
        self.assertIn("device_credentials", security)
        self.assertIn("secret_hash", security)
        self.assertNotIn("INSERT INTO device_credentials (volunteer_id, device_secret", security)


if __name__ == "__main__":
    unittest.main()
