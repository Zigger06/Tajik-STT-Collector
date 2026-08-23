package com.zigger06.tajiksttcollector.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
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

private val CollectorDarkColors = darkColorScheme(
    primary = Color(0xFF82D5C8),
    onPrimary = Color(0xFF003731),
    primaryContainer = Color(0xFF005047),
    onPrimaryContainer = Color(0xFF9FF2E5),
    secondary = Color(0xFFB1CCC6),
    background = Color(0xFF0E1514),
    onBackground = Color(0xFFE0E4E2),
    surface = Color(0xFF151D1B),
    onSurface = Color(0xFFE0E4E2),
    surfaceVariant = Color(0xFF3F4946),
    onSurfaceVariant = Color(0xFFBEC9C5),
    error = Color(0xFFFFB4AB),
)

@Composable
fun TajikCollectorTheme(
    darkTheme: Boolean = false,
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) CollectorDarkColors else CollectorColors,
        content = content,
    )
}
