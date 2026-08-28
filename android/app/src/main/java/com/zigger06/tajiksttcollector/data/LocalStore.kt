package com.zigger06.tajiksttcollector.data

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import java.io.File
import java.io.IOException
import java.util.UUID

const val RECORDING_BATCH_SIZE = 5

class LocalStore(context: Context) {
    private val appContext = context.applicationContext
    private val preferences = appContext.getSharedPreferences("collector_settings", Context.MODE_PRIVATE)
    private val database = PendingDatabase(appContext)

    fun loadSettings(): AppSettings {
        // Keep the pre-auth volunteer UUID during upgrades so existing server
        // history and the local five-recording queue remain attached to it.
        val volunteerId = preferences.getString("volunteer_id", null)
            ?: UUID.randomUUID().toString().also {
                preferences.edit().putString("volunteer_id", it).apply()
            }
        // Existing installs did not have this value. Generate it once on first
        // launch after upgrade and keep it in app-private SharedPreferences.
        // android:allowBackup=false prevents normal Android backup export.
        val deviceSecret = preferences.getString("device_secret", null)
            ?.takeIf { it.isNotBlank() }
            ?: DeviceCredential.generateSecret().also {
                preferences.edit().putString("device_secret", it).apply()
            }
        return AppSettings(
            volunteerId = volunteerId,
            deviceSecret = deviceSecret,
            displayName = preferences.getString("display_name", "") ?: "",
            region = preferences.getString("region", "") ?: "",
            dialect = preferences.getString("dialect", "") ?: "",
            serverUrl = preferences.getString("server_url", "") ?: "",
            consent = preferences.getBoolean("consent", false),
            participationRevoked = preferences.getBoolean("participation_revoked", false),
        )
    }

    fun saveSettings(settings: AppSettings) {
        preferences.edit()
            .putString("volunteer_id", settings.volunteerId)
            // device_secret is deliberately not rewritten from UI settings.
            .putString("display_name", settings.displayName.trim())
            .putString("region", settings.region.trim())
            .putString("dialect", settings.dialect.trim())
            .putString("server_url", settings.serverUrl.trim().trimEnd('/'))
            .putBoolean("consent", settings.consent)
            .putBoolean("participation_revoked", settings.participationRevoked)
            .apply()
    }

    fun markParticipationRevoked() {
        preferences.edit()
            .putBoolean("consent", false)
            .putBoolean("participation_revoked", true)
            .apply()
        clearPendingRecordings()
    }

    fun markParticipationResumed() {
        preferences.edit()
            .putBoolean("consent", true)
            .putBoolean("participation_revoked", false)
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

    fun keepLocalCopies(): Boolean = preferences.getBoolean("keep_local_copies", false)

    fun saveKeepLocalCopies(enabled: Boolean) {
        preferences.edit().putBoolean("keep_local_copies", enabled).apply()
    }

    /**
     * Keeps a user-owned copy after a successful server upload.
     *
     * Android 10+ stores it in Downloads/Tajik-STT so it remains visible outside
     * the app. Android 8/9 use app-specific external storage because public
     * Downloads would otherwise require the legacy broad storage permission.
     * This method is idempotent for WorkManager retries.
     */
    @Throws(IOException::class)
    fun retainUploadedCopy(recording: PendingRecording) {
        val source = File(recording.filePath)
        if (!source.exists()) throw IOException("Local WAV file is missing")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            retainInDownloads(recording.id, source)
        } else {
            retainInAppExternalStorage(recording.id, source)
        }
    }

    private fun retainInDownloads(recordingId: String, source: File) {
        val resolver = appContext.contentResolver
        val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
        val relativePath = "${Environment.DIRECTORY_DOWNLOADS}/Tajik-STT"
        val displayName = "$recordingId.wav"
        val projection = arrayOf(MediaStore.MediaColumns._ID, MediaStore.MediaColumns.SIZE)
        val selection =
            "${MediaStore.MediaColumns.DISPLAY_NAME} = ? AND ${MediaStore.MediaColumns.RELATIVE_PATH} = ?"
        val selectionArgs = arrayOf(displayName, relativePath)

        resolver.query(collection, projection, selection, selectionArgs, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val id = cursor.getLong(cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID))
                val size = cursor.getLong(cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.SIZE))
                val existing = ContentUris.withAppendedId(collection, id)
                if (size == source.length()) return
                resolver.delete(existing, null, null)
            }
        }

        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, displayName)
            put(MediaStore.MediaColumns.MIME_TYPE, "audio/wav")
            put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = resolver.insert(collection, values)
            ?: throw IOException("Could not create a local WAV copy")
        try {
            val output = resolver.openOutputStream(uri, "w")
                ?: throw IOException("Could not open the local WAV copy")
            output.use { destination -> source.inputStream().use { it.copyTo(destination) } }
            val ready = ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }
            resolver.update(uri, ready, null, null)
        } catch (error: Exception) {
            resolver.delete(uri, null, null)
            if (error is IOException) throw error
            throw IOException("Could not save the local WAV copy", error)
        }
    }

    private fun retainInAppExternalStorage(recordingId: String, source: File) {
        val root = appContext.getExternalFilesDir(Environment.DIRECTORY_MUSIC)
            ?: File(appContext.filesDir, "saved_recordings")
        val directory = File(root, "Tajik-STT").apply { mkdirs() }
        val target = File(directory, "$recordingId.wav")
        if (target.exists() && target.length() == source.length()) return
        source.copyTo(target, overwrite = true)
        if (!target.exists() || target.length() != source.length()) {
            target.delete()
            throw IOException("Could not verify the local WAV copy")
        }
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

    fun clearPendingRecordings(): Int {
        val paths = mutableListOf<String>()
        database.readableDatabase.query(
            "pending_recordings",
            arrayOf("file_path"),
            null,
            null,
            null,
            null,
            null,
        ).use { cursor ->
            val filePath = cursor.getColumnIndexOrThrow("file_path")
            while (cursor.moveToNext()) paths += cursor.getString(filePath)
        }
        paths.forEach { path ->
            try {
                File(path).delete()
            } catch (_: SecurityException) {
                // App-private queue cleanup is best-effort; DB entry is still removed.
            }
        }
        return database.writableDatabase.delete("pending_recordings", null, null)
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
