from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from backup_collector import sha256_file


def verify_backup(backup_dir: str | Path) -> dict:
    backup_dir = Path(backup_dir).resolve()
    complete = backup_dir / "COMPLETE"
    manifest_path = backup_dir / "backup-manifest.json"
    database_path = backup_dir / "collector.db"
    if not complete.is_file():
        raise RuntimeError("Backup is incomplete: COMPLETE marker is missing")
    if not manifest_path.is_file() or not database_path.is_file():
        raise RuntimeError("Backup metadata or collector.db is missing")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_db_hash = str(manifest.get("database_sha256", ""))
    actual_db_hash = sha256_file(database_path)
    if not expected_db_hash or expected_db_hash != actual_db_hash:
        raise RuntimeError("collector.db SHA-256 verification failed")

    connection = sqlite3.connect(database_path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
        database_ids = {
            str(row[0])
            for row in connection.execute("SELECT id FROM recordings").fetchall()
        }
    finally:
        connection.close()

    manifest_ids: set[str] = set()
    for item in manifest.get("recordings", []):
        recording_id = str(item["id"])
        manifest_ids.add(recording_id)
        relative = Path(str(item["file"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe path in backup manifest: {relative}")
        path = (backup_dir / relative).resolve()
        if backup_dir not in path.parents:
            raise RuntimeError(f"Backup file escapes backup directory: {relative}")
        if not path.is_file():
            raise RuntimeError(f"Backup WAV is missing: {relative}")
        if sha256_file(path) != str(item["sha256"]):
            raise RuntimeError(f"Backup WAV SHA-256 verification failed: {recording_id}")

    if database_ids != manifest_ids:
        missing = sorted(database_ids - manifest_ids)
        extra = sorted(manifest_ids - database_ids)
        raise RuntimeError(
            f"Backup recording set mismatch; missing={missing[:5]} extra={extra[:5]}"
        )

    return {
        "ok": True,
        "recordings": len(manifest_ids),
        "database_sha256": actual_db_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a Tajik STT Collector backup snapshot.")
    parser.add_argument("backup_dir")
    args = parser.parse_args()
    result = verify_backup(args.backup_dir)
    print(f"Backup verified: {result['recordings']} recordings")
    print(f"Database SHA-256: {result['database_sha256']}")


if __name__ == "__main__":
    main()
