package com.zigger06.tajiksttcollector.data

data class AppSettings(
    val volunteerId: String,
    val deviceSecret: String,
    val displayName: String,
    val region: String,
    val dialect: String,
    val serverUrl: String,
    val consent: Boolean,
    val participationRevoked: Boolean = false,
) {
    val isConfigured: Boolean
        get() = volunteerId.isNotBlank() &&
            deviceSecret.isNotBlank() &&
            displayName.isNotBlank() &&
            serverUrl.isNotBlank() &&
            consent

    val canContribute: Boolean
        get() = isConfigured && !participationRevoked

    // Do not let accidental logging of this data class expose the bearer token.
    override fun toString(): String =
        "AppSettings(volunteerId=$volunteerId, deviceSecret=<redacted>, " +
            "displayName=$displayName, region=$region, dialect=$dialect, " +
            "serverUrl=$serverUrl, consent=$consent, " +
            "participationRevoked=$participationRevoked)"
}

data class TextTask(
    val id: Long,
    val content: String,
    val source: String,
    val currentRecordings: Int = 0,
    val requiredRecordings: Int = 5,
)

data class VolunteerStats(
    val submitted: Int,
    val pendingReview: Int,
    val approved: Int,
    val rejected: Int,
)

data class AudioReviewTask(
    val id: String,
    val text: String,
    val audioUrl: String,
    val durationMs: Long,
    val sampleRate: Int,
)

data class OwnRecording(
    val id: String,
    val status: String,
    val createdAt: String,
    val text: String,
    val durationMs: Long,
    val sampleRate: Int,
)

data class MyDataSnapshot(
    val recordings: List<OwnRecording>,
    val consentActive: Boolean,
)

data class PendingRecording(
    val id: String,
    val textId: Long,
    val filePath: String,
    val durationMs: Long,
    val sampleRate: Int,
)
