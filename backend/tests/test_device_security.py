from __future__ import annotations

import hashlib
import secrets
import tempfile
import unittest
import uuid
from pathlib import Path

from collector.database import Database
from collector.security import (
    AuthenticationError,
    DeviceSecurity,
    RateLimitError,
    RateRule,
)
from collector.service import CollectorService


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


class DeviceSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = CollectorService(Database(root / "collector.db"), root / "audio")
        self.security = DeviceSecurity(self.service, challenge_difficulty=4)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def register(self, volunteer_id: str, secret: str, name: str = "Security tester") -> dict:
        challenge = self.security.issue_registration_challenge(volunteer_id, secret, "127.0.0.1")
        return self.security.register_volunteer(
            volunteer_id=volunteer_id,
            secret=secret,
            display_name=name,
            consent=True,
            challenge_nonce=challenge["nonce"],
            challenge_proof=solve_pow(challenge["nonce"], challenge["difficulty"]),
            ip="127.0.0.1",
        )

    def test_secret_is_hashed_and_repeat_registration_uses_same_credential(self) -> None:
        volunteer_id = str(uuid.uuid4())
        secret = secrets.token_urlsafe(32)
        first = self.register(volunteer_id, secret)
        self.assertEqual(first["id"], volunteer_id)

        with self.service.database.connect() as connection:
            row = connection.execute(
                "SELECT secret_salt, secret_hash FROM device_credentials WHERE volunteer_id = ?",
                (volunteer_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["secret_hash"], secret)
        self.assertNotIn(secret, row["secret_salt"])

        repeated = self.security.register_volunteer(
            volunteer_id=volunteer_id,
            secret=secret,
            display_name="Security tester",
            region="Dushanbe",
            consent=True,
            ip="127.0.0.1",
        )
        self.assertEqual(repeated["region"], "Dushanbe")
        self.assertEqual(
            self.security.authenticate(volunteer_id, secret, "stats", "127.0.0.1"),
            volunteer_id,
        )

    def test_missing_wrong_and_other_volunteer_credentials_are_rejected(self) -> None:
        first_id = str(uuid.uuid4())
        second_id = str(uuid.uuid4())
        first_secret = secrets.token_urlsafe(32)
        second_secret = secrets.token_urlsafe(32)
        self.register(first_id, first_secret, "First tester")
        self.register(second_id, second_secret, "Second tester")

        with self.assertRaises(AuthenticationError):
            self.security.authenticate(first_id, "", "stats", "127.0.0.1")
        with self.assertRaises(AuthenticationError):
            self.security.authenticate(first_id, secrets.token_urlsafe(32), "stats", "127.0.0.1")
        with self.assertRaises(AuthenticationError):
            self.security.authenticate(first_id, second_secret, "stats", "127.0.0.1")

    def test_legacy_volunteer_can_claim_same_uuid_with_matching_profile(self) -> None:
        volunteer_id = str(uuid.uuid4())
        self.service.register_volunteer(
            volunteer_id,
            "Legacy tester",
            region="Dushanbe",
            consent=True,
        )
        secret = secrets.token_urlsafe(32)
        result = self.register(volunteer_id, secret, "Legacy tester")
        self.assertEqual(result["id"], volunteer_id)
        self.assertEqual(
            self.security.authenticate(volunteer_id, secret, "task", "127.0.0.1"),
            volunteer_id,
        )

    def test_device_rate_limit_returns_429_error_type(self) -> None:
        rules = {
            "stats": {
                "device": (RateRule(2, 60),),
                "ip": (),
            }
        }
        security = DeviceSecurity(
            self.service,
            challenge_difficulty=4,
            rate_rules=rules,
        )
        volunteer_id = str(uuid.uuid4())
        secret = secrets.token_urlsafe(32)
        challenge = security.issue_registration_challenge(volunteer_id, secret, "127.0.0.1")
        security.register_volunteer(
            volunteer_id=volunteer_id,
            secret=secret,
            display_name="Rate tester",
            consent=True,
            challenge_nonce=challenge["nonce"],
            challenge_proof=solve_pow(challenge["nonce"], challenge["difficulty"]),
            ip="127.0.0.1",
        )
        security.authenticate(volunteer_id, secret, "stats", "127.0.0.1")
        security.authenticate(volunteer_id, secret, "stats", "127.0.0.1")
        with self.assertRaises(RateLimitError) as limited:
            security.authenticate(volunteer_id, secret, "stats", "127.0.0.1")
        self.assertGreaterEqual(limited.exception.retry_after, 1)


if __name__ == "__main__":
    unittest.main()
