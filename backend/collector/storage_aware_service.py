from __future__ import annotations

from pathlib import Path

from .service import CollectorService, validate_uuid


class StorageAwareCollectorService(CollectorService):
    """Collector service that never assigns an unreadable WAV for review.

    Older development builds could leave a recording row behind after the WAV was
    removed manually or by a pre-release bug. Such a row used to become the oldest
    review task forever: the task endpoint returned it, while /media/... correctly
    returned 404 because the file did not exist. We keep the metadata untouched for
    admin/audit purposes, but skip unusable rows and continue to the next valid WAV.
    """

    def get_audio_review_task(self, volunteer_id: str) -> dict | None:
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
