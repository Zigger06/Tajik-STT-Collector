from __future__ import annotations

import io
import tempfile
import unittest
import uuid
import wave
from pathlib import Path

from collector.database import Database
from collector.service import CollectorService
from tools.backup_collector import create_backup
from tools.verify_backup import verify_backup


def make_wav(duration_ms: int = 600, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    frames = b"\x00\x00" * (sample_rate * duration_ms // 1000)
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return buffer.getvalue()


class BackupToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.audio = self.runtime / "audio"
        self.service = CollectorService(Database(self.runtime / "collector.db"), self.audio)
        self.volunteer_id = str(uuid.uuid4())
        self.service.register_volunteer(
            self.volunteer_id,
            "Backup tester",
            consent=True,
        )
        self.service.import_texts(
            [{"text": "Матни санҷишӣ барои нусхаи эҳтиётӣ."}],
            approved=True,
        )
        with self.service.database.connect() as connection:
            text_id = connection.execute("SELECT id FROM texts LIMIT 1").fetchone()[0]
        self.recording_id = str(uuid.uuid4())
        self.service.submit_recording(
            self.recording_id,
            text_id,
            self.volunteer_id,
            duration_ms=600,
            sample_rate=16000,
            audio=make_wav(),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_backup_requires_encrypted_destination_acknowledgement(self) -> None:
        with self.assertRaises(RuntimeError):
            create_backup(
                self.runtime / "collector.db",
                self.audio,
                self.root / "backup-target",
                encrypted_destination_confirmed=False,
            )

    def test_sqlite_and_wav_backup_is_complete_and_verifiable(self) -> None:
        backup = create_backup(
            self.runtime / "collector.db",
            self.audio,
            self.root / "backup-target",
            encrypted_destination_confirmed=True,
        )
        self.assertTrue((backup / "COMPLETE").is_file())
        self.assertTrue((backup / "collector.db").is_file())
        self.assertTrue((backup / "audio" / f"{self.recording_id}.wav").is_file())
        result = verify_backup(backup)
        self.assertTrue(result["ok"])
        self.assertEqual(result["recordings"], 1)

    def test_verifier_rejects_tampered_backup(self) -> None:
        backup = create_backup(
            self.runtime / "collector.db",
            self.audio,
            self.root / "backup-target",
            encrypted_destination_confirmed=True,
        )
        wav = backup / "audio" / f"{self.recording_id}.wav"
        wav.write_bytes(wav.read_bytes() + b"tamper")
        with self.assertRaises(RuntimeError):
            verify_backup(backup)


if __name__ == "__main__":
    unittest.main()
