from __future__ import annotations

from pathlib import Path

from .service import (
    CollectorError,
    CollectorService,
    normalize_text,
    validate_uuid,
)


class StorageAwareCollectorService(CollectorService):
    """Production-facing service with storage and mobile-workflow safeguards."""

    def get_audio_review_task(self, volunteer_id: str) -> dict | None:
        """Never assign a database row whose WAV is no longer readable."""
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT r.id, r.duration_ms, r.sample_rate, r.file_path, t.content AS text
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
                LIMIT 200
                """,
                (volunteer_id, volunteer_id),
            ).fetchall()

        audio_root = self.audio_dir.resolve()
        for row in rows:
            try:
                path = Path(row["file_path"]).resolve()
            except (OSError, TypeError, ValueError):
                continue
            if path.parent != audio_root or not path.is_file():
                continue
            return {
                "id": row["id"],
                "duration_ms": row["duration_ms"],
                "sample_rate": row["sample_rate"],
                "text": row["text"],
            }
        return None

    def submit_text(self, volunteer_id: str, content: str, source: str = "") -> dict:
        """Volunteer-facing text tasks stay short enough for recording and review."""
        normalized = normalize_text(content)
        if len(normalized) > 300:
            raise CollectorError("volunteer text must be at most 300 characters")
        return super().submit_text(volunteer_id, normalized, source)

    def submit_text_batch(
        self,
        volunteer_id: str,
        contents: list[str],
        source: str = "",
    ) -> dict:
        """Insert many short volunteer sentences in one HTTP request.

        The Android UI may accept a paragraph up to 5000 characters, split it into
        sentence-sized units, and send all units here at once. Each stored review task
        remains independent and never exceeds 300 characters.
        """
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        if not isinstance(contents, list) or not 1 <= len(contents) <= 50:
            raise CollectorError("texts must contain between 1 and 50 items")

        cleaned = [normalize_text(str(value)) for value in contents]
        if sum(len(value) for value in cleaned) > 5000:
            raise CollectorError("combined volunteer text must be at most 5000 characters")
        for value in cleaned:
            if len(value) < 3:
                raise CollectorError("each volunteer text must be at least 3 characters")
            if len(value) > 300:
                raise CollectorError("each volunteer text must be at most 300 characters")

        source = normalize_text(source)[:500]
        inserted_ids: list[int] = []
        duplicates = 0
        with self.database.connect() as connection:
            for content in cleaned:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO texts
                        (content, normalized, source, submitted_by, status, required_recordings)
                    VALUES (?, ?, ?, ?, 'pending_review', 5)
                    """,
                    (content, content.casefold(), source, volunteer_id),
                )
                if cursor.rowcount:
                    inserted_ids.append(int(cursor.lastrowid))
                else:
                    duplicates += 1
        return {
            "inserted": len(inserted_ids),
            "duplicates": duplicates,
            "text_ids": inserted_ids,
        }

    def volunteer_recordings_page(
        self,
        volunteer_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> dict:
        """Return only one lightweight metadata page; audio is fetched on demand."""
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id, require_active=False)
        limit = max(1, min(int(limit), 50))
        offset = max(0, int(offset))
        with self.database.connect() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM recordings WHERE volunteer_id = ?",
                    (volunteer_id,),
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT r.id, r.status, r.created_at, r.duration_ms, r.sample_rate,
                       t.id AS text_id, t.content AS text
                FROM recordings r
                JOIN texts t ON t.id = r.text_id
                WHERE r.volunteer_id = ?
                ORDER BY r.created_at DESC, r.id DESC
                LIMIT ? OFFSET ?
                """,
                (volunteer_id, limit, offset),
            ).fetchall()
        recordings = [dict(row) for row in rows]
        next_offset = offset + len(recordings)
        return {
            "recordings": recordings,
            "total": total,
            "has_more": next_offset < total,
            "next_offset": next_offset,
        }
