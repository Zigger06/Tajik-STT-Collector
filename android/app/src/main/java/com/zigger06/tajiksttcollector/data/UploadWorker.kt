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
            api.registerVolunteer()
            // A complete five-recording batch is already local before this loop.
            // Network speed therefore never blocks the user's Save button: this
            // worker uploads the ready files later when Android reports connectivity.
            for (recording in store.pendingRecordings()) {
                api.uploadRecording(recording)
                if (store.keepLocalCopies()) {
                    // The server upload is idempotent, so a failed local-copy write
                    // can safely retry without duplicating the server recording.
                    store.retainUploadedCopy(recording)
                }
                store.removePending(recording.id)
                File(recording.filePath).delete()
            }
            store.saveSubmittedCount(api.volunteerStats().submitted)

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
