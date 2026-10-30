package com.example.citruscollect.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** 与设计稿一致的取色板：米白纸感背景 + 深绿主色 + 赭色提示。 */
object CitrusColors {
    val Ink = Color(0xFF183A2B)
    val Green = Color(0xFF17664F)
    val GreenSoft = Color(0xFFEDF2E9)
    val Soft = Color(0xFFEDF3ED)
    val Paper = Color(0xFFF3F1E9)
    val Screen = Color(0xFFEDF3F0)
    val Line = Color(0xFFE4E9E1)
    val Muted = Color(0xFF7C877C)
    val Faint = Color(0xFF98A08F)
    val Orange = Color(0xFFC66B37)
    val OrangeSoft = Color(0xFFFBEFE3)
    val Red = Color(0xFFB34D42)
    val RedSoft = Color(0xFFFBEFE7)
    val White = Color.White
}

@Composable
fun CitrusTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = CitrusColors.Green,
            onPrimary = CitrusColors.White,
            primaryContainer = CitrusColors.GreenSoft,
            onPrimaryContainer = CitrusColors.Ink,
            secondaryContainer = CitrusColors.GreenSoft,
            onSecondaryContainer = CitrusColors.Ink,
            background = CitrusColors.Paper,
            onBackground = CitrusColors.Ink,
            surface = CitrusColors.White,
            onSurface = CitrusColors.Ink,
            surfaceVariant = CitrusColors.GreenSoft,
            onSurfaceVariant = CitrusColors.Muted,
            outline = CitrusColors.Line,
            outlineVariant = CitrusColors.Line,
            error = CitrusColors.Red
        ),
        content = content
    )
}
