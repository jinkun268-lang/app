package com.example.citruscollect.ui

import androidx.compose.runtime.staticCompositionLocalOf
import com.example.citruscollect.AppContainer

val LocalAppContainer = staticCompositionLocalOf<AppContainer> {
    error("AppContainer not provided")
}
