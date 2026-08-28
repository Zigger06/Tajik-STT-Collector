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
                ExistingWorkPolicy.APPEND_OR_REPLACE,
                request,
            )
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(UNIQUE_UPLOAD_WORK)
        }
    }
}
