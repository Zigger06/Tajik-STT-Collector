package com.zigger06.tajiksttcollector.ui

import android.Manifest
import android.content.pm.PackageManager
import android.media.MediaPlayer
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.EditNote
import androidx.compose.material.icons.filled.FactCheck
import androidx.compose.material.icons.filled.Headphones
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.PauseCircle
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.StopCircle
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.zigger06.tajiksttcollector.audio.RecordingResult
import com.zigger06.tajiksttcollector.audio.WavRecorder
import com.zigger06.tajiksttcollector.data.AppSettings
import com.zigger06.tajiksttcollector.data.AudioReviewTask
import com.zigger06.tajiksttcollector.data.LocalStore
import com.zigger06.tajiksttcollector.data.PendingRecording
import com.zigger06.tajiksttcollector.data.TextTask
import com.zigger06.tajiksttcollector.data.UploadWorker
import com.zigger06.tajiksttcollector.data.VolunteerStats
import com.zigger06.tajiksttcollector.network.ApiClient
import com.zigger06.tajiksttcollector.network.ServerConfig
import kotlinx.coroutines.launch
import java.io.File
import java.util.UUID

private enum class Screen { HOME, SETUP, RECORD, TEXT_REVIEW, AUDIO_REVIEW }

private const val PRIVACY_URL = "https://zigger06.github.io/Tajik-STT-Collector/privacy.html"
private const val TERMS_URL = "https://zigger06.github.io/Tajik-STT-Collector/terms.html"

@Composable
fun CollectorApp(store: LocalStore) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }
    var settings by remember { mutableStateOf(store.loadSettings()) }
    var screen by rememberSaveable {
        mutableStateOf(if (settings.isConfigured) Screen.HOME else Screen.SETUP)
    }
    var pendingCount by remember { mutableIntStateOf(store.pendingCount()) }
    var volunteerStats by remember {
        mutableStateOf(VolunteerStats(store.cachedSubmittedCount(), 0, 0, 0))
    }

    LaunchedEffect(screen, pendingCount) {
        if (screen == Screen.HOME) {
            pendingCount = store.pendingCount()
            if (settings.isConfigured) {
                try {
                    volunteerStats = ApiClient(settings).volunteerStats()
                    store.saveSubmittedCount(volunteerStats.submitted)
                } catch (_: Exception) {
                    volunteerStats = volunteerStats.copy(
                        submitted = store.cachedSubmittedCount(),
                    )
                }
            }
        }
    }

    BackHandler(enabled = screen != Screen.HOME && settings.isConfigured) {
        screen = Screen.HOME
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        containerColor = MaterialTheme.colorScheme.background,
    ) { scaffoldPadding ->
        when (screen) {
            Screen.HOME -> HomeScreen(
                modifier = Modifier.padding(scaffoldPadding),
                pendingCount = pendingCount,
                volunteerStats = volunteerStats,
                onRecord = { screen = Screen.RECORD },
                onTextReview = { screen = Screen.TEXT_REVIEW },
                onAudioReview = { screen = Screen.AUDIO_REVIEW },
                onSettings = { screen = Screen.SETUP },
                onRetryUpload = {
                    UploadWorker.schedule(context)
                    scope.launch { snackbar.showSnackbar("Фиристодан дар замина оғоз шуд.") }
                },
            )

            Screen.SETUP -> SetupScreen(
                modifier = Modifier.padding(scaffoldPadding),
                initial = settings,
                canGoBack = settings.isConfigured,
                onBack = { screen = Screen.HOME },
                onSave = { candidate ->
                    scope.launch {
                        try {
                            val configured = candidate.copy(
                                serverUrl = ServerConfig.resolve(candidate.serverUrl),
                            )
                            val api = ApiClient(configured)
                            check(api.checkHealth()) { "Сервер ҷавоб надод." }
                            api.registerVolunteer()
                            store.saveSettings(configured)
                            settings = configured
                            UploadWorker.schedule(context)
                            screen = Screen.HOME
                            snackbar.showSnackbar("Пайвастшавӣ муваффақ шуд.")
                        } catch (error: Exception) {
                            snackbar.showSnackbar(error.message ?: "Пайвастшавӣ нашуд.")
                        }
                    }
                },
            )

            Screen.RECORD -> RecordingScreen(
                modifier = Modifier.padding(scaffoldPadding),
                settings = settings,
                store = store,
                onBack = { screen = Screen.HOME },
                onQueueChanged = { pendingCount = store.pendingCount() },
                showMessage = { scope.launch { snackbar.showSnackbar(it) } },
            )

            Screen.TEXT_REVIEW -> TextReviewScreen(
                modifier = Modifier.padding(scaffoldPadding),
                settings = settings,
                onBack = { screen = Screen.HOME },
                showMessage = { scope.launch { snackbar.showSnackbar(it) } },
            )

            Screen.AUDIO_REVIEW -> AudioReviewScreen(
                modifier = Modifier.padding(scaffoldPadding),
                settings = settings,
                onBack = { screen = Screen.HOME },
                showMessage = { scope.launch { snackbar.showSnackbar(it) } },
            )
        }
    }
}

@Composable
private fun HomeScreen(
    modifier: Modifier,
    pendingCount: Int,
    volunteerStats: VolunteerStats,
    onRecord: () -> Unit,
    onTextReview: () -> Unit,
    onAudioReview: () -> Unit,
    onSettings: () -> Unit,
    onRetryUpload: () -> Unit,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text("Садои тоҷикӣ", fontSize = 30.sp, fontWeight = FontWeight.Black)
                Text(
                    "Барои сохтани Tajik‑STT саҳм гузоред",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onSettings) {
                Icon(Icons.Default.Settings, contentDescription = "Танзимот")
            }
        }

        Spacer(Modifier.height(4.dp))
        OutlinedCard(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(20.dp),
        ) {
            Column(
                modifier = Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("Омори ман", fontSize = 20.sp, fontWeight = FontWeight.ExtraBold)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    StatisticValue("Ҳамагӣ", volunteerStats.submitted + pendingCount)
                    StatisticValue("Фиристода", volunteerStats.submitted)
                    StatisticValue("Дар навбат", pendingCount)
                }
                Text(
                    "Дар санҷиш: ${volunteerStats.pendingReview} · Қабулшуда: ${volunteerStats.approved}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        ActionCard(
            icon = Icons.Default.Mic,
            title = "Сабти овоз",
            subtitle = "Матнро хонед ва овози худро сабт кунед",
            onClick = onRecord,
            emphasized = true,
        )
        ActionCard(
            icon = Icons.Default.FactCheck,
            title = "Санҷиши матн",
            subtitle = "Дурустӣ ва имлои матнҳоро санҷед",
            onClick = onTextReview,
        )
        ActionCard(
            icon = Icons.Default.Headphones,
            title = "Санҷиши сабт",
            subtitle = "Аудиоро гӯш карда, ба он баҳо диҳед",
            onClick = onAudioReview,
        )

        if (pendingCount > 0) {
            OutlinedCard(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Default.CloudUpload, contentDescription = null)
                    Spacer(Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Дар навбат: $pendingCount сабт", fontWeight = FontWeight.Bold)
                        Text(
                            "Ҳангоми пайдо шудани пайвастшавӣ фиристода мешавад.",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    IconButton(onClick = onRetryUpload) {
                        Icon(Icons.Default.Refresh, contentDescription = "Такрор")
                    }
                }
            }
        }
    }
}

@Composable
private fun StatisticValue(label: String, value: Int) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value.toString(), fontSize = 25.sp, fontWeight = FontWeight.Black)
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ActionCard(
    icon: ImageVector,
    title: String,
    subtitle: String,
    onClick: () -> Unit,
    emphasized: Boolean = false,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(22.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (emphasized) MaterialTheme.colorScheme.primaryContainer
            else MaterialTheme.colorScheme.surface,
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
    ) {
        Row(
            modifier = Modifier.padding(20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(52.dp),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    icon,
                    contentDescription = null,
                    modifier = Modifier.size(34.dp),
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
            Spacer(Modifier.width(14.dp))
            Column {
                Text(title, fontSize = 20.sp, fontWeight = FontWeight.ExtraBold)
                Spacer(Modifier.height(3.dp))
                Text(subtitle, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun SetupScreen(
    modifier: Modifier,
    initial: AppSettings,
    canGoBack: Boolean,
    onBack: () -> Unit,
    onSave: (AppSettings) -> Unit,
) {
    var displayName by remember(initial) { mutableStateOf(initial.displayName) }
    var region by remember(initial) { mutableStateOf(initial.region) }
    var dialect by remember(initial) { mutableStateOf(initial.dialect) }
    var consent by remember(initial) { mutableStateOf(initial.consent) }
    val uriHandler = LocalUriHandler.current

    ScreenColumn(modifier) {
        ScreenHeader("Танзими аввал", onBack.takeIf { canGoBack })
        Text(
            "Номи худро ворид кунед ва барои сабт, санҷиши матн ва санҷиши аудио саҳм гузоред.",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = displayName,
            onValueChange = { displayName = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Ном ё рамзи шумо") },
            supportingText = { Text("Барои махфият метавонед тахаллус истифода баред") },
            singleLine = true,
        )
        OutlinedTextField(
            value = region,
            onValueChange = { region = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Минтақа") },
            singleLine = true,
        )
        OutlinedTextField(
            value = dialect,
            onValueChange = { dialect = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Лаҳҷа (ихтиёрӣ)") },
            singleLine = true,
        )
        Row(verticalAlignment = Alignment.Top) {
            Checkbox(checked = consent, onCheckedChange = { consent = it })
            Text(
                "Ман 18-сола ё калонтар ҳастам, Сиёсати махфият ва Шартҳои истифодаро хондам ва барои истифодаи сабтҳои овозам дар таҳқиқ ва омӯзиши Tajik‑STT розӣ ҳастам.",
                modifier = Modifier.padding(top = 12.dp),
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            TextButton(
                onClick = { uriHandler.openUri(PRIVACY_URL) },
                modifier = Modifier.weight(1f),
            ) {
                Text("Сиёсати махфият")
            }
            TextButton(
                onClick = { uriHandler.openUri(TERMS_URL) },
                modifier = Modifier.weight(1f),
            ) {
                Text("Шартҳои истифода")
            }
        }
        Button(
            onClick = {
                onSave(
                    initial.copy(
                        displayName = displayName.trim(),
                        region = region.trim(),
                        dialect = dialect.trim(),
                        consent = consent,
                    ),
                )
            },
            modifier = Modifier.fillMaxWidth(),
            enabled = displayName.trim().length >= 2 && consent,
        ) {
            Text("Оғоз кардан", modifier = Modifier.padding(vertical = 5.dp))
        }
    }
}

@Composable
private fun RecordingScreen(
    modifier: Modifier,
    settings: AppSettings,
    store: LocalStore,
    onBack: () -> Unit,
    onQueueChanged: () -> Unit,
    showMessage: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val recorder = remember { WavRecorder() }
    var task by remember { mutableStateOf<TextTask?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf("") }
    var isRecording by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<RecordingResult?>(null) }
    var recordingId by remember { mutableStateOf("") }
    var player by remember { mutableStateOf<MediaPlayer?>(null) }
    var sending by remember { mutableStateOf(false) }

    fun loadTask() {
        scope.launch {
            loading = true
            error = ""
            try {
                task = ApiClient(settings).recordingTask()
            } catch (exception: Exception) {
                error = exception.message ?: "Матн гирифта нашуд."
            } finally {
                loading = false
            }
        }
    }

    fun beginRecording() {
        try {
            player?.release()
            player = null
            result = null
            recordingId = UUID.randomUUID().toString()
            val file = File(context.filesDir, "recordings/$recordingId.wav")
            recorder.start(file)
            isRecording = true
            error = ""
        } catch (exception: Exception) {
            error = exception.message ?: "Сабт оғоз нашуд."
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) beginRecording() else error = "Иҷозати микрофон лозим аст."
    }

    LaunchedEffect(Unit) { loadTask() }
    DisposableEffect(Unit) {
        onDispose {
            if (recorder.isRecording) recorder.stop()
            player?.release()
        }
    }

    ScreenColumn(modifier) {
        ScreenHeader("Сабти овоз", onBack)
        when {
            loading -> LoadingBox()
            error.isNotBlank() && task == null -> ErrorBox(error, onRetry = ::loadTask)
            task == null -> EmptyBox("Ҳоло матни омода барои сабт нест.")
            else -> {
                val currentTask = task!!
                Text(
                    "Матнро ором, равшан ва бе илова хонед.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(22.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                ) {
                    Column(Modifier.padding(22.dp)) {
                        Text(
                            currentTask.content,
                            fontSize = 23.sp,
                            lineHeight = 34.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                        if (currentTask.source.isNotBlank()) {
                            Spacer(Modifier.height(14.dp))
                            Text(
                                "Манбаъ: ${currentTask.source}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }

                if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)

                Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                    FilledIconButton(
                        onClick = {
                            if (isRecording) {
                                result = recorder.stop()
                                isRecording = false
                                if ((result?.durationMs ?: 0L) < 500L) {
                                    error = "Сабт хеле кӯтоҳ аст. Аз нав сабт кунед."
                                }
                            } else {
                                val granted = ContextCompat.checkSelfPermission(
                                    context,
                                    Manifest.permission.RECORD_AUDIO,
                                ) == PackageManager.PERMISSION_GRANTED
                                if (granted) beginRecording()
                                else permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                            }
                        },
                        modifier = Modifier.size(86.dp),
                        shape = CircleShape,
                        colors = IconButtonDefaults.filledIconButtonColors(
                            containerColor = if (isRecording) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.primary,
                        ),
                    ) {
                        Icon(
                            if (isRecording) Icons.Default.StopCircle else Icons.Default.Mic,
                            contentDescription = null,
                            modifier = Modifier.size(48.dp),
                        )
                    }
                }
                Text(
                    if (isRecording) "Қатъ кардан" else if (result == null) "Оғози сабт" else "Аз нав сабт кардан",
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.Center,
                    fontWeight = FontWeight.Bold,
                )

                result?.let { recording ->
                    OutlinedButton(
                        onClick = {
                            player?.release()
                            player = MediaPlayer().apply {
                                setDataSource(recording.file.absolutePath)
                                prepare()
                                start()
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Default.PlayCircle, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Гӯш кардан (${recording.durationMs / 1000.0} сония)")
                    }
                    Button(
                        onClick = {
                            val pending = PendingRecording(
                                id = recordingId,
                                textId = currentTask.id,
                                filePath = recording.file.absolutePath,
                                durationMs = recording.durationMs,
                                sampleRate = recording.sampleRate,
                            )
                            store.addPending(pending)
                            onQueueChanged()
                            sending = true
                            scope.launch {
                                try {
                                    val api = ApiClient(settings)
                                    api.registerVolunteer()
                                    api.uploadRecording(pending)
                                    store.removePending(pending.id)
                                    recording.file.delete()
                                    onQueueChanged()
                                    showMessage("Сабт фиристода шуд. Раҳмат!")
                                    result = null
                                    task = null
                                    loadTask()
                                } catch (_: Exception) {
                                    UploadWorker.schedule(context)
                                    showMessage("Сабт дар телефон нигоҳ дошта шуд ва баъдтар фиристода мешавад.")
                                    onBack()
                                } finally {
                                    sending = false
                                }
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = recording.durationMs >= 500 && !sending,
                    ) {
                        if (sending) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                        else Icon(Icons.Default.Save, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Нигоҳ доштан ва фиристодан")
                    }
                }
            }
        }
    }
}

@Composable
private fun TextReviewScreen(
    modifier: Modifier,
    settings: AppSettings,
    onBack: () -> Unit,
    showMessage: (String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var task by remember { mutableStateOf<TextTask?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf("") }
    var correction by remember { mutableStateOf("") }
    var editMode by remember { mutableStateOf(false) }

    fun loadTask() {
        scope.launch {
            loading = true
            error = ""
            editMode = false
            correction = ""
            try { task = ApiClient(settings).textReviewTask() }
            catch (exception: Exception) { error = exception.message ?: "Матн гирифта нашуд." }
            finally { loading = false }
        }
    }

    fun submit(verdict: String) {
        val current = task ?: return
        scope.launch {
            loading = true
            try {
                ApiClient(settings).submitTextReview(current.id, verdict, correction)
                showMessage("Санҷиш қабул шуд. Раҳмат!")
                task = null
                loadTask()
            } catch (exception: Exception) {
                error = exception.message ?: "Санҷиш фиристода нашуд."
                loading = false
            }
        }
    }

    LaunchedEffect(Unit) { loadTask() }
    ScreenColumn(modifier) {
        ScreenHeader("Санҷиши матн", onBack)
        when {
            loading -> LoadingBox()
            error.isNotBlank() && task == null -> ErrorBox(error, ::loadTask)
            task == null -> EmptyBox("Ҳоло матне барои санҷиш нест.")
            else -> {
                val current = task!!
                Text("Имло, калимаҳо ва маънои ҷумлаҳоро санҷед.")
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(22.dp),
                ) {
                    Column(Modifier.padding(22.dp)) {
                        Text(current.content, fontSize = 23.sp, lineHeight = 34.sp)
                        if (current.source.isNotBlank()) {
                            Spacer(Modifier.height(12.dp))
                            Text("Манбаъ: ${current.source}", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
                if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)
                if (editMode) {
                    OutlinedTextField(
                        value = correction,
                        onValueChange = { correction = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Матни дуруст") },
                        minLines = 3,
                    )
                    Button(
                        onClick = { submit("correction") },
                        enabled = correction.trim().length >= 3,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Фиристодани ислоҳ") }
                } else {
                    Button(onClick = { submit("correct") }, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Default.CheckCircle, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Дуруст аст")
                    }
                    OutlinedButton(
                        onClick = { correction = current.content; editMode = true },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Default.EditNote, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Ислоҳ кардан")
                    }
                    TextButton(onClick = { submit("reject") }, modifier = Modifier.fillMaxWidth()) {
                        Text("Матн номувофиқ аст", color = MaterialTheme.colorScheme.error)
                    }
                }
            }
        }
    }
}

@Composable
private fun AudioReviewScreen(
    modifier: Modifier,
    settings: AppSettings,
    onBack: () -> Unit,
    showMessage: (String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var task by remember { mutableStateOf<AudioReviewTask?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf("") }
    var reason by remember { mutableStateOf("") }
    var player by remember { mutableStateOf<MediaPlayer?>(null) }
    var playing by remember { mutableStateOf(false) }

    fun stopPlayer() {
        player?.release()
        player = null
        playing = false
    }

    fun loadTask() {
        scope.launch {
            stopPlayer()
            loading = true
            error = ""
            reason = ""
            try { task = ApiClient(settings).audioReviewTask() }
            catch (exception: Exception) { error = exception.message ?: "Сабт гирифта нашуд." }
            finally { loading = false }
        }
    }

    fun submit(verdict: String) {
        val current = task ?: return
        scope.launch {
            loading = true
            stopPlayer()
            try {
                ApiClient(settings).submitAudioReview(current.id, verdict, reason)
                showMessage("Баҳо қабул шуд. Раҳмат!")
                task = null
                loadTask()
            } catch (exception: Exception) {
                error = exception.message ?: "Баҳо фиристода нашуд."
                loading = false
            }
        }
    }

    LaunchedEffect(Unit) { loadTask() }
    DisposableEffect(Unit) { onDispose { stopPlayer() } }

    ScreenColumn(modifier) {
        ScreenHeader("Санҷиши сабт", onBack)
        when {
            loading -> LoadingBox()
            error.isNotBlank() && task == null -> ErrorBox(error, ::loadTask)
            task == null -> EmptyBox("Ҳоло сабте барои санҷиш нест.")
            else -> {
                val current = task!!
                Text("Аудиоро гӯш кунед ва онро бо матн муқоиса намоед.")
                Card(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(22.dp)) {
                    Text(
                        current.text,
                        modifier = Modifier.padding(22.dp),
                        fontSize = 22.sp,
                        lineHeight = 32.sp,
                    )
                }
                Button(
                    onClick = {
                        if (playing) stopPlayer()
                        else {
                            error = ""
                            player = MediaPlayer().apply {
                                setDataSource(current.audioUrl)
                                setOnPreparedListener { media -> media.start(); playing = true }
                                setOnCompletionListener { stopPlayer() }
                                setOnErrorListener { _, _, _ ->
                                    error = "Аудио кушода нашуд."
                                    stopPlayer()
                                    true
                                }
                                prepareAsync()
                            }
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(
                        if (playing) Icons.Default.PauseCircle else Icons.Default.PlayCircle,
                        contentDescription = null,
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(if (playing) "Қатъ кардан" else "Гӯш кардан")
                }
                if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)
                OutlinedTextField(
                    value = reason,
                    onValueChange = { reason = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Сабаби рад (ихтиёрӣ)") },
                    minLines = 2,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(
                        onClick = { submit("reject") },
                        modifier = Modifier.weight(1f),
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.error),
                    ) { Text("Рад кардан", color = MaterialTheme.colorScheme.error) }
                    Button(
                        onClick = { submit("approve") },
                        modifier = Modifier.weight(1f),
                    ) { Text("Қабул кардан") }
                }
            }
        }
    }
}

@Composable
private fun ScreenColumn(modifier: Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
        content = content,
    )
}

@Composable
private fun ScreenHeader(title: String, onBack: (() -> Unit)?) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        if (onBack != null) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Бозгашт")
            }
        } else {
            Icon(Icons.Default.Home, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(12.dp))
        }
        Text(title, fontSize = 27.sp, fontWeight = FontWeight.Black)
    }
}

@Composable
private fun LoadingBox() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(220.dp),
        contentAlignment = Alignment.Center,
    ) { CircularProgressIndicator() }
}

@Composable
private fun EmptyBox(message: String) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 70.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(
            Icons.Default.CheckCircle,
            contentDescription = null,
            modifier = Modifier.size(54.dp),
            tint = MaterialTheme.colorScheme.primary,
        )
        Text(message, textAlign = TextAlign.Center, fontSize = 18.sp)
    }
}

@Composable
private fun ErrorBox(message: String, onRetry: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 50.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Icon(
            Icons.Default.Warning,
            contentDescription = null,
            modifier = Modifier.size(48.dp),
            tint = MaterialTheme.colorScheme.error,
        )
        Text(message, textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.error)
        OutlinedButton(onClick = onRetry) {
            Icon(Icons.Default.Refresh, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Такрор кардан")
        }
    }
}
