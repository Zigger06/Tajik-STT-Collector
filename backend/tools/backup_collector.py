from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(
    database_path: str | Path,
    audio_dir: str | Path,
    output_root: str | Path,
    *,
    encrypted_destination_confirmed: bool,
) -> Path:
    if not encrypted_destination_confirmed:
        raise RuntimeError(
            "Refusing to create a production backup until the destination is confirmed encrypted."
        )

    database_path = Path(database_path).resolve()
    audio_dir = Path(audio_dir).resolve()
    output_root = Path(output_root).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {database_path}")
    if not audio_dir.is_dir():
        raise FileNotFoundError(f"Audio directory not found: {audio_dir}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = output_root / f"tajik-stt-backup-{timestamp}"
    suffix = 1
    while backup_dir.exists():
        backup_dir = output_root / f"tajik-stt-backup-{timestamp}-{suffix}"
        suffix += 1
    backup_audio = backup_dir / "audio"
    backup_audio.mkdir(parents=True, exist_ok=False)

    backup_db = backup_dir / "collector.db"
    source = sqlite3.connect(database_path, timeout=30)
    target = sqlite3.connect(backup_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    manifest: dict[str, object] = {
        "format": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_sha256": sha256_file(backup_db),
        "recordings": [],
    }

    snapshot = sqlite3.connect(backup_db)
    snapshot.row_factory = sqlite3.Row
    try:
        integrity = snapshot.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
        rows = snapshot.execute(
            "SELECT id, file_path, sha256 FROM recordings ORDER BY created_at, id"
        ).fetchall()
    finally:
        snapshot.close()

    recordings: list[dict[str, str]] = []
    for row in rows:
        recording_id = str(row["id"])
        source_path = Path(row["file_path"]).resolve()
        if source_path.parent != audio_dir:
            raise RuntimeError(
                f"Recording {recording_id} points outside configured audio directory"
            )
        if not source_path.is_file():
            raise FileNotFoundError(f"Recording file missing: {source_path}")
        actual_hash = sha256_file(source_path)
        stored_hash = str(row["sha256"] or "")
        if stored_hash and stored_hash != actual_hash:
            raise RuntimeError(f"SHA-256 mismatch before backup: {recording_id}")
        destination = backup_audio / f"{recording_id}.wav"
        shutil.copy2(source_path, destination)
        copied_hash = sha256_file(destination)
        if copied_hash != actual_hash:
            raise RuntimeError(f"SHA-256 mismatch after backup: {recording_id}")
        recordings.append(
            {
                "id": recording_id,
                "file": f"audio/{recording_id}.wav",
                "sha256": copied_hash,
            }
        )

    manifest["recordings"] = recordings
    (backup_dir / "backup-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # COMPLETE is deliberately written last. An interrupted backup remains
    # visibly incomplete and verify_backup.py will reject it.
    (backup_dir / "COMPLETE").write_text("complete\n", encoding="utf-8")
    return backup_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a consistent SQLite + WAV snapshot on an encrypted destination."
    )
    parser.add_argument("--db", required=True, help="Path to collector.db")
    parser.add_argument("--audio", required=True, help="Path to runtime/audio")
    parser.add_argument("--output", required=True, help="Existing encrypted backup root")
    parser.add_argument(
        "--encrypted-destination-confirmed",
        action="store_true",
        help="Required acknowledgement; use the PowerShell wrapper to verify BitLocker first.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    backup = create_backup(
        args.db,
        args.audio,
        args.output,
        encrypted_destination_confirmed=args.encrypted_destination_confirmed,
    )
    print(f"Backup complete: {backup}")


if __name__ == "__main__":
    main()
