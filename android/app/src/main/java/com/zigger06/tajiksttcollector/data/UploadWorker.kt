package com.zigger06.tajiksttcollector.data

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.zigger06.tajiksttcollector.network.ApiClient
import com.zigger06.tajiksttcollector.network.ApiException
import java.io.File
import java.io.IOException

class UploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val store = LocalStore(applicationContext)
        val settings = store.loadSettings()
        if (settings.participationRevoked) return Result.success()
        if (!settings.isConfigured) return Result.failure()
        val api = ApiClient(settings)
        return try {
            // Setup/migration already registers the credential. Re-registering before
            // every five-file upload was wasting the strict anti-Sybil registration
            // budget and could lock a legitimate volunteer out after normal testing.
            for (recording in store.pendingRecordings()) {
                try {
                    api.uploadRecording(recording)
                } catch (error: ApiException) {
                    if (!isAlreadyRecordedText(error)) throw error
                    // Recovery for a stale prompt from older clients: the server already
                    // has this volunteer's voice for the text, so this redundant WAV can
                    // never be accepted. Do not let one stale item block the whole queue.
                    if (store.keepLocalCopies()) {
                        store.retainUploadedCopy(recording)
                    }
                    store.removePending(recording.id)
                    ApiClient.discardRecordingTask(settings.volunteerId, recording.textId)
                    File(recording.filePath).delete()
                    continue
                }

                if (store.keepLocalCopies()) {
                    // The server upload is idempotent, so a failed local-copy write
                    // can safely retry without duplicating the server recording.
                    store.retainUploadedCopy(recording)
                }
                store.removePending(recording.id)
                ApiClient.discardRecordingTask(settings.volunteerId, recording.textId)
                File(recording.filePath).delete()
            }
            store.saveVolunteerStats(api.volunteerStats())

            // Refill the prompt cache while the network is already available.
            // Failure here must never roll back or retry successfully uploaded WAVs.
            try {
                val missing = (
                    RECORDING_TASK_CACHE_TARGET - store.cachedRecordingTaskCount()
                ).coerceAtLeast(0)
                if (missing > 0) {
                    val excluded = (
                        store.pendingTextIds() + store.cachedRecordingTaskIds()
                    ).distinct()
                    val fresh = api.recordingTasks(missing, excluded)
                    store.cacheRecordingTasks(fresh)
                    ApiClient.seedRecordingTasks(settings.volunteerId, store.cachedRecordingTasks())
                }
            } catch (_: Exception) {
                // Best-effort cache refill. The next app start or upload retries it.
            }
            Result.success()
        } catch (error: ApiException) {
            if (error.statusCode == 429 || error.statusCode >= 500) Result.retry() else Result.failure()
        } catch (error: IOException) {
            Result.retry()
        }
    }

    private fun isAlreadyRecordedText(error: ApiException): Boolean =
        error.statusCode == 409 &&
            error.message.orEmpty().contains("already recorded this text", ignoreCase = true)

    companion object {
        private const val UNIQUE_UPLOAD_WORK = "tajik-stt-upload"

        fun schedule(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val request = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(constraints)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                UNIQUE_UPLOAD_WORK,
                ExistingWorkPolicy.KEEP,
                request,
            )
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(UNIQUE_UPLOAD_WORK)
        }
    }
}
