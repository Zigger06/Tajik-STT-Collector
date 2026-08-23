package com.zigger06.tajiksttcollector.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import java.util.UUID

const val RECORDING_BATCH_SIZE = 5

class LocalStore(context: Context) {
    private val appContext = context.applicationContext
    private val preferences = appContext.getSharedPreferences("collector_settings", Context.MODE_PRIVATE)
    private val database = PendingDatabase(appContext)

    fun loadSettings(): AppSettings {
        val volunteerId = preferences.getString("volunteer_id", null)
            ?: UUID.randomUUID().toString().also {
                preferences.edit().putString("volunteer_id", it).apply()
            }
        return AppSettings(
            volunteerId = volunteerId,
            displayName = preferences.getString("display_name", "") ?: "",
            region = preferences.getString("region", "") ?: "",
            dialect = preferences.getString("dialect", "") ?: "",
            serverUrl = preferences.getString("server_url", "") ?: "",
            consent = preferences.getBoolean("consent", false),
        )
    }

    fun saveSettings(settings: AppSettings) {
        preferences.edit()
            .putString("volunteer_id", settings.volunteerId)
            .putString("display_name", settings.displayName.trim())
            .putString("region", settings.region.trim())
            .putString("dialect", settings.dialect.trim())
            .putString("server_url", settings.serverUrl.trim().trimEnd('/'))
            .putBoolean("consent", settings.consent)
            .apply()
    }

    fun cachedSubmittedCount(): Int = preferences.getInt("submitted_count", 0)

    fun saveSubmittedCount(count: Int) {
        preferences.edit().putInt("submitted_count", count.coerceAtLeast(0)).apply()
    }

    fun isDarkTheme(): Boolean = preferences.getBoolean("dark_theme", false)

    fun saveDarkTheme(enabled: Boolean) {
        preferences.edit().putBoolean("dark_theme", enabled).apply()
    }

    /** Saves one recording and releases the whole local batch only when it reaches five. */
    fun addPending(recording: PendingRecording): Boolean {
        val db = database.writableDatabase
        db.beginTransaction()
        return try {
            val values = ContentValues().apply {
                put("id", recording.id)
                put("text_id", recording.textId)
                put("file_path", recording.filePath)
                put("duration_ms", recording.durationMs)
                put("sample_rate", recording.sampleRate)
                put("ready", 0)
            }
            db.insertWithOnConflict(
                "pending_recordings",
                null,
                values,
                SQLiteDatabase.CONFLICT_REPLACE,
            )
            val staged = countWhere(db, "ready = 0")
            val batchReady = staged >= RECORDING_BATCH_SIZE
            if (batchReady) {
                val ready = ContentValues().apply { put("ready", 1) }
                db.update("pending_recordings", ready, "ready = 0", null)
            }
            db.setTransactionSuccessful()
            batchReady
        } finally {
            db.endTransaction()
        }
    }

    /** Only complete five-recording batches are visible to the uploader. */
    fun pendingRecordings(): List<PendingRecording> {
        val result = mutableListOf<PendingRecording>()
        database.readableDatabase.query(
            "pending_recordings",
            arrayOf("id", "text_id", "file_path", "duration_ms", "sample_rate"),
            "ready = 1",
            null,
            null,
            null,
            "created_at ASC",
        ).use { cursor ->
            val id = cursor.getColumnIndexOrThrow("id")
            val textId = cursor.getColumnIndexOrThrow("text_id")
            val filePath = cursor.getColumnIndexOrThrow("file_path")
            val duration = cursor.getColumnIndexOrThrow("duration_ms")
            val rate = cursor.getColumnIndexOrThrow("sample_rate")
            while (cursor.moveToNext()) {
                result += PendingRecording(
                    id = cursor.getString(id),
                    textId = cursor.getLong(textId),
                    filePath = cursor.getString(filePath),
                    durationMs = cursor.getLong(duration),
                    sampleRate = cursor.getInt(rate),
                )
            }
        }
        return result
    }

    fun pendingTextIds(): List<Long> {
        val result = mutableListOf<Long>()
        database.readableDatabase.query(
            true,
            "pending_recordings",
            arrayOf("text_id"),
            null,
            null,
            null,
            null,
            null,
            null,
        ).use { cursor ->
            val textId = cursor.getColumnIndexOrThrow("text_id")
            while (cursor.moveToNext()) result += cursor.getLong(textId)
        }
        return result
    }

    fun stagedCount(): Int = countWhere(database.readableDatabase, "ready = 0")

    fun removePending(id: String) {
        database.writableDatabase.delete("pending_recordings", "id = ?", arrayOf(id))
    }

    fun pendingCount(): Int = database.readableDatabase.rawQuery(
        "SELECT COUNT(*) FROM pending_recordings",
        null,
    ).use { cursor ->
        cursor.moveToFirst()
        cursor.getInt(0)
    }

    private fun countWhere(db: SQLiteDatabase, where: String): Int = db.rawQuery(
        "SELECT COUNT(*) FROM pending_recordings WHERE $where",
        null,
    ).use { cursor ->
        cursor.moveToFirst()
        cursor.getInt(0)
    }

    private class PendingDatabase(context: Context) :
        SQLiteOpenHelper(context, "collector_local.db", null, 2) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL(
                """
                CREATE TABLE pending_recordings (
                    id TEXT PRIMARY KEY,
                    text_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    sample_rate INTEGER NOT NULL,
                    ready INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
                """.trimIndent(),
            )
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            if (oldVersion < 2) {
                // Recordings queued by v0.3.0 were already eligible for upload.
                db.execSQL(
                    "ALTER TABLE pending_recordings ADD COLUMN ready INTEGER NOT NULL DEFAULT 1",
                )
            }
        }
    }
}
