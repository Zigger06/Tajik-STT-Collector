package com.zigger06.tajiksttcollector.network

import com.zigger06.tajiksttcollector.data.AppSettings
import com.zigger06.tajiksttcollector.data.AudioReviewTask
import com.zigger06.tajiksttcollector.data.PendingRecording
import com.zigger06.tajiksttcollector.data.TextTask
import com.zigger06.tajiksttcollector.data.VolunteerStats
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiException(val statusCode: Int, message: String) : IOException(message)

class ApiClient(private val settings: AppSettings) {
    private val baseUrl = settings.serverUrl.trim().trimEnd('/')
    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    suspend fun checkHealth(): Boolean = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/health").get().build()
        execute(request).optBoolean("ok", false)
    }

    suspend fun registerVolunteer() = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("id", settings.volunteerId)
            .put("display_name", settings.displayName)
            .put("region", settings.region)
            .put("dialect", settings.dialect)
            .put("consent", settings.consent)
        execute(jsonRequest("/api/v1/volunteers", body))
        Unit
    }

    suspend fun recordingTask(excludeTextIds: List<Long> = emptyList()): TextTask? =
        withContext(Dispatchers.IO) {
        val builder = "$baseUrl/api/v1/tasks/recording".toHttpUrl().newBuilder()
            .addQueryParameter("volunteer_id", settings.volunteerId)
        if (excludeTextIds.isNotEmpty()) {
            builder.addQueryParameter(
                "exclude_text_ids",
                excludeTextIds.distinct().take(100).joinToString(","),
            )
        }
        val url = builder.build()
        parseTextTask(
            execute(Request.Builder().url(url).get().build()).optJSONObject("task"),
        )
    }

    suspend fun volunteerStats(): VolunteerStats = withContext(Dispatchers.IO) {
        val url = "$baseUrl/api/v1/volunteers/stats".toHttpUrl().newBuilder()
            .addQueryParameter("volunteer_id", settings.volunteerId)
            .build()
        val stats = execute(Request.Builder().url(url).get().build())
        VolunteerStats(
            submitted = stats.optInt("submitted", 0),
            pendingReview = stats.optInt("pending_review", 0),
            approved = stats.optInt("approved", 0),
            rejected = stats.optInt("rejected", 0),
        )
    }

    suspend fun textReviewTask(): TextTask? = withContext(Dispatchers.IO) {
        val url = "$baseUrl/api/v1/tasks/text-review".toHttpUrl().newBuilder()
            .addQueryParameter("volunteer_id", settings.volunteerId)
            .build()
        parseTextTask(
            execute(Request.Builder().url(url).get().build()).optJSONObject("task"),
        )
    }

    suspend fun audioReviewTask(): AudioReviewTask? = withContext(Dispatchers.IO) {
        val url = "$baseUrl/api/v1/tasks/audio-review".toHttpUrl().newBuilder()
            .addQueryParameter("volunteer_id", settings.volunteerId)
            .build()
        val task = execute(Request.Builder().url(url).get().build()).optJSONObject("task")
            ?: return@withContext null
        val audioUrl = task.getString("audio_url")
        AudioReviewTask(
            id = task.getString("id"),
            text = task.getString("text"),
            audioUrl = if (audioUrl.startsWith("http://") || audioUrl.startsWith("https://")) {
                audioUrl
            } else {
                "$baseUrl/${audioUrl.trimStart('/')}"
            },
            durationMs = task.optLong("duration_ms"),
            sampleRate = task.optInt("sample_rate", 16000),
        )
    }

    suspend fun uploadRecording(recording: PendingRecording) = withContext(Dispatchers.IO) {
        val file = File(recording.filePath)
        if (!file.exists()) throw IOException("Local WAV file is missing")
        val url = "$baseUrl/api/v1/recordings".toHttpUrl().newBuilder()
            .addQueryParameter("recording_id", recording.id)
            .addQueryParameter("text_id", recording.textId.toString())
            .addQueryParameter("volunteer_id", settings.volunteerId)
            .addQueryParameter("duration_ms", recording.durationMs.toString())
            .addQueryParameter("sample_rate", recording.sampleRate.toString())
            .build()
        val request = Request.Builder()
            .url(url)
            .post(file.asRequestBody("audio/wav".toMediaType()))
            .build()
        execute(request)
        Unit
    }

    suspend fun submitTextReview(textId: Long, verdict: String, correction: String = "") =
        withContext(Dispatchers.IO) {
            val body = JSONObject()
                .put("text_id", textId)
                .put("volunteer_id", settings.volunteerId)
                .put("verdict", verdict)
                .put("correction", correction)
            execute(jsonRequest("/api/v1/text-reviews", body))
            Unit
        }

    suspend fun submitAudioReview(recordingId: String, verdict: String, reason: String = "") =
        withContext(Dispatchers.IO) {
            val body = JSONObject()
                .put("recording_id", recordingId)
                .put("volunteer_id", settings.volunteerId)
                .put("verdict", verdict)
                .put("reason", reason)
            execute(jsonRequest("/api/v1/audio-reviews", body))
            Unit
        }

    private fun jsonRequest(path: String, body: JSONObject): Request {
        val request = Request.Builder()
            .url("$baseUrl$path")
            .post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
        return request.build()
    }

    private fun execute(request: Request): JSONObject {
        client.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            val json = if (text.isBlank()) JSONObject() else try {
                JSONObject(text)
            } catch (error: Exception) {
                throw IOException("Server returned invalid JSON", error)
            }
            if (!response.isSuccessful) {
                throw ApiException(response.code, json.optString("error", "HTTP ${response.code}"))
            }
            return json
        }
    }

    private fun parseTextTask(task: JSONObject?): TextTask? {
        task ?: return null
        return TextTask(
            id = task.getLong("id"),
            content = task.getString("content"),
            source = task.optString("source", ""),
            currentRecordings = task.optInt("current_recordings", 0),
            requiredRecordings = task.optInt("required_recordings", 5),
        )
    }
}
