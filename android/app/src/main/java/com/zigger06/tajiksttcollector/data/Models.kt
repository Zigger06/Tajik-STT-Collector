package com.zigger06.tajiksttcollector.data

data class AppSettings(
    val volunteerId: String,
    val displayName: String,
    val region: String,
    val dialect: String,
    val serverUrl: String,
    val projectKey: String,
    val consent: Boolean,
) {
    val isConfigured: Boolean
        get() = displayName.isNotBlank() &&
            serverUrl.isNotBlank() &&
            projectKey.isNotBlank() &&
            consent
}

data class TextTask(
    val id: Long,
    val content: String,
    val source: String,
    val currentRecordings: Int = 0,
    val requiredRecordings: Int = 5,
)

data class AudioReviewTask(
    val id: String,
    val text: String,
    val audioUrl: String,
    val durationMs: Long,
    val sampleRate: Int,
)

data class PendingRecording(
    val id: String,
    val textId: Long,
    val filePath: String,
    val durationMs: Long,
    val sampleRate: Int,
)
