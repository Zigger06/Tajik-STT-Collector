from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Iterable

from .database import Database


class CollectorError(Exception):
    status_code = 400


class NotFoundError(CollectorError):
    status_code = 404


class ForbiddenError(CollectorError):
    status_code = 403


class ConflictError(CollectorError):
    status_code = 409


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def validate_uuid(value: str, field_name: str = "id") -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise CollectorError(f"{field_name} must be a valid UUID") from exc


class CollectorService:
    def __init__(
        self,
        database: Database,
        audio_dir: str | Path,
        required_reviews: int = 2,
    ):
        self.database = database
        self.audio_dir = Path(audio_dir).resolve()
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.required_reviews = required_reviews
        self.database.initialize()
        self._purge_delete_tombstones()

    def register_volunteer(
        self,
        volunteer_id: str,
        display_name: str,
        region: str = "",
        dialect: str = "",
        consent: bool = False,
    ) -> dict:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        display_name = normalize_text(display_name)
        if len(display_name) < 2:
            raise CollectorError("display_name is too short")
        if not consent:
            raise CollectorError("consent is required")

        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO volunteers (id, display_name, region, dialect, consent_active)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name,
                    region = excluded.region,
                    dialect = excluded.dialect
                """,
                (
                    volunteer_id,
                    display_name[:100],
                    normalize_text(region)[:100],
                    normalize_text(dialect)[:100],
                ),
            )
            row = connection.execute(
                """
                SELECT id, display_name, region, dialect, consent_active, revoked_at, created_at
                FROM volunteers WHERE id = ?
                """,
                (volunteer_id,),
            ).fetchone()
        return dict(row)

    def submit_text(
        self,
        volunteer_id: str,
        content: str,
        source: str = "",
    ) -> dict:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        content = normalize_text(content)
        if len(content) < 3:
            raise CollectorError("text is too short")
        if len(content) > 1000:
            raise CollectorError("text is too long")
        source = normalize_text(source)[:500]

        with self.database.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO texts
                        (content, normalized, source, submitted_by, status, required_recordings)
                    VALUES (?, ?, ?, ?, 'pending_review', 5)
                    """,
                    (content, content.casefold(), source, volunteer_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("text already exists") from exc
            text_id = cursor.lastrowid
        return {
            "id": text_id,
            "content": content,
            "source": source,
            "status": "pending_review",
        }

    def import_texts(
        self,
        items: Iterable[dict],
        default_source: str = "",
        approved: bool = False,
        required_recordings: int = 5,
    ) -> dict:
        if not 1 <= required_recordings <= 20:
            raise CollectorError("required_recordings must be between 1 and 20")
        status = "approved" if approved else "pending_review"
        inserted = 0
        duplicates = 0
        skipped = 0
        with self.database.connect() as connection:
            for item in items:
                content = normalize_text(str(item.get("text", "")))
                if len(content) < 3 or len(content) > 1000:
                    skipped += 1
                    continue
                source = normalize_text(str(item.get("source", default_source)))[:500]
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO texts
                        (content, normalized, source, status, required_recordings)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (content, content.casefold(), source, status, required_recordings),
                )
                if cursor.rowcount:
                    inserted += 1
                else:
                    duplicates += 1
        return {"inserted": inserted, "duplicates": duplicates, "skipped": skipped}

    def import_file(
        self,
        file_path: str | Path,
        source: str = "",
        approved: bool = False,
        required_recordings: int = 5,
    ) -> dict:
        path = Path(file_path)
        if not path.exists():
            raise NotFoundError(f"File not found: {path}")
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                items = list(csv.DictReader(handle))
        else:
            with path.open("r", encoding="utf-8-sig") as handle:
                items = [{"text": line, "source": source} for line in handle]
        return self.import_texts(items, source, approved, required_recordings)

    def get_recording_task(
        self,
        volunteer_id: str,
        excluded_text_ids: Iterable[int] = (),
    ) -> dict | None:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        excluded_ids = list(dict.fromkeys(int(value) for value in excluded_text_ids))[:100]
        exclusion_sql = ""
        parameters: list[object] = [volunteer_id]
        if excluded_ids:
            placeholders = ", ".join("?" for _ in excluded_ids)
            exclusion_sql = f"AND t.id NOT IN ({placeholders})"
            parameters.extend(excluded_ids)
        with self.database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT
                    t.id, t.content, t.source, t.required_recordings,
                    (
                        SELECT COUNT(*)
                        FROM recordings r
                        JOIN volunteers rv ON rv.id = r.volunteer_id
                        WHERE r.text_id = t.id
                          AND r.status IN ('pending', 'approved')
                          AND rv.consent_active = 1
                    ) AS current_recordings
                FROM texts t
                WHERE t.status = 'approved'
                  AND NOT EXISTS (
                      SELECT 1 FROM recordings own
                      WHERE own.text_id = t.id
                        AND own.volunteer_id = ?
                        AND own.status IN ('pending', 'approved')
                  )
                  {exclusion_sql}
                  AND (
                      SELECT COUNT(*)
                      FROM recordings r
                      JOIN volunteers rv ON rv.id = r.volunteer_id
                      WHERE r.text_id = t.id
                        AND r.status IN ('pending', 'approved')
                        AND rv.consent_active = 1
                  ) < t.required_recordings
                ORDER BY current_recordings ASC, t.id ASC
                LIMIT 1
                """,
                parameters,
            ).fetchone()
        return dict(row) if row else None

    def submit_recording(
        self,
        recording_id: str,
        text_id: int,
        volunteer_id: str,
        duration_ms: int,
        sample_rate: int,
        audio: bytes,
    ) -> dict:
        recording_id = validate_uuid(recording_id, "recording_id")
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        if not 300 <= duration_ms <= 120_000:
            raise CollectorError("duration_ms must be between 300 and 120000")
        if sample_rate not in (8_000, 16_000, 22_050, 44_100, 48_000):
            raise CollectorError("unsupported sample_rate")
        if len(audio) < 48 or len(audio) > 25 * 1024 * 1024:
            raise CollectorError("audio file size is invalid")
        if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise CollectorError("only PCM WAV files are accepted")

        target_path = self.audio_dir / f"{recording_id}.wav"
        temporary_path = target_path.with_suffix(".wav.part")
        digest = hashlib.sha256(audio).hexdigest()

        with self.database.connect() as connection:
            text = connection.execute(
                "SELECT id, status FROM texts WHERE id = ?", (text_id,)
            ).fetchone()
            if not text:
                raise NotFoundError("text not found")
            if text["status"] != "approved":
                raise ConflictError("text is not approved for recording")
            existing = connection.execute(
                "SELECT id FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            if existing:
                return {"id": recording_id, "status": "already_uploaded"}
            own = connection.execute(
                """
                SELECT id FROM recordings
                WHERE text_id = ? AND volunteer_id = ? AND status IN ('pending', 'approved')
                """,
                (text_id, volunteer_id),
            ).fetchone()
            if own:
                raise ConflictError("volunteer already recorded this text")

            temporary_path.write_bytes(audio)
            temporary_path.replace(target_path)
            try:
                connection.execute(
                    """
                    INSERT INTO recordings
                        (id, text_id, volunteer_id, file_path, duration_ms, sample_rate, sha256)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        recording_id,
                        text_id,
                        volunteer_id,
                        str(target_path),
                        duration_ms,
                        sample_rate,
                        digest,
                    ),
                )
            except Exception:
                target_path.unlink(missing_ok=True)
                raise
        return {"id": recording_id, "status": "pending"}

    def get_text_review_task(self, volunteer_id: str) -> dict | None:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT t.id, t.content, t.source
                FROM texts t
                WHERE t.status = 'pending_review'
                  AND (t.submitted_by IS NULL OR t.submitted_by != ?)
                  AND NOT EXISTS (
                      SELECT 1 FROM text_reviews tr
                      WHERE tr.text_id = t.id AND tr.volunteer_id = ?
                  )
                ORDER BY t.id ASC
                LIMIT 1
                """,
                (volunteer_id, volunteer_id),
            ).fetchone()
        return dict(row) if row else None

    def submit_text_review(
        self,
        text_id: int,
        volunteer_id: str,
        verdict: str,
        correction: str = "",
    ) -> dict:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        if verdict not in ("correct", "correction", "reject"):
            raise CollectorError("invalid text review verdict")
        correction = normalize_text(correction)
        if verdict == "correction" and len(correction) < 3:
            raise CollectorError("correction text is required")

        with self.database.connect() as connection:
            text = connection.execute(
                "SELECT id, status, submitted_by FROM texts WHERE id = ?", (text_id,)
            ).fetchone()
            if not text:
                raise NotFoundError("text not found")
            if text["status"] != "pending_review":
                raise ConflictError("text is no longer awaiting review")
            if text["submitted_by"] == volunteer_id:
                raise ConflictError("volunteer cannot review their own text")
            try:
                connection.execute(
                    """
                    INSERT INTO text_reviews (text_id, volunteer_id, verdict, correction)
                    VALUES (?, ?, ?, ?)
                    """,
                    (text_id, volunteer_id, verdict, correction),
                )
            except Exception as exc:
                raise ConflictError("text was already reviewed by this volunteer") from exc

            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN verdict = 'correct' THEN 1 ELSE 0 END) AS correct_count,
                    SUM(CASE WHEN verdict = 'reject' THEN 1 ELSE 0 END) AS reject_count,
                    SUM(CASE WHEN verdict = 'correction' THEN 1 ELSE 0 END) AS correction_count
                FROM text_reviews WHERE text_id = ?
                """,
                (text_id,),
            ).fetchone()
            status = "pending_review"
            if counts["correction_count"]:
                status = "needs_admin"
            elif counts["correct_count"] >= self.required_reviews:
                status = "approved"
            elif counts["reject_count"] >= self.required_reviews:
                status = "rejected"
            connection.execute(
                "UPDATE texts SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (status, text_id),
            )
        return {"text_id": text_id, "status": status}

    def get_audio_review_task(self, volunteer_id: str) -> dict | None:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT r.id, r.duration_ms, r.sample_rate, t.content AS text
                FROM recordings r
                JOIN texts t ON t.id = r.text_id
                JOIN volunteers owner ON owner.id = r.volunteer_id
                WHERE r.status = 'pending'
                  AND owner.consent_active = 1
                  AND r.volunteer_id <> ?
                  AND NOT EXISTS (
                      SELECT 1 FROM audio_reviews ar
                      WHERE ar.recording_id = r.id AND ar.volunteer_id = ?
                  )
                ORDER BY r.created_at ASC
                LIMIT 1
                """,
                (volunteer_id, volunteer_id),
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def submit_audio_review(
        self,
        recording_id: str,
        volunteer_id: str,
        verdict: str,
        reason: str = "",
    ) -> dict:
        recording_id = validate_uuid(recording_id, "recording_id")
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        if verdict not in ("approve", "reject"):
            raise CollectorError("invalid audio review verdict")

        with self.database.connect() as connection:
            recording = connection.execute(
                """
                SELECT r.id, r.volunteer_id, r.status, owner.consent_active
                FROM recordings r
                JOIN volunteers owner ON owner.id = r.volunteer_id
                WHERE r.id = ?
                """,
                (recording_id,),
            ).fetchone()
            if not recording:
                raise NotFoundError("recording not found")
            if not recording["consent_active"]:
                raise ConflictError("recording owner has withdrawn consent")
            if recording["volunteer_id"] == volunteer_id:
                raise ConflictError("volunteer cannot review their own recording")
            if recording["status"] != "pending":
                raise ConflictError("recording is no longer awaiting review")
            try:
                connection.execute(
                    """
                    INSERT INTO audio_reviews (recording_id, volunteer_id, verdict, reason)
                    VALUES (?, ?, ?, ?)
                    """,
                    (recording_id, volunteer_id, verdict, normalize_text(reason)[:500]),
                )
            except Exception as exc:
                raise ConflictError("recording was already reviewed by this volunteer") from exc

            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN verdict = 'approve' THEN 1 ELSE 0 END) AS approve_count,
                    SUM(CASE WHEN verdict = 'reject' THEN 1 ELSE 0 END) AS reject_count
                FROM audio_reviews WHERE recording_id = ?
                """,
                (recording_id,),
            ).fetchone()
            status = "pending"
            if counts["approve_count"] >= self.required_reviews:
                status = "approved"
            elif counts["reject_count"] >= self.required_reviews:
                status = "rejected"
            connection.execute(
                "UPDATE recordings SET status = ? WHERE id = ?", (status, recording_id)
            )
        return {"recording_id": recording_id, "status": status}

    def list_needs_admin(self, limit: int = 100) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT t.id, t.content, t.source,
                       GROUP_CONCAT(NULLIF(tr.correction, ''), ' || ') AS corrections
                FROM texts t
                LEFT JOIN text_reviews tr ON tr.text_id = t.id
                WHERE t.status = 'needs_admin'
                GROUP BY t.id
                ORDER BY t.id ASC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_text(self, text_id: int, action: str, content: str = "") -> dict:
        if action not in ("approve", "reject"):
            raise CollectorError("action must be approve or reject")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT content FROM texts WHERE id = ?", (text_id,)
            ).fetchone()
            if not row:
                raise NotFoundError("text not found")
            status = "approved" if action == "approve" else "rejected"
            final_content = normalize_text(content) if content else row["content"]
            if len(final_content) < 3:
                raise CollectorError("resolved text is too short")
            try:
                connection.execute(
                    """
                    UPDATE texts
                    SET content = ?, normalized = ?, status = ?,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (final_content, final_content.casefold(), status, text_id),
                )
            except Exception as exc:
                raise ConflictError("resolved text duplicates another text") from exc
        return {"text_id": text_id, "status": status, "content": final_content}

    def stats(self) -> dict:
        with self.database.connect() as connection:
            result = {
                "volunteers": connection.execute("SELECT COUNT(*) FROM volunteers").fetchone()[0],
                "texts": {},
                "recordings": {},
            }
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM texts GROUP BY status"
            ):
                result["texts"][row["status"]] = row["count"]
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM recordings GROUP BY status"
            ):
                result["recordings"][row["status"]] = row["count"]
        return result

    def volunteer_stats(self, volunteer_id: str) -> dict:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        result = {
            "submitted": 0,
            "pending_review": 0,
            "approved": 0,
            "rejected": 0,
        }
        with self.database.connect() as connection:
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM recordings WHERE volunteer_id = ? GROUP BY status",
                (volunteer_id,),
            ):
                count = int(row["count"])
                result["submitted"] += count
                if row["status"] == "pending":
                    result["pending_review"] = count
                elif row["status"] in result:
                    result[row["status"]] = count
        return result

    def list_volunteer_recordings(self, volunteer_id: str) -> list[dict]:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id, require_active=False)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT r.id, r.status, r.created_at, r.duration_ms, r.sample_rate,
                       t.id AS text_id, t.content AS text
                FROM recordings r
                JOIN texts t ON t.id = r.text_id
                WHERE r.volunteer_id = ?
                ORDER BY r.created_at DESC, r.id DESC
                """,
                (volunteer_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def volunteer_recording_path(self, volunteer_id: str, recording_id: str) -> Path:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        recording_id = validate_uuid(recording_id, "recording_id")
        self._require_volunteer(volunteer_id, require_active=False)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT file_path FROM recordings WHERE id = ? AND volunteer_id = ?",
                (recording_id, volunteer_id),
            ).fetchone()
        if not row:
            # Deliberately do not reveal whether another volunteer owns this UUID.
            raise NotFoundError("recording not found")
        path = self._managed_audio_path(row["file_path"])
        if not path.exists():
            raise NotFoundError("audio file is missing")
        return path

    def delete_volunteer_recording(self, volunteer_id: str, recording_id: str) -> dict:
        recording_id = validate_uuid(recording_id, "recording_id")
        deleted = self._delete_volunteer_recordings(volunteer_id, recording_id)
        return {"recording_id": recording_id, "deleted": deleted == 1}

    def delete_all_volunteer_recordings(self, volunteer_id: str) -> dict:
        deleted = self._delete_volunteer_recordings(volunteer_id, None)
        return {"deleted": deleted}

    def revoke_consent(self, volunteer_id: str) -> dict:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id, require_active=False)
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE volunteers
                SET consent_active = 0,
                    revoked_at = COALESCE(revoked_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                WHERE id = ?
                """,
                (volunteer_id,),
            )
            row = connection.execute(
                "SELECT consent_active, revoked_at FROM volunteers WHERE id = ?",
                (volunteer_id,),
            ).fetchone()
        return {
            "consent_active": bool(row["consent_active"]),
            "revoked_at": row["revoked_at"],
        }

    def volunteer_consent_active(self, volunteer_id: str) -> bool:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id, require_active=False)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT consent_active FROM volunteers WHERE id = ?", (volunteer_id,)
            ).fetchone()
        return bool(row["consent_active"])

    def export_dataset(self, output_dir: str | Path) -> dict:
        output = Path(output_dir).resolve()
        audio_output = output / "audio"
        audio_output.mkdir(parents=True, exist_ok=True)
        manifest_path = output / "manifest.jsonl"
        exported = 0
        with self.database.connect() as connection, manifest_path.open(
            "w", encoding="utf-8"
        ) as manifest:
            rows = connection.execute(
                """
                SELECT r.id, r.file_path, r.duration_ms, r.sample_rate,
                       r.volunteer_id, t.id AS text_id, t.content, t.source
                FROM recordings r
                JOIN texts t ON t.id = r.text_id
                JOIN volunteers v ON v.id = r.volunteer_id
                WHERE r.status = 'approved'
                  AND t.status = 'approved'
                  AND v.consent_active = 1
                ORDER BY t.id, r.created_at
                """
            ).fetchall()
            for row in rows:
                source_path = Path(row["file_path"])
                if not source_path.exists():
                    continue
                wav_name = f"{row['id']}.wav"
                txt_name = f"{row['id']}.txt"
                shutil.copy2(source_path, audio_output / wav_name)
                (audio_output / txt_name).write_text(row["content"] + "\n", encoding="utf-8")
                record = {
                    "audio": f"audio/{wav_name}",
                    "text": row["content"],
                    "speaker_id": row["volunteer_id"],
                    "text_id": row["text_id"],
                    "recording_id": row["id"],
                    "duration_ms": row["duration_ms"],
                    "sample_rate": row["sample_rate"],
                    "source": row["source"],
                }
                manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
                exported += 1
        return {"exported": exported, "manifest": str(manifest_path)}

    def recording_path(self, recording_id: str) -> Path:
        recording_id = validate_uuid(recording_id, "recording_id")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT file_path FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
        if not row:
            raise NotFoundError("recording not found")
        path = self._managed_audio_path(row["file_path"])
        if not path.exists():
            raise NotFoundError("audio file is missing")
        return path

    def _delete_volunteer_recordings(
        self,
        volunteer_id: str,
        recording_id: str | None,
    ) -> int:
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id, require_active=False)
        with self.database.connect() as connection:
            if recording_id is None:
                rows = connection.execute(
                    "SELECT id, file_path FROM recordings WHERE volunteer_id = ?",
                    (volunteer_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, file_path FROM recordings WHERE volunteer_id = ? AND id = ?",
                    (volunteer_id, recording_id),
                ).fetchall()
        if recording_id is not None and not rows:
            raise NotFoundError("recording not found")

        staged: list[tuple[Path, Path]] = []
        try:
            for row in rows:
                original = self._managed_audio_path(row["file_path"])
                if not original.exists():
                    continue
                tombstone = self.audio_dir / f".delete-{uuid.uuid4().hex}-{original.name}"
                original.replace(tombstone)
                staged.append((original, tombstone))

            try:
                with self.database.connect() as connection:
                    if recording_id is None:
                        cursor = connection.execute(
                            "DELETE FROM recordings WHERE volunteer_id = ?",
                            (volunteer_id,),
                        )
                    else:
                        cursor = connection.execute(
                            "DELETE FROM recordings WHERE volunteer_id = ? AND id = ?",
                            (volunteer_id, recording_id),
                        )
                    deleted = int(cursor.rowcount)
            except Exception:
                for original, tombstone in reversed(staged):
                    if tombstone.exists() and not original.exists():
                        tombstone.replace(original)
                raise

            cleanup_failed = False
            for _, tombstone in staged:
                try:
                    tombstone.unlink(missing_ok=True)
                except OSError:
                    cleanup_failed = True
            if cleanup_failed:
                raise CollectorError(
                    "recording metadata was removed but file cleanup is pending server restart"
                )
            return deleted
        except Exception:
            raise

    def _managed_audio_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path).resolve()
        try:
            path.relative_to(self.audio_dir)
        except ValueError as exc:
            raise CollectorError("audio path is outside managed storage") from exc
        return path

    def _purge_delete_tombstones(self) -> None:
        for path in self.audio_dir.glob(".delete-*"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # A locked file will be retried on the next server start.
                pass

    def _require_volunteer(self, volunteer_id: str, require_active: bool = True) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, consent_active FROM volunteers WHERE id = ?", (volunteer_id,)
            ).fetchone()
        if not row:
            raise NotFoundError("volunteer is not registered")
        if require_active and not row["consent_active"]:
            raise ForbiddenError("volunteer consent has been revoked")
