package com.zigger06.tajiksttcollector.ui

import android.media.MediaPlayer
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.PauseCircle
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.PrivacyTip
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.zigger06.tajiksttcollector.audio.ByteArrayMediaDataSource
import com.zigger06.tajiksttcollector.data.AppSettings
import com.zigger06.tajiksttcollector.data.LocalStore
import com.zigger06.tajiksttcollector.data.OwnRecording
import com.zigger06.tajiksttcollector.data.UploadWorker
import com.zigger06.tajiksttcollector.network.ApiClient
import kotlinx.coroutines.launch
import java.io.IOException

private const val MY_DATA_PAGE_SIZE = 10

@Composable
fun MyDataScreen(
    store: LocalStore,
    onBack: (() -> Unit)?,
    onParticipationRevoked: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }
    var settings by remember { mutableStateOf(store.loadSettings()) }
    var recordings by remember { mutableStateOf<List<OwnRecording>>(emptyList()) }
    var totalRecordings by remember { mutableStateOf(0) }
    var hasMore by remember { mutableStateOf(false) }
    var nextOffset by remember { mutableStateOf(0) }
    var consentActive by remember { mutableStateOf(!settings.participationRevoked) }
    var loading by remember { mutableStateOf(true) }
    var loadingMore by remember { mutableStateOf(false) }
    var actionBusy by remember { mutableStateOf(false) }
    var audioBusyId by remember { mutableStateOf<String?>(null) }
    var downloadBusyId by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf("") }
    var recordingToDelete by remember { mutableStateOf<OwnRecording?>(null) }
    var confirmDeleteAll by remember { mutableStateOf(false) }
    var confirmRevoke by remember { mutableStateOf(false) }
    var showLocalCopyInfo by remember { mutableStateOf(false) }
    var keepLocalCopies by remember { mutableStateOf(store.keepLocalCopies()) }
    var pendingDownloadId by remember { mutableStateOf<String?>(null) }
    var player by remember { mutableStateOf<MediaPlayer?>(null) }
    var playingId by remember { mutableStateOf<String?>(null) }

    fun stopPlayer() {
        player?.release()
        player = null
        playingId = null
    }

    suspend fun applyParticipationState(snapshotConsentActive: Boolean) {
        consentActive = snapshotConsentActive
        if (!snapshotConsentActive && !settings.participationRevoked) {
            UploadWorker.cancel(context)
            store.markParticipationRevoked()
            settings = store.loadSettings()
            onParticipationRevoked()
        }
    }

    suspend fun refreshData(showSpinner: Boolean = true) {
        settings = store.loadSettings()
        if (settings.serverUrl.isBlank() || settings.displayName.isBlank()) {
            recordings = emptyList()
            totalRecordings = 0
            hasMore = false
            nextOffset = 0
            loading = false
            error = "Аввал танзими барномаро анҷом диҳед."
            return
        }
        if (showSpinner) loading = true
        error = ""
        try {
            val snapshot = ApiClient(settings).myData(offset = 0, limit = MY_DATA_PAGE_SIZE)
            recordings = snapshot.recordings
            totalRecordings = snapshot.total
            hasMore = snapshot.hasMore
            nextOffset = snapshot.nextOffset
            applyParticipationState(snapshot.consentActive)
        } catch (exception: Exception) {
            error = userFacingError(exception, "Маълумот гирифта нашуд. Баъдтар дубора кӯшиш кунед.")
        } finally {
            loading = false
        }
    }

    fun loadMore() {
        if (!hasMore || loadingMore) return
        scope.launch {
            loadingMore = true
            error = ""
            try {
                val snapshot = ApiClient(settings).myData(
                    offset = nextOffset,
                    limit = MY_DATA_PAGE_SIZE,
                )
                val known = recordings.mapTo(mutableSetOf()) { it.id }
                recordings = recordings + snapshot.recordings.filter { known.add(it.id) }
                totalRecordings = snapshot.total
                hasMore = snapshot.hasMore
                nextOffset = snapshot.nextOffset
                applyParticipationState(snapshot.consentActive)
            } catch (exception: Exception) {
                error = userFacingError(exception, "Сабтҳои дигар гирифта нашуданд.")
            } finally {
                loadingMore = false
            }
        }
    }

    fun playRecording(recording: OwnRecording) {
        if (playingId == recording.id) {
            stopPlayer()
            return
        }
        scope.launch {
            audioBusyId = recording.id
            error = ""
            stopPlayer()
            try {
                val bytes = ApiClient(settings).ownRecordingAudio(recording.id)
                player = MediaPlayer().apply {
                    setDataSource(ByteArrayMediaDataSource(bytes))
                    setOnCompletionListener { stopPlayer() }
                    setOnErrorListener { _, _, _ ->
                        error = "Аудио кушода нашуд."
                        stopPlayer()
                        true
                    }
                    prepare()
                    start()
                }
                playingId = recording.id
            } catch (exception: Exception) {
                error = userFacingError(exception, "Аудио гирифта нашуд.")
            } finally {
                audioBusyId = null
            }
        }
    }

    val saveRecordingLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("audio/wav"),
    ) { uri ->
        val recordingId = pendingDownloadId
        pendingDownloadId = null
        if (uri != null && recordingId != null) {
            scope.launch {
                downloadBusyId = recordingId
                error = ""
                try {
                    val bytes = ApiClient(settings).ownRecordingAudio(recordingId)
                    val output = context.contentResolver.openOutputStream(uri)
                        ?: throw IOException("output unavailable")
                    output.use {
                        it.write(bytes)
                        it.flush()
                    }
                    snackbar.showSnackbar("Сабт шуд")
                } catch (exception: Exception) {
                    error = userFacingError(exception, "Сабт боргирӣ нашуд.")
                } finally {
                    downloadBusyId = null
                }
            }
        }
    }

    LaunchedEffect(Unit) { refreshData() }
    DisposableEffect(Unit) { onDispose { stopPlayer() } }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        containerColor = MaterialTheme.colorScheme.background,
    ) { scaffoldPadding ->
        Column(
            modifier = Modifier
                .padding(scaffoldPadding)
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (onBack != null) {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Бозгашт")
                    }
                } else {
                    Icon(
                        Icons.Default.PrivacyTip,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                    )
                    Spacer(Modifier.width(12.dp))
                }
                Text("Маълумоти ман", fontSize = 28.sp, fontWeight = FontWeight.Black)
            }

            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(22.dp),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                ),
            ) {
                Column(
                    modifier = Modifier.padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("Овози шумо зери назорати шумост", fontWeight = FontWeight.ExtraBold)
                    Text(
                        "Сабтҳои фиристодаи шумо дар компютери лоиҳаи Tajik‑STT нигоҳ дошта мешаванд. " +
                            "Шумо метавонед онҳоро дар ин ҷо бинед, гӯш кунед, боргирӣ кунед ё ҳазф намоед.",
                    )
                    Text(
                        "Ҳазф кардани сабти аслӣ онро аз нигоҳдории сервер ва маҷмӯаҳои оянда хориҷ мекунад. " +
                            "Агар он қаблан барои омӯзиши модели анҷомёфта истифода шуда бошад, ҳазфи WAV " +
                            "омӯзиши анҷомёфтаро худкор барнамегардонад.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            OutlinedCard(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Нусхаи маҳаллӣ", fontWeight = FontWeight.ExtraBold)
                        Text(
                            "Пас аз фиристодани сабти овоз, нусха дар телефон нигоҳ дошта мешавад.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    IconButton(onClick = { showLocalCopyInfo = true }) {
                        Icon(
                            Icons.Default.Info,
                            contentDescription = "Маълумоти бештар",
                            tint = MaterialTheme.colorScheme.primary,
                        )
                    }
                    Switch(
                        checked = keepLocalCopies,
                        onCheckedChange = { enabled ->
                            store.saveKeepLocalCopies(enabled)
                            keepLocalCopies = enabled
                        },
                    )
                }
            }

            if (!consentActive || settings.participationRevoked) {
                OutlinedCard(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(18.dp),
                ) {
                    Text(
                        "Иштироки шумо боздошта шудааст. Сабтҳои мавҷударо ҳоло ҳам метавонед " +
                            "гӯш кунед, боргирӣ кунед ё ҳазф намоед; онҳо ба экспортҳои нави омӯзишӣ дохил намешаванд.",
                        modifier = Modifier.padding(16.dp),
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }

            if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)

            when {
                loading -> {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 48.dp),
                        horizontalArrangement = Arrangement.Center,
                    ) { CircularProgressIndicator() }
                }
                recordings.isEmpty() -> {
                    Text(
                        "Ҳоло дар сервер сабти фиристодаи шумо нест.",
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 28.dp),
                        textAlign = TextAlign.Center,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                else -> {
                    Text(
                        "Сабтҳои ман: ${recordings.size} аз $totalRecordings",
                        fontSize = 21.sp,
                        fontWeight = FontWeight.ExtraBold,
                    )
                    recordings.forEach { recording ->
                        OwnRecordingCard(
                            recording = recording,
                            playing = playingId == recording.id,
                            busy = actionBusy ||
                                audioBusyId == recording.id ||
                                downloadBusyId == recording.id,
                            onPlay = { playRecording(recording) },
                            onDownload = {
                                pendingDownloadId = recording.id
                                saveRecordingLauncher.launch("${recording.id}.wav")
                            },
                            onDelete = { recordingToDelete = recording },
                        )
                    }
                }
            }

            if (hasMore) {
                OutlinedButton(
                    onClick = ::loadMore,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !loadingMore && !actionBusy,
                ) {
                    if (loadingMore) {
                        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                    } else {
                        Text("Дигар сабтҳо")
                    }
                }
            }

            OutlinedButton(
                onClick = { scope.launch { refreshData() } },
                modifier = Modifier.fillMaxWidth(),
                enabled = !actionBusy,
            ) {
                Icon(Icons.Default.Refresh, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Нав кардан")
            }

            Button(
                onClick = { confirmDeleteAll = true },
                modifier = Modifier.fillMaxWidth(),
                enabled = (totalRecordings > 0 || store.pendingCount() > 0) && !actionBusy,
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer,
                ),
            ) {
                Icon(Icons.Default.Delete, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Ҳазфи ҳамаи сабтҳои ман")
            }

            if (consentActive && !settings.participationRevoked) {
                Text(
                    "Бозпас гирифтани розигӣ фиристодан ва истифодаи ояндаи сабтҳои шуморо қатъ мекунад. " +
                        "Сабтҳои серверӣ то вақте ки шумо онҳоро ҳазф накунед, барои идора ва боргирӣ нигоҳ дошта мешаванд. " +
                        "Сабтҳои ҳанӯз нафиристода дар ҳамин телефон мемонанд ва то аз нав оғоз кардани иштирок фиристода намешаванд.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(
                    onClick = { confirmRevoke = true },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !actionBusy,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer,
                        contentColor = MaterialTheme.colorScheme.onErrorContainer,
                    ),
                ) {
                    Icon(Icons.Default.PrivacyTip, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Бозпас гирифтани розигӣ")
                }
            }

            Spacer(Modifier.height(20.dp))
        }
    }

    if (showLocalCopyInfo) {
        AlertDialog(
            onDismissRequest = { showLocalCopyInfo = false },
            title = { Text("Нусхаи маҳаллӣ") },
            text = {
                Text(
                    "То фиристодан ҳамаи сабтҳо ба ҳар ҳол дар ҷузвдони хусусии барнома дар телефон нигоҳ дошта мешаванд. " +
                        "Ин гузариш танҳо муайян мекунад, ки баъд аз фиристодани муваффақ нусхаи WAV боқӣ монад ё не. " +
                        "Дар Android 10+ нусхаҳои нигоҳдошта дар Downloads/Tajik-STT пайдо мешаванд. " +
                        "Хомӯш кардани гузариш нусхаҳои қаблан нигоҳдоштаро худкор ҳазф намекунад.",
                )
            },
            confirmButton = {
                TextButton(onClick = { showLocalCopyInfo = false }) { Text("Фаҳмо") }
            },
        )
    }

    recordingToDelete?.let { recording ->
        AlertDialog(
            onDismissRequest = { if (!actionBusy) recordingToDelete = null },
            title = { Text("Сабт ҳазф шавад?") },
            text = {
                Text("Файли аслии ин сабт аз сервер ҳазф мешавад ва дар экспортҳои оянда истифода намешавад.")
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        scope.launch {
                            actionBusy = true
                            error = ""
                            stopPlayer()
                            try {
                                ApiClient(settings).deleteOwnRecording(recording.id)
                                recordingToDelete = null
                                refreshData(showSpinner = false)
                                snackbar.showSnackbar("Сабт ҳазф шуд")
                            } catch (exception: Exception) {
                                error = userFacingError(exception, "Сабт ҳазф нашуд.")
                            } finally {
                                actionBusy = false
                            }
                        }
                    },
                ) { Text("Ҳазф кардан", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { recordingToDelete = null }) { Text("Бекор кардан") }
            },
        )
    }

    if (confirmDeleteAll) {
        AlertDialog(
            onDismissRequest = { if (!actionBusy) confirmDeleteAll = false },
            title = { Text("Ҳамаи сабтҳо ҳазф шаванд?") },
            text = {
                Text(
                    "Ҳамаи WAV-ҳои шумо аз сервер ва сабтҳои ҳанӯз нафиристода аз навбати ин телефон ҳазф мешаванд. " +
                        "Ин амал баргардонида намешавад.",
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        scope.launch {
                            actionBusy = true
                            error = ""
                            stopPlayer()
                            try {
                                val deleted = ApiClient(settings).deleteAllOwnRecordings()
                                val localDeleted = store.clearPendingRecordings()
                                confirmDeleteAll = false
                                refreshData(showSpinner = false)
                                snackbar.showSnackbar("Сабтҳо ҳазф шуданд: сервер $deleted, телефон $localDeleted")
                            } catch (exception: Exception) {
                                error = userFacingError(exception, "Сабтҳо ҳазф нашуданд.")
                            } finally {
                                actionBusy = false
                            }
                        }
                    },
                ) { Text("Ҳамаашро ҳазф кардан", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { confirmDeleteAll = false }) { Text("Бекор кардан") }
            },
        )
    }

    if (confirmRevoke) {
        AlertDialog(
            onDismissRequest = { if (!actionBusy) confirmRevoke = false },
            title = { Text("Розигӣ бозпас гирифта шавад?") },
            text = {
                Text(
                    "Пас аз ин барнома дигар сабт, матн ё санҷиши нав намефиристад. " +
                        "Сабтҳои ҳанӯз нафиристода аз телефон ҳазф намешаванд ва то аз нав оғоз кардани иштирок фиристода намешаванд. " +
                        "Сабтҳои сервериро метавонед баъдан аз ҳамин бахш боргирӣ ё ҳазф кунед.",
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        scope.launch {
                            actionBusy = true
                            error = ""
                            try {
                                ApiClient(settings).revokeConsent()
                                UploadWorker.cancel(context)
                                store.markParticipationRevoked()
                                settings = store.loadSettings()
                                consentActive = false
                                confirmRevoke = false
                                snackbar.showSnackbar("Розигӣ бозпас гирифта шуд")
                                onParticipationRevoked()
                            } catch (exception: Exception) {
                                error = userFacingError(exception, "Розигӣ бозпас гирифта нашуд.")
                            } finally {
                                actionBusy = false
                            }
                        }
                    },
                ) { Text("Бозпас гирифтан", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { confirmRevoke = false }) { Text("Бекор кардан") }
            },
        )
    }
}

@Composable
private fun OwnRecordingCard(
    recording: OwnRecording,
    playing: Boolean,
    busy: Boolean,
    onPlay: () -> Unit,
    onDownload: () -> Unit,
    onDelete: () -> Unit,
) {
    OutlinedCard(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(statusLabel(recording.status), fontWeight = FontWeight.ExtraBold)
                Text(
                    formatServerDate(recording.createdAt),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(recording.text, fontSize = 18.sp, lineHeight = 26.sp)
            Text(
                "Давомнокӣ: ${formatDuration(recording.durationMs)} · ${recording.sampleRate} Hz",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(
                    onClick = onPlay,
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                ) {
                    Icon(
                        if (playing) Icons.Default.PauseCircle else Icons.Default.PlayCircle,
                        contentDescription = null,
                    )
                    Spacer(Modifier.width(5.dp))
                    Text(if (playing) "Қатъ" else "Гӯш")
                }
                OutlinedButton(
                    onClick = onDownload,
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                ) {
                    Icon(Icons.Default.Download, contentDescription = null)
                    Spacer(Modifier.width(5.dp))
                    Text("Боргирӣ")
                }
                IconButton(onClick = onDelete, enabled = !busy) {
                    Icon(
                        Icons.Default.Delete,
                        contentDescription = "Ҳазф кардан",
                        tint = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }
}

private fun statusLabel(status: String): String = when (status) {
    "approved" -> "Қабулшуда"
    "rejected" -> "Радшуда"
    else -> "Дар санҷиш"
}

private fun formatDuration(durationMs: Long): String =
    String.format(java.util.Locale.US, "%.1f сония", durationMs.coerceAtLeast(0) / 1000.0)

private fun formatServerDate(value: String): String {
    if (value.isBlank()) return ""
    return value.replace('T', ' ').removeSuffix("Z").take(16)
}
