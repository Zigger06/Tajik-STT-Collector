package com.zigger06.tajiksttcollector

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PrivacyTip
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import com.zigger06.tajiksttcollector.data.LocalStore
import com.zigger06.tajiksttcollector.ui.CollectorApp
import com.zigger06.tajiksttcollector.ui.MyDataScreen
import com.zigger06.tajiksttcollector.ui.theme.TajikCollectorTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        setContent {
            val store = remember { LocalStore(applicationContext) }
            val initialSettings = remember { store.loadSettings() }
            var darkTheme by remember { mutableStateOf(store.isDarkTheme()) }
            var participationRevoked by remember {
                mutableStateOf(initialSettings.participationRevoked)
            }
            var showMyData by remember { mutableStateOf(participationRevoked) }

            SideEffect {
                WindowCompat.getInsetsController(window, window.decorView).apply {
                    isAppearanceLightStatusBars = !darkTheme
                    isAppearanceLightNavigationBars = !darkTheme
                }
            }
            TajikCollectorTheme(darkTheme = darkTheme) {
                Box(modifier = Modifier.fillMaxSize()) {
                    if (showMyData) {
                        MyDataScreen(
                            store = store,
                            onBack = if (participationRevoked) null else ({ showMyData = false }),
                            onParticipationRevoked = {
                                participationRevoked = true
                                showMyData = true
                            },
                        )
                    } else {
                        CollectorApp(
                            store = store,
                            darkTheme = darkTheme,
                            onDarkThemeChange = { enabled ->
                                store.saveDarkTheme(enabled)
                                darkTheme = enabled
                            },
                        )
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
            }
        }
    }
}
