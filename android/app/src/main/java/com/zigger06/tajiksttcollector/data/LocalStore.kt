package com.zigger06.tajiksttcollector.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import java.util.UUID

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
            serverUrl = preferences.getString("server_url", "http://10.0.2.2:8000")
                ?: "http://10.0.2.2:8000",
            projectKey = preferences.getString("project_key", "tajik-stt-local")
                ?: "tajik-stt-local",
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
            .putString("project_key", settings.projectKey.trim())
            .putBoolean("consent", settings.consent)
            .apply()
    }

    fun addPending(recording: PendingRecording) {
        val values = ContentValues().apply {
            put("id", recording.id)
            put("text_id", recording.textId)
            put("file_path", recording.filePath)
            put("duration_ms", recording.durationMs)
            put("sample_rate", recording.sampleRate)
        }
        database.writableDatabase.insertWithOnConflict(
            "pending_recordings",
            null,
            values,
            SQLiteDatabase.CONFLICT_REPLACE,
        )
    }

    fun pendingRecordings(): List<PendingRecording> {
        val result = mutableListOf<PendingRecording>()
        database.readableDatabase.query(
            "pending_recordings",
            arrayOf("id", "text_id", "file_path", "duration_ms", "sample_rate"),
            null,
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

    private class PendingDatabase(context: Context) :
        SQLiteOpenHelper(context, "collector_local.db", null, 1) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL(
                """
                CREATE TABLE pending_recordings (
                    id TEXT PRIMARY KEY,
                    text_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    sample_rate INTEGER NOT NULL,
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
                """.trimIndent(),
            )
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
    }
}
