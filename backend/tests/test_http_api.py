from __future__ import annotations

import hashlib
import json
import secrets
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

from collector.database import Database
from collector.http_api import make_handler, serve_online
from collector.security import DeviceSecurity
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


class HttpApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.admin = root / "admin.html"
        self.admin.write_text("<html>ok</html>", encoding="utf-8")
        self.service = CollectorService(Database(root / "collector.db"), root / "audio")
        self.security = DeviceSecurity(self.service, challenge_difficulty=4)
        handler = make_handler(
            self.service,
            "test-key",
            self.admin,
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

    @staticmethod
    def auth_headers(volunteer_id: str, secret: str) -> dict[str, str]:
        return {
            "X-Volunteer-Id": volunteer_id,
            "Authorization": f"Bearer {secret}",
        }

    def request(
        self,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        headers: dict[str, str] | None = None,
        base: str | None = None,
    ) -> tuple[int, dict, object]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request_headers = dict(headers or {})
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            (base or self.base) + path,
            data=data,
            method=method,
            headers=request_headers,
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload, response.headers

    def register(
        self,
        volunteer_id: str,
        secret: str,
        name: str,
        base: str | None = None,
    ) -> dict:
        target = base or self.base
        auth = self.auth_headers(volunteer_id, secret)
        _, challenge, _ = self.request(
            "/api/v1/registration-challenge",
            headers=auth,
            base=target,
        )
        headers = {
            **auth,
            "X-Registration-Nonce": challenge["nonce"],
            "X-Registration-Proof": solve_pow(
                challenge["nonce"], challenge["difficulty"]
            ),
        }
        status, registered, _ = self.request(
            "/api/v1/volunteers",
            method="POST",
            body={
                "id": volunteer_id,
                "display_name": name,
                "region": "Dushanbe",
                "consent": True,
            },
            headers=headers,
            base=target,
        )
        self.assertEqual(status, 201)
        return registered

    def test_admin_device_auth_registration_and_task(self) -> None:
        status, health, headers = self.request("/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

        with self.assertRaises(urllib.error.HTTPError) as unauthorized:
            self.request("/api/v1/stats")
        self.assertEqual(unauthorized.exception.code, 401)

        status, imported, _ = self.request(
            "/api/v1/admin/texts/import",
            method="POST",
            body={"texts": ["Ин як матни санҷишӣ аст."], "approved": True},
            headers={"X-Project-Key": "test-key"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(imported["inserted"], 1)

        volunteer_id = str(uuid.uuid4())
        secret = secrets.token_urlsafe(32)
        auth = self.auth_headers(volunteer_id, secret)

        # A new anonymous identity cannot be created from a bare UUID/token pair;
        # it must first solve the one-time registration challenge.
        with self.assertRaises(urllib.error.HTTPError) as needs_proof:
            self.request(
                "/api/v1/volunteers",
                method="POST",
                body={
                    "id": volunteer_id,
                    "display_name": "HTTP tester",
                    "consent": True,
                },
                headers=auth,
            )
        self.assertEqual(needs_proof.exception.code, 428)

        registered = self.register(volunteer_id, secret, "HTTP tester")
        self.assertEqual(registered["id"], volunteer_id)

        # Re-registration with the already-bound credential is idempotent and
        # does not require another proof-of-work challenge.
        status, repeated, _ = self.request(
            "/api/v1/volunteers",
            method="POST",
            body={
                "id": volunteer_id,
                "display_name": "HTTP tester",
                "region": "Dushanbe",
                "consent": True,
            },
            headers=auth,
        )
        self.assertEqual(status, 201)
        self.assertEqual(repeated["id"], volunteer_id)

        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.request("/api/v1/volunteers/stats")
        self.assertEqual(missing.exception.code, 401)

        with self.assertRaises(urllib.error.HTTPError) as wrong:
            self.request(
                "/api/v1/volunteers/stats",
                headers=self.auth_headers(volunteer_id, secrets.token_urlsafe(32)),
            )
        self.assertEqual(wrong.exception.code, 401)

        second_id = str(uuid.uuid4())
        second_secret = secrets.token_urlsafe(32)
        self.register(second_id, second_secret, "Other tester")
        with self.assertRaises(urllib.error.HTTPError) as other_credential:
            self.request(
                "/api/v1/volunteers/stats",
                headers=self.auth_headers(volunteer_id, second_secret),
            )
        self.assertEqual(other_credential.exception.code, 401)

        _, task, _ = self.request("/api/v1/tasks/recording", headers=auth)
        self.assertEqual(task["task"]["content"], "Ин як матни санҷишӣ аст.")
        self.assertNotIn("volunteer_id=", "/api/v1/tasks/recording")
        _, excluded, _ = self.request(
            f"/api/v1/tasks/recording?exclude_text_ids={task['task']['id']}",
            headers=auth,
        )
        self.assertIsNone(excluded["task"])

    def test_public_handler_hides_admin_and_preserves_normal_volunteer_flow(self) -> None:
        public_security = DeviceSecurity(self.service, challenge_difficulty=4)
        handler = make_handler(
            self.service,
            "client-key",
            self.admin,
            allow_admin=False,
            security_context=public_security,
        )
        public_server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        public_thread = threading.Thread(target=public_server.serve_forever, daemon=True)
        public_thread.start()
        public_base = f"http://127.0.0.1:{public_server.server_port}"

        try:
            for path in ("/admin", "/api/v1/stats", "/api/v1/admin/texts/needs-admin"):
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    self.request(
                        path,
                        headers={"X-Project-Key": "client-key"},
                        base=public_base,
                    )
                self.assertEqual(missing.exception.code, 404)

            for path in ("/api/v1/admin/texts/import", "/api/v1/admin/texts/resolve"):
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    self.request(
                        path,
                        method="POST",
                        body={},
                        headers={"X-Project-Key": "client-key"},
                        base=public_base,
                    )
                self.assertEqual(missing.exception.code, 404)

            first_id = str(uuid.uuid4())
            first_secret = secrets.token_urlsafe(32)
            second_id = str(uuid.uuid4())
            second_secret = secrets.token_urlsafe(32)
            self.register(first_id, first_secret, "Public volunteer 1", base=public_base)
            self.register(second_id, second_secret, "Public volunteer 2", base=public_base)
            first_auth = self.auth_headers(first_id, first_secret)
            second_auth = self.auth_headers(second_id, second_secret)

            _, stats, _ = self.request(
                "/api/v1/volunteers/stats",
                headers=first_auth,
                base=public_base,
            )
            self.assertEqual(stats["submitted"], 0)

            status, submitted_text, _ = self.request(
                "/api/v1/texts",
                method="POST",
                body={"text": "Матни пешниҳодкардаи ихтиёрӣ.", "source": ""},
                headers=first_auth,
                base=public_base,
            )
            self.assertEqual(status, 201)
            self.assertEqual(submitted_text["status"], "pending_review")

            _, own_task, _ = self.request(
                "/api/v1/tasks/text-review",
                headers=first_auth,
                base=public_base,
            )
            self.assertIsNone(own_task["task"])

            with self.assertRaises(urllib.error.HTTPError) as self_review:
                self.request(
                    "/api/v1/text-reviews",
                    method="POST",
                    body={"text_id": submitted_text["id"], "verdict": "correct"},
                    headers=first_auth,
                    base=public_base,
                )
            self.assertEqual(self_review.exception.code, 409)

            _, review_task, _ = self.request(
                "/api/v1/tasks/text-review",
                headers=second_auth,
                base=public_base,
            )
            self.assertEqual(review_task["task"]["id"], submitted_text["id"])
            status, _, _ = self.request(
                "/api/v1/text-reviews",
                method="POST",
                body={"text_id": submitted_text["id"], "verdict": "correct"},
                headers=second_auth,
                base=public_base,
            )
            self.assertEqual(status, 201)

            _, audio_task, _ = self.request(
                "/api/v1/tasks/audio-review",
                headers=first_auth,
                base=public_base,
            )
            self.assertIsNone(audio_task["task"])
        finally:
            public_server.shutdown()
            public_server.server_close()
            public_thread.join(timeout=2)

    def test_online_admin_rejects_external_bind(self) -> None:
        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            serve_online(
                service=self.service,
                public_host="127.0.0.1",
                public_port=8000,
                admin_host="0.0.0.0",
                admin_port=8001,
                admin_key="test-key",
                admin_file=self.admin,
            )


if __name__ == "__main__":
    unittest.main()
