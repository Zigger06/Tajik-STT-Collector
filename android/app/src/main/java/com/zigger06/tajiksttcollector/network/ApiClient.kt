package com.zigger06.tajiksttcollector.network

import com.zigger06.tajiksttcollector.data.AppSettings
import com.zigger06.tajiksttcollector.data.AudioReviewTask
import com.zigger06.tajiksttcollector.data.MyDataSnapshot
import com.zigger06.tajiksttcollector.data.OwnRecording
import com.zigger06.tajiksttcollector.data.PendingRecording
import com.zigger06.tajiksttcollector.data.RECORDING_TASK_CACHE_TARGET
import com.zigger06.tajiksttcollector.data.TextTask
import com.zigger06.tajiksttcollector.data.VolunteerStats
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.security.MessageDigest
import java.util.LinkedHashMap
import java.util.concurrent.TimeUnit

class ApiException(val statusCode: Int, message: String) : IOException(message)

class ApiClient(private val settings: AppSettings) {
    private val baseUrl = settings.serverUrl.trim().trimEnd('/')
    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    suspend fun checkHealth(): Boolean = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/health").get().build()
        execute(request).optBoolean("ok", false)
    }

    suspend fun registerVolunteer() = withContext(Dispatchers.IO) {
        val body = registrationBody(settings.consent)

        try {
            execute(registrationRequest(body))
        } catch (error: ApiException) {
            if (error.statusCode != 428) throw error
            val challenge = registrationChallenge()
            val nonce = challenge.getString("nonce")
            val difficulty = challenge.getInt("difficulty")
            val proof = withContext(Dispatchers.Default) {
                solveRegistrationProof(nonce, difficulty)
            }
            execute(registrationRequest(body, nonce, proof.toString()))
        }
        Unit
    }

    /** Explicit re-consent always uses a fresh proof challenge. */
    suspend fun resumeConsent() = withContext(Dispatchers.IO) {
        val challenge = registrationChallenge()
        val nonce = challenge.getString("nonce")
        val difficulty = challenge.getInt("difficulty")
        val proof = withContext(Dispatchers.Default) {
            solveRegistrationProof(nonce, difficulty)
        }
        execute(
            registrationRequest(
                registrationBody(consent = true),
                nonce,
                proof.toString(),
            ),
        )
        Unit
    }

    suspend fun submitText(text: String, source: String = "") = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("text", text)
            .put("source", source)
        execute(jsonRequest("/api/v1/texts", body))
        Unit
    }

    suspend fun submitTexts(texts: List<String>, source: String = ""): Int =
        withContext(Dispatchers.IO) {
            val body = JSONObject()
                .put("texts", JSONArray(texts))
                .put("source", source)
            execute(jsonRequest("/api/v1/texts/batch", body)).optInt("inserted", 0)
        }

    /**
     * Recording UI asks this for every prompt. The hot path is deliberately local:
     * a prefetched task is returned without touching DNS, Funnel or the PC server.
     */
    suspend fun recordingTask(excludeTextIds: List<Long> = emptyList()): TextTask? =
        withContext(Dispatchers.IO) {
            cachedRecordingTask(excludeTextIds)?.let { return@withContext it }
            recordingTasks(RECORDING_TASK_CACHE_TARGET, excludeTextIds)
            cachedRecordingTask(excludeTextIds)
        }

    suspend fun recordingTasks(
        limit: Int = RECORDING_TASK_CACHE_TARGET,
        excludeTextIds: List<Long> = emptyList(),
    ): List<TextTask> = withContext(Dispatchers.IO) {
        val builder = "$baseUrl/api/v1/tasks/recording-batch".toHttpUrl().newBuilder()
            .addQueryParameter("limit", limit.coerceIn(1, 20).toString())
        if (excludeTextIds.isNotEmpty()) {
            builder.addQueryParameter(
                "exclude_text_ids",
                excludeTextIds.distinct().take(100).joinToString(","),
            )
        }
        val response = execute(authorizedBuilder(builder.build().toString()).get().build())
        val array = response.optJSONArray("tasks")
        val tasks = buildList {
            if (array != null) {
                for (index in 0 until array.length()) {
                    parseTextTask(array.optJSONObject(index))?.let(::add)
                }
            }
        }
        seedRecordingTasks(settings.volunteerId, tasks)
        tasks
    }

    suspend fun volunteerStats(): VolunteerStats = withContext(Dispatchers.IO) {
        val stats = execute(
            authorizedBuilder("$baseUrl/api/v1/volunteers/stats").get().build(),
        )
        VolunteerStats(
            submitted = stats.optInt("submitted", 0),
            pendingReview = stats.optInt("pending_review", 0),
            approved = stats.optInt("approved", 0),
            rejected = stats.optInt("rejected", 0),
        )
    }

    suspend fun textReviewTask(): TextTask? = withContext(Dispatchers.IO) {
        parseTextTask(
            execute(authorizedBuilder("$baseUrl/api/v1/tasks/text-review").get().build())
                .optJSONObject("task"),
        )
    }

    suspend fun audioReviewTask(): AudioReviewTask? = withContext(Dispatchers.IO) {
        val task = execute(
            authorizedBuilder("$baseUrl/api/v1/tasks/audio-review").get().build(),
        ).optJSONObject("task") ?: return@withContext null
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

    /** Download reviewer audio once; repeated playback comes from process RAM. */
    suspend fun reviewAudio(recordingId: String, audioUrl: String): ByteArray =
        withContext(Dispatchers.IO) {
            val key = "review:${settings.volunteerId}:$recordingId"
            cachedAudio(key)?.let { return@withContext it }
            val bytes = executeBytes(Request.Builder().url(audioUrl).get().build())
            cacheAudio(key, bytes)
            bytes
        }

    suspend fun uploadRecording(recording: PendingRecording) = withContext(Dispatchers.IO) {
        val file = File(recording.filePath)
        if (!file.exists()) throw IOException("Local WAV file is missing")
        val url = "$baseUrl/api/v1/recordings".toHttpUrl().newBuilder()
            .addQueryParameter("recording_id", recording.id)
            .addQueryParameter("text_id", recording.textId.toString())
            .addQueryParameter("duration_ms", recording.durationMs.toString())
            .addQueryParameter("sample_rate", recording.sampleRate.toString())
            .build()
        val request = authorizedBuilder(url.toString())
            .post(file.asRequestBody("audio/wav".toMediaType()))
            .build()
        execute(request)
        Unit
    }

    suspend fun submitTextReview(textId: Long, verdict: String, correction: String = "") =
        withContext(Dispatchers.IO) {
            val body = JSONObject()
                .put("text_id", textId)
                .put("verdict", verdict)
                .put("correction", correction)
            execute(jsonRequest("/api/v1/text-reviews", body))
            Unit
        }

    suspend fun submitAudioReview(recordingId: String, verdict: String, reason: String = "") =
        withContext(Dispatchers.IO) {
            val body = JSONObject()
                .put("recording_id", recordingId)
                .put("verdict", verdict)
                .put("reason", reason)
            execute(jsonRequest("/api/v1/audio-reviews", body))
            removeCachedAudio("review:${settings.volunteerId}:$recordingId")
            Unit
        }

    suspend fun myData(offset: Int = 0, limit: Int = 10): MyDataSnapshot =
        withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/v1/me/recordings".toHttpUrl().newBuilder()
                .addQueryParameter("offset", offset.coerceAtLeast(0).toString())
                .addQueryParameter("limit", limit.coerceIn(1, 50).toString())
                .build()
            val response = execute(authorizedBuilder(url.toString()).get().build())
            val array = response.optJSONArray("recordings")
            val recordings = buildList {
                if (array != null) {
                    for (index in 0 until array.length()) {
                        val item = array.getJSONObject(index)
                        add(
                            OwnRecording(
                                id = item.getString("id"),
                                status = item.optString("status", "pending"),
                                createdAt = item.optString("created_at", ""),
                                text = item.optString("text", ""),
                                durationMs = item.optLong("duration_ms", 0L),
                                sampleRate = item.optInt("sample_rate", 16000),
                            ),
                        )
                    }
                }
            }
            MyDataSnapshot(
                recordings = recordings,
                consentActive = response.optBoolean("consent_active", true),
                total = response.optInt("total", recordings.size),
                hasMore = response.optBoolean("has_more", false),
                nextOffset = response.optInt("next_offset", offset + recordings.size),
            )
        }

    /** Fetch once, keep a bounded in-memory copy, and reuse it for Play + Download. */
    suspend fun ownRecordingAudio(recordingId: String): ByteArray = withContext(Dispatchers.IO) {
        val key = "own:${settings.volunteerId}:$recordingId"
        cachedAudio(key)?.let { return@withContext it }
        val url = "$baseUrl/api/v1/me/recordings/$recordingId/audio"
        val bytes = executeBytes(authorizedBuilder(url).get().build())
        cacheAudio(key, bytes)
        bytes
    }

    /** Returns only an already-fetched own WAV; this method never touches the network. */
    fun cachedOwnRecordingAudio(recordingId: String): ByteArray? =
        cachedAudio("own:${settings.volunteerId}:$recordingId")

    suspend fun downloadOwnRecordingTo(recordingId: String, output: OutputStream) =
        withContext(Dispatchers.IO) {
            output.write(ownRecordingAudio(recordingId))
            output.flush()
        }

    suspend fun downloadOwnArchiveTo(output: OutputStream) = withContext(Dispatchers.IO) {
        executeTo(
            authorizedBuilder("$baseUrl/api/v1/me/recordings/archive").get().build(),
            output,
        )
    }

    suspend fun deleteOwnRecording(recordingId: String) = withContext(Dispatchers.IO) {
        execute(
            authorizedBuilder("$baseUrl/api/v1/me/recordings/$recordingId")
                .delete()
                .build(),
        )
        removeCachedAudio("own:${settings.volunteerId}:$recordingId")
        Unit
    }

    suspend fun deleteAllOwnRecordings(): Int = withContext(Dispatchers.IO) {
        val deleted = execute(
            authorizedBuilder("$baseUrl/api/v1/me/recordings")
                .delete()
                .build(),
        ).optInt("deleted", 0)
        removeCachedAudioPrefix("own:${settings.volunteerId}:")
        deleted
    }

    suspend fun revokeConsent() = withContext(Dispatchers.IO) {
        val empty = JSONObject().toString()
            .toRequestBody("application/json; charset=utf-8".toMediaType())
        execute(
            authorizedBuilder("$baseUrl/api/v1/me/revoke-consent")
                .post(empty)
                .build(),
        )
        Unit
    }

    private fun registrationBody(consent: Boolean): JSONObject = JSONObject()
        .put("id", settings.volunteerId)
        .put("display_name", settings.displayName)
        .put("region", settings.region)
        .put("dialect", settings.dialect)
        .put("consent", consent)

    private fun registrationRequest(
        body: JSONObject,
        nonce: String = "",
        proof: String = "",
    ): Request {
        val builder = authorizedBuilder("$baseUrl/api/v1/volunteers")
            .post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
        if (nonce.isNotBlank()) builder.header("X-Registration-Nonce", nonce)
        if (proof.isNotBlank()) builder.header("X-Registration-Proof", proof)
        return builder.build()
    }

    private fun registrationChallenge(): JSONObject {
        val request = authorizedBuilder("$baseUrl/api/v1/registration-challenge")
            .get()
            .build()
        return execute(request)
    }

    private fun jsonRequest(path: String, body: JSONObject): Request =
        authorizedBuilder("$baseUrl$path")
            .post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
            .build()

    private fun authorizedBuilder(url: String): Request.Builder = Request.Builder()
        .url(url)
        .header("X-Volunteer-Id", settings.volunteerId)
        .header("Authorization", "Bearer ${settings.deviceSecret}")

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

    private fun executeBytes(request: Request, maxBytes: Int = MAX_RAM_AUDIO_BYTES): ByteArray {
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val text = response.body?.string().orEmpty()
                val message = try {
                    JSONObject(text).optString("error", "HTTP ${response.code}")
                } catch (_: Exception) {
                    "HTTP ${response.code}"
                }
                throw ApiException(response.code, message)
            }
            val body = response.body ?: throw IOException("Server returned an empty file")
            val declared = body.contentLength()
            if (declared > maxBytes) throw IOException("Audio is too large for memory cache")

            // Our audio endpoints always provide Content-Length. Read exactly that
            // many bytes and return immediately instead of waiting for a socket EOF.
            // This also makes the download path robust if an HTTP connection is kept
            // alive after the complete WAV body has already arrived.
            if (declared >= 0L) {
                val expected = declared.toInt()
                val output = ByteArrayOutputStream(expected)
                body.byteStream().use { input ->
                    val buffer = ByteArray(64 * 1024)
                    var remaining = expected
                    while (remaining > 0) {
                        val read = input.read(buffer, 0, minOf(buffer.size, remaining))
                        if (read < 0) throw IOException("Audio response ended early")
                        output.write(buffer, 0, read)
                        remaining -= read
                    }
                }
                return output.toByteArray()
            }

            // Defensive fallback for an unexpected chunked/unknown-length response.
            val output = ByteArrayOutputStream(64 * 1024)
            body.byteStream().use { input ->
                val buffer = ByteArray(64 * 1024)
                var total = 0
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    total += read
                    if (total > maxBytes) throw IOException("Audio is too large for memory cache")
                    output.write(buffer, 0, read)
                }
            }
            return output.toByteArray()
        }
    }

    private fun executeTo(request: Request, output: OutputStream) {
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val text = response.body?.string().orEmpty()
                val message = try {
                    JSONObject(text).optString("error", "HTTP ${response.code}")
                } catch (_: Exception) {
                    "HTTP ${response.code}"
                }
                throw ApiException(response.code, message)
            }
            val body = response.body ?: throw IOException("Server returned an empty file")
            body.byteStream().use { input -> input.copyTo(output, 64 * 1024) }
            output.flush()
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

    private fun cachedRecordingTask(excludeTextIds: List<Long>): TextTask? {
        val excluded = excludeTextIds.toHashSet()
        return synchronized(recordingTaskCacheLock) {
            val cache = recordingTaskCache[settings.volunteerId] ?: return@synchronized null
            val iterator = cache.entries.iterator()
            while (iterator.hasNext()) {
                val entry = iterator.next()
                if (entry.key in excluded) {
                    iterator.remove()
                    continue
                }
                return@synchronized entry.value
            }
            null
        }
    }

    private fun solveRegistrationProof(nonce: String, difficulty: Int): Long {
        require(difficulty in 1..24) { "Invalid registration challenge" }
        val digest = MessageDigest.getInstance("SHA-256")
        var counter = 0L
        while (counter >= 0) {
            val hash = digest.digest("$nonce:$counter".toByteArray(Charsets.UTF_8))
            if (hasLeadingZeroBits(hash, difficulty)) return counter
            counter++
        }
        throw IOException("Registration proof could not be generated")
    }

    private fun hasLeadingZeroBits(digest: ByteArray, bits: Int): Boolean {
        val wholeBytes = bits / 8
        val remainingBits = bits % 8
        for (index in 0 until wholeBytes) {
            if (digest[index].toInt() and 0xff != 0) return false
        }
        if (remainingBits == 0) return true
        val mask = (0xff shl (8 - remainingBits)) and 0xff
        return (digest[wholeBytes].toInt() and 0xff and mask) == 0
    }

    companion object {
        private const val MAX_RAM_AUDIO_BYTES = 25 * 1024 * 1024
        private const val MAX_AUDIO_CACHE_BYTES = 32 * 1024 * 1024

        private val recordingTaskCacheLock = Any()
        private val recordingTaskCache = mutableMapOf<String, LinkedHashMap<Long, TextTask>>()

        private val audioCacheLock = Any()
        private val audioCache = object : LinkedHashMap<String, ByteArray>(16, 0.75f, true) {}
        private var audioCacheBytes = 0

        private fun cachedAudio(key: String): ByteArray? = synchronized(audioCacheLock) {
            audioCache[key]
        }

        private fun cacheAudio(key: String, bytes: ByteArray) = synchronized(audioCacheLock) {
            audioCache.remove(key)?.let { audioCacheBytes -= it.size }
            audioCache[key] = bytes
            audioCacheBytes += bytes.size
            val iterator = audioCache.entries.iterator()
            while (audioCacheBytes > MAX_AUDIO_CACHE_BYTES && iterator.hasNext()) {
                val removed = iterator.next()
                audioCacheBytes -= removed.value.size
                iterator.remove()
            }
        }

        private fun removeCachedAudio(key: String) = synchronized(audioCacheLock) {
            audioCache.remove(key)?.let { audioCacheBytes -= it.size }
        }

        private fun removeCachedAudioPrefix(prefix: String) = synchronized(audioCacheLock) {
            val iterator = audioCache.entries.iterator()
            while (iterator.hasNext()) {
                val entry = iterator.next()
                if (entry.key.startsWith(prefix)) {
                    audioCacheBytes -= entry.value.size
                    iterator.remove()
                }
            }
        }

        /** Seeds process memory from LocalStore, or adds freshly prefetched tasks. */
        fun seedRecordingTasks(volunteerId: String, tasks: List<TextTask>) {
            if (volunteerId.isBlank() || tasks.isEmpty()) return
            synchronized(recordingTaskCacheLock) {
                val cache = recordingTaskCache.getOrPut(volunteerId) { LinkedHashMap() }
                tasks.forEach { task -> cache[task.id] = task }
                while (cache.size > RECORDING_TASK_CACHE_TARGET * 2) {
                    val first = cache.entries.firstOrNull()?.key ?: break
                    cache.remove(first)
                }
            }
        }

        /** Remove a prompt immediately after its WAV is accepted into the local queue. */
        fun discardRecordingTask(volunteerId: String, textId: Long) {
            synchronized(recordingTaskCacheLock) {
                val cache = recordingTaskCache[volunteerId] ?: return
                cache.remove(textId)
                if (cache.isEmpty()) recordingTaskCache.remove(volunteerId)
            }
        }
    }
}
