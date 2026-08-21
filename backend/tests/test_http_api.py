from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

from collector.database import Database
from collector.http_api import make_handler
from collector.service import CollectorService


class HttpApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.admin = root / "admin.html"
        self.admin.write_text("<html>ok</html>", encoding="utf-8")
        self.service = CollectorService(Database(root / "collector.db"), root / "audio")
        handler = make_handler(self.service, "test-key", self.admin)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path: str, method: str = "GET", body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "X-Project-Key": "test-key",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_health_auth_registration_import_and_task(self) -> None:
        with urllib.request.urlopen(self.base + "/health", timeout=3) as response:
            self.assertTrue(json.loads(response.read())["ok"])

        with self.assertRaises(urllib.error.HTTPError) as unauthorized:
            urllib.request.urlopen(self.base + "/api/v1/stats", timeout=3)
        self.assertEqual(unauthorized.exception.code, 401)

        imported = self.request(
            "/api/v1/admin/texts/import",
            method="POST",
            body={"texts": ["Ин як матни санҷишӣ аст."], "approved": True},
        )
        self.assertEqual(imported["inserted"], 1)

        volunteer_id = str(uuid.uuid4())
        registered = self.request(
            "/api/v1/volunteers",
            method="POST",
            body={
                "id": volunteer_id,
                "display_name": "HTTP tester",
                "region": "Dushanbe",
                "consent": True,
            },
        )
        self.assertEqual(registered["id"], volunteer_id)

        task = self.request(f"/api/v1/tasks/recording?volunteer_id={volunteer_id}")
        self.assertEqual(task["task"]["content"], "Ин як матни санҷишӣ аст.")


if __name__ == "__main__":
    unittest.main()
