package com.zigger06.tajiksttcollector

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.LightMode
import androidx.compose.material.icons.filled.PrivacyTip
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import com.zigger06.tajiksttcollector.data.LocalStore
import com.zigger06.tajiksttcollector.data.RECORDING_TASK_CACHE_TARGET
import com.zigger06.tajiksttcollector.data.UploadWorker
import com.zigger06.tajiksttcollector.network.ApiClient
import com.zigger06.tajiksttcollector.network.ServerConfig
import com.zigger06.tajiksttcollector.ui.CollectorApp
import com.zigger06.tajiksttcollector.ui.MyDataScreen
import com.zigger06.tajiksttcollector.ui.SnakeGameScreen
import com.zigger06.tajiksttcollector.ui.theme.TajikCollectorTheme
import com.zigger06.tajiksttcollector.ui.userFacingError
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        setContent {
            val store = remember { LocalStore(applicationContext) }
            val initialSettings = remember { store.loadSettings() }
            val migrationPreferences = remember {
                getSharedPreferences("collector_settings", MODE_PRIVATE)
            }
            val scope = rememberCoroutineScope()
            var credentialBootstrapEpoch by remember { mutableIntStateOf(0) }
            var darkTheme by remember { mutableStateOf(store.isDarkTheme()) }
            var participationRevoked by remember {
                mutableStateOf(initialSettings.participationRevoked)
            }
            var showMyData by remember { mutableStateOf(false) }
            var showSnakeGame by remember { mutableStateOf(false) }
            var confirmResume by remember { mutableStateOf(false) }
            var resumeBusy by remember { mutableStateOf(false) }
            var resumeError by remember { mutableStateOf("") }

            // Stage-2 migration safety: a pre-auth install can already look fully
            // configured after LocalStore generates its first device secret, while
            // the server still has only the legacy volunteer row and no credential.
            // Claim that legacy row once, silently, before relying on authenticated
            // routes. Failure is non-destructive and is retried on a later app start.
            //
            // This startup effect also repairs a stale saved server URL, resumes any
            // pending upload worker, and warms the recording-prompt cache. None of
            // these best-effort network actions block the home screen.
            LaunchedEffect(initialSettings) {
                var current = store.loadSettings()

                // Existing configured installs may still carry an older Funnel URL
                // in SharedPreferences. Resolve the current deployment on every app
                // start and recreate CollectorApp if the stored URL changed.
                if (current.isConfigured) {
                    try {
                        val resolvedUrl = ServerConfig.resolve(current.serverUrl)
                        if (resolvedUrl != current.serverUrl) {
                            current = current.copy(serverUrl = resolvedUrl)
                            store.saveSettings(current)
                            credentialBootstrapEpoch++
                        }
                    } catch (_: Exception) {
                        // Offline is normal; keep the last stored URL and local data.
                    }
                }

                val migrationKey = "device_credential_bootstrapped_v1"
                val needsBootstrap = current.isConfigured &&
                    !migrationPreferences.getBoolean(migrationKey, false)
                if (needsBootstrap) {
                    try {
                        ApiClient(current).registerVolunteer()
                        migrationPreferences.edit().putBoolean(migrationKey, true).apply()
                        credentialBootstrapEpoch++
                    } catch (_: Exception) {
                        // Preserve offline-first behavior. Do not mark success; the
                        // next app start will retry the safe idempotent migration.
                    }
                }

                current = store.loadSettings()
                ApiClient.seedRecordingTasks(current.volunteerId, store.cachedRecordingTasks())
                if (current.isConfigured && !current.participationRevoked) {
                    // WorkManager persists the queue across process/server restarts.
                    // Scheduling again is idempotent because the work is unique.
                    if (store.pendingRecordings().isNotEmpty()) {
                        UploadWorker.schedule(applicationContext)
                    }

                    val missing = (
                        RECORDING_TASK_CACHE_TARGET - store.cachedRecordingTaskCount()
                    ).coerceAtLeast(0)
                    if (missing > 0) {
                        try {
                            val excluded = (
                                store.pendingTextIds() + store.cachedRecordingTaskIds()
                            ).distinct()
                            val fresh = ApiClient(current).recordingTasks(missing, excluded)
                            store.cacheRecordingTasks(fresh)
                            ApiClient.seedRecordingTasks(
                                current.volunteerId,
                                store.cachedRecordingTasks(),
                            )
                        } catch (_: Exception) {
                            // Offline is normal: whatever was already cached remains
                            // immediately usable and the uploader will replenish later.
                        }
                    }
                }
            }

            BackHandler(enabled = showSnakeGame) {
                showSnakeGame = false
            }
            BackHandler(enabled = showMyData) {
                showMyData = false
            }

            SideEffect {
                WindowCompat.getInsetsController(window, window.decorView).apply {
                    isAppearanceLightStatusBars = !darkTheme
                    isAppearanceLightNavigationBars = !darkTheme
                }
            }

            TajikCollectorTheme(darkTheme = darkTheme) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(MaterialTheme.colorScheme.background),
                ) {
                    when {
                        showSnakeGame -> {
                            SnakeGameScreen(onBack = { showSnakeGame = false })
                        }

                        showMyData -> {
                            MyDataScreen(
                                store = store,
                                onBack = { showMyData = false },
                                onParticipationRevoked = {
                                    participationRevoked = true
                                    showMyData = false
                                },
                            )
                        }

                        participationRevoked -> {
                            ParticipationPausedScreen(
                                darkTheme = darkTheme,
                                resumeBusy = resumeBusy,
                                resumeError = resumeError,
                                onDarkThemeChange = { enabled ->
                                    store.saveDarkTheme(enabled)
                                    darkTheme = enabled
                                },
                                onMyData = { showMyData = true },
                                onResume = { confirmResume = true },
                            )
                        }

                        else -> {
                            key(credentialBootstrapEpoch) {
                                CollectorApp(
                                    store = store,
                                    darkTheme = darkTheme,
                                    onDarkThemeChange = { enabled ->
                                        store.saveDarkTheme(enabled)
                                        darkTheme = enabled
                                    },
                                    onGame = { showSnakeGame = true },
                                )
                            }
                            ExtendedFloatingActionButton(
                                onClick = { showMyData = true },
                                modifier = Modifier
                                    .align(Alignment.BottomEnd)
                                    .navigationBarsPadding()
                                    .padding(end = 18.dp, bottom = 14.dp),
                                icon = {
                                    Icon(Icons.Default.PrivacyTip, contentDescription = null)
                                },
                                text = { Text("Маълумоти ман") },
                            )
                        }
                    }
                }

                if (confirmResume) {
                    AlertDialog(
                        onDismissRequest = { if (!resumeBusy) confirmResume = false },
                        title = { Text("Иштирокро аз нав оғоз мекунед?") },
                        text = {
                            Text(
                                "Ин амал розигии шуморо дубора фаъол мекунад. Сабтҳои серверие, ки " +
                                    "пас аз боздошт ҳанӯз ҳазф нашудаанд, боз метавонанд барои санҷиш ва " +
                                    "экспортҳои ояндаи Tajik-STT истифода шаванд. Сабтҳои ҳанӯз " +
                                    "нафиристодаи телефон низ баъд аз идома метавонанд дар замина фиристода шаванд.",
                            )
                        },
                        confirmButton = {
                            TextButton(
                                enabled = !resumeBusy,
                                onClick = {
                                    scope.launch {
                                        resumeBusy = true
                                        resumeError = ""
                                        try {
                                            val current = store.loadSettings()
                                            val resumed = current.copy(
                                                consent = true,
                                                participationRevoked = false,
                                            )
                                            ApiClient(resumed).resumeConsent()
                                            store.markParticipationResumed()
                                            participationRevoked = false
                                            confirmResume = false
                                            UploadWorker.schedule(applicationContext)
                                            showMyData = false
                                        } catch (error: Exception) {
                                            resumeError = userFacingError(
                                                error,
                                                "Иштирок аз нав оғоз нашуд.",
                                            )
                                            confirmResume = false
                                        } finally {
                                            resumeBusy = false
                                        }
                                    }
                                },
                            ) { Text("Аз нав оғоз кардан") }
                        },
                        dismissButton = {
                            TextButton(
                                enabled = !resumeBusy,
                                onClick = { confirmResume = false },
                            ) { Text("Бекор кардан") }
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun ParticipationPausedScreen(
    darkTheme: Boolean,
    resumeBusy: Boolean,
    resumeError: String,
    onDarkThemeChange: (Boolean) -> Unit,
    onMyData: () -> Unit,
    onResume: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(22.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            "Иштирок боздошта шудааст",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Black,
        )
        Spacer(Modifier.height(10.dp))
        Text(
            "Сабт, иловаи матн ва санҷиш то вақте ки шумо розигиро дубора фаъол накунед, " +
                "фиристода намешаванд. Сабтҳои ҳанӯз нафиристода дар телефон нигоҳ дошта мешаванд. " +
                "Маълумоти мавҷудаи худро ҳамеша идора карда метавонед.",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(22.dp))
        Button(
            onClick = onResume,
            modifier = Modifier.fillMaxWidth(),
            enabled = !resumeBusy,
        ) {
            Text("Иштирокро аз нав оғоз кардан")
        }
        OutlinedButton(
            onClick = onMyData,
            modifier = Modifier.fillMaxWidth(),
            enabled = !resumeBusy,
        ) {
            Text("Маълумоти ман")
        }
        Spacer(Modifier.height(20.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                if (darkTheme) Icons.Default.DarkMode else Icons.Default.LightMode,
                contentDescription = if (darkTheme) "Мавзӯи торик" else "Мавзӯи равшан",
                tint = MaterialTheme.colorScheme.primary,
            )
            Spacer(Modifier.width(10.dp))
            Switch(checked = darkTheme, onCheckedChange = onDarkThemeChange)
        }
        if (resumeError.isNotBlank()) {
            Spacer(Modifier.height(10.dp))
            Text(
                resumeError,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
