from __future__ import annotations

from pathlib import Path

from .service import (
    CollectorError,
    CollectorService,
    ConflictError,
    normalize_text,
    validate_uuid,
)


VOLUNTEER_TEXT_HOURLY_LIMIT = 60


class VolunteerTextRateLimitError(CollectorError):
    status_code = 429


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

    @staticmethod
    def _assert_text_budget(connection, volunteer_id: str, new_items: int) -> None:
        """Bound actual new volunteer sentences, not merely HTTP request count.

        The legacy HTTP limiter charges one slot per request, so a batch endpoint could
        otherwise amplify one request into dozens of stored texts. This persistent
        semantic quota survives backend restarts and counts the rows that would really
        be inserted, closing that amplification path independently of HTTP batching.
        """
        if new_items <= 0:
            return
        recent = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM texts
                WHERE submitted_by = ?
                  AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 hour')
                """,
                (volunteer_id,),
            ).fetchone()[0]
        )
        if recent + new_items > VOLUNTEER_TEXT_HOURLY_LIMIT:
            raise VolunteerTextRateLimitError(
                "too many volunteer texts; please try again later"
            )

    def submit_text(self, volunteer_id: str, content: str, source: str = "") -> dict:
        """Volunteer-facing text tasks stay short and share the persistent quota."""
        volunteer_id = validate_uuid(volunteer_id, "volunteer_id")
        self._require_volunteer(volunteer_id)
        normalized = normalize_text(content)
        if len(normalized) < 3:
            raise CollectorError("text is too short")
        if len(normalized) > 300:
            raise CollectorError("volunteer text must be at most 300 characters")
        source = normalize_text(source)[:500]

        with self.database.connect() as connection:
            # Serialize budget-check + insert across ThreadingHTTPServer workers.
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT id FROM texts WHERE normalized = ?",
                (normalized.casefold(),),
            ).fetchone()
            if existing:
                raise ConflictError("text already exists")
            self._assert_text_budget(connection, volunteer_id, 1)
            cursor = connection.execute(
                """
                INSERT INTO texts
                    (content, normalized, source, submitted_by, status, required_recordings)
                VALUES (?, ?, ?, ?, 'pending_review', 5)
                """,
                (normalized, normalized.casefold(), source, volunteer_id),
            )
            text_id = int(cursor.lastrowid)
        return {
            "id": text_id,
            "content": normalized,
            "source": source,
            "status": "pending_review",
        }

    def submit_text_batch(
        self,
        volunteer_id: str,
        contents: list[str],
        source: str = "",
    ) -> dict:
        """Insert many short volunteer sentences in one HTTP request.

        A batch may still contain up to 50 UI-split sentences for convenience, but the
        persistent hourly quota counts every actual new sentence. Therefore restarting
        the backend or packing many sentences into one request cannot multiply the
        allowed contribution rate.
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
        unique_by_normalized: dict[str, str] = {}
        for content in cleaned:
            unique_by_normalized.setdefault(content.casefold(), content)

        inserted_ids: list[int] = []
        with self.database.connect() as connection:
            # BEGIN IMMEDIATE makes the semantic quota race-safe across concurrent
            # batch/single submissions handled by different server threads.
            connection.execute("BEGIN IMMEDIATE")
            normalized_values = list(unique_by_normalized)
            placeholders = ", ".join("?" for _ in normalized_values)
            existing = {
                str(row["normalized"])
                for row in connection.execute(
                    f"SELECT normalized FROM texts WHERE normalized IN ({placeholders})",
                    normalized_values,
                ).fetchall()
            }
            new_contents = [
                content
                for normalized, content in unique_by_normalized.items()
                if normalized not in existing
            ]
            self._assert_text_budget(connection, volunteer_id, len(new_contents))

            for content in new_contents:
                cursor = connection.execute(
                    """
                    INSERT INTO texts
                        (content, normalized, source, submitted_by, status, required_recordings)
                    VALUES (?, ?, ?, ?, 'pending_review', 5)
                    """,
                    (content, content.casefold(), source, volunteer_id),
                )
                inserted_ids.append(int(cursor.lastrowid))

        return {
            "inserted": len(inserted_ids),
            "duplicates": len(cleaned) - len(inserted_ids),
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
