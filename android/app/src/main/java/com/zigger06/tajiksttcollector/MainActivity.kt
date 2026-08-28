package com.zigger06.tajiksttcollector

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PrivacyTip
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import com.zigger06.tajiksttcollector.data.UploadWorker
import com.zigger06.tajiksttcollector.network.ApiClient
import com.zigger06.tajiksttcollector.ui.CollectorApp
import com.zigger06.tajiksttcollector.ui.MyDataScreen
import com.zigger06.tajiksttcollector.ui.theme.TajikCollectorTheme
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
            var showMyData by remember { mutableStateOf(participationRevoked) }
            var keepLocalCopies by remember { mutableStateOf(store.keepLocalCopies()) }
            var confirmResume by remember { mutableStateOf(false) }
            var resumeBusy by remember { mutableStateOf(false) }
            var resumeError by remember { mutableStateOf("") }

            // Stage-2 migration safety: a pre-auth install can already look fully
            // configured after LocalStore generates its first device secret, while
            // the server still has only the legacy volunteer row and no credential.
            // Claim that legacy row once, silently, before relying on authenticated
            // routes. Failure is non-destructive and is retried on a later app start.
            LaunchedEffect(initialSettings) {
                val migrationKey = "device_credential_bootstrapped_v1"
                val needsBootstrap = initialSettings.isConfigured &&
                    !migrationPreferences.getBoolean(migrationKey, false)
                if (needsBootstrap) {
                    try {
                        ApiClient(initialSettings).registerVolunteer()
                        migrationPreferences.edit().putBoolean(migrationKey, true).apply()
                        // Recreate CollectorApp so a stats request that raced with the
                        // one-time bootstrap is retried using the now-bound credential.
                        credentialBootstrapEpoch++
                    } catch (_: Exception) {
                        // Preserve offline-first behavior. Do not mark success; the
                        // next app start will retry the safe idempotent migration.
                    }
                }
            }

            BackHandler(enabled = showMyData) {
                // My Data is a normal in-app screen, including after consent is
                // withdrawn. System Back must never dump the user out of the app.
                showMyData = false
            }

            SideEffect {
                WindowCompat.getInsetsController(window, window.decorView).apply {
                    isAppearanceLightStatusBars = !darkTheme
                    isAppearanceLightNavigationBars = !darkTheme
                }
            }
            TajikCollectorTheme(darkTheme = darkTheme) {
                Box(modifier = Modifier.fillMaxSize()) {
                    if (showMyData) {
                        Column(modifier = Modifier.fillMaxSize()) {
                            Box(modifier = Modifier.weight(1f)) {
                                MyDataScreen(
                                    store = store,
                                    onBack = { showMyData = false },
                                    onParticipationRevoked = {
                                        participationRevoked = true
                                        showMyData = true
                                    },
                                )
                            }

                            OutlinedCard(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .navigationBarsPadding()
                                    .padding(horizontal = 12.dp, vertical = 8.dp),
                            ) {
                                Column(
                                    modifier = Modifier.padding(14.dp),
                                    verticalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Column(modifier = Modifier.weight(1f)) {
                                            Text(
                                                "Нусхаи маҳаллӣ",
                                                fontWeight = FontWeight.Bold,
                                            )
                                            Text(
                                                "Пас аз фиристодан нусхаи WAV-ро дар телефон нигоҳ доред.",
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant,
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
                                    Text(
                                        "То фиристодан ҳамаи сабтҳо ба ҳар ҳол дар ҷузвдони хусусии барнома " +
                                            "маҳаллӣ мемонанд. Ин гузариш танҳо нусхаи баъди фиристоданро нигоҳ медорад. " +
                                            "Дар Android 10+ нусхаҳо дар Downloads/Tajik-STT пайдо мешаванд. " +
                                            "Хомӯш кардани гузариш нусхаҳои қаблан нигоҳдоштаро худкор ҳазф намекунад.",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )

                                    if (participationRevoked) {
                                        Button(
                                            onClick = { confirmResume = true },
                                            modifier = Modifier.fillMaxWidth(),
                                            enabled = !resumeBusy,
                                        ) {
                                            Text("Иштирокро аз нав оғоз кардан")
                                        }
                                        if (resumeError.isNotBlank()) {
                                            Text(
                                                resumeError,
                                                color = MaterialTheme.colorScheme.error,
                                                style = MaterialTheme.typography.bodySmall,
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    } else {
                        key(credentialBootstrapEpoch) {
                            CollectorApp(
                                store = store,
                                darkTheme = darkTheme,
                                onDarkThemeChange = { enabled ->
                                    store.saveDarkTheme(enabled)
                                    darkTheme = enabled
                                },
                            )
                        }
                        ExtendedFloatingActionButton(
                            onClick = { showMyData = true },
                            modifier = Modifier
                                .align(Alignment.BottomEnd)
                                .padding(end = 18.dp, bottom = 22.dp),
                            icon = {
                                Icon(Icons.Default.PrivacyTip, contentDescription = null)
                            },
                            text = { Text("Маълумоти ман") },
                        )
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
                                    "экспортҳои ояндаи Tajik-STT истифода шаванд. Агар инро намехоҳед, " +
                                    "он сабтҳоро пеш аз идома ҳазф кунед.",
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
                                            resumeError = error.message
                                                ?: "Иштирок аз нав оғоз нашуд."
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
