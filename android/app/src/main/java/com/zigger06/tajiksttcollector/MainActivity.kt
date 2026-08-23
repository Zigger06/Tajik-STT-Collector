package com.zigger06.tajiksttcollector

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.core.view.WindowCompat
import com.zigger06.tajiksttcollector.data.LocalStore
import com.zigger06.tajiksttcollector.ui.CollectorApp
import com.zigger06.tajiksttcollector.ui.theme.TajikCollectorTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        setContent {
            val store = remember { LocalStore(applicationContext) }
            var darkTheme by remember { mutableStateOf(store.isDarkTheme()) }
            SideEffect {
                WindowCompat.getInsetsController(window, window.decorView).apply {
                    isAppearanceLightStatusBars = !darkTheme
                    isAppearanceLightNavigationBars = !darkTheme
                }
            }
            TajikCollectorTheme(darkTheme = darkTheme) {
                CollectorApp(
                    store = store,
                    darkTheme = darkTheme,
                    onDarkThemeChange = { enabled ->
                        store.saveDarkTheme(enabled)
                        darkTheme = enabled
                    },
                )
            }
        }
    }
}
