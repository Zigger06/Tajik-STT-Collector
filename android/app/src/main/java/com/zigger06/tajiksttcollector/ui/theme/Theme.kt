package com.zigger06.tajiksttcollector.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val CollectorColors = lightColorScheme(
    primary = Color(0xFF087F72),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFC7F2EA),
    onPrimaryContainer = Color(0xFF063E38),
    secondary = Color(0xFF496B65),
    background = Color(0xFFF4FBF9),
    surface = Color(0xFFFFFFFF),
    surfaceVariant = Color(0xFFE3EEEB),
    error = Color(0xFFBA1A1A),
)

@Composable
fun TajikCollectorTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = CollectorColors,
        content = content,
    )
}
