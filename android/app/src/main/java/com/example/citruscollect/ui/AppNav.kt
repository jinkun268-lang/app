package com.example.citruscollect.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.example.citruscollect.ui.screens.CaptureScreen
import com.example.citruscollect.ui.screens.CollectionHomeScreen
import com.example.citruscollect.ui.screens.ConfirmScreen
import com.example.citruscollect.ui.screens.LoginScreen
import com.example.citruscollect.ui.screens.QuestionScreen
import com.example.citruscollect.ui.screens.UploadScreen

@Composable
fun AppNav() {
    val container = LocalAppContainer.current
    val token by container.sessionStore.token.collectAsState(initial = null)

    if (token == null) {
        LoginScreen()
    } else {
        MainNav()
    }
}

@Composable
private fun MainNav() {
    val nav = rememberNavController()
    val backStack by nav.currentBackStackEntryAsState()
    val route = backStack?.destination?.route

    Scaffold(
        bottomBar = {
            if (route in setOf("collection", "question")) {
                NavigationBar {
                    NavigationBarItem(
                        selected = route == "collection",
                        onClick = { nav.navigate("collection") { popUpTo("collection") { inclusive = true } } },
                        icon = { Text("采", fontWeight = FontWeight.Bold) },
                        label = { Text("采集") }
                    )
                    NavigationBarItem(
                        selected = route == "question",
                        onClick = { nav.navigate("question") { popUpTo("question") { inclusive = true } } },
                        icon = { Text("问", fontWeight = FontWeight.Bold) },
                        label = { Text("提问") }
                    )
                }
            }
        }
    ) { padding ->
        NavHost(
            navController = nav,
            startDestination = "collection",
            modifier = Modifier.padding(padding)
        ) {
            composable("collection") {
                CollectionHomeScreen(
                    onStartCapture = { nav.navigate("capture/$it") },
                    onOpenUploads = { nav.navigate("uploads") }
                )
            }
            composable("question") { QuestionScreen() }
            composable("capture/{sampleId}") { entry ->
                CaptureScreen(
                    sampleId = entry.arguments?.getString("sampleId").orEmpty(),
                    onDone = { nav.navigate("confirm/$it") },
                    onBack = { nav.popBackStack() }
                )
            }
            composable("confirm/{sampleId}") { entry ->
                ConfirmScreen(
                    sampleId = entry.arguments?.getString("sampleId").orEmpty(),
                    onBack = { nav.popBackStack() },
                    onSaved = {
                        // 保存后去待传列表，而不是回相机死循环。
                        nav.navigate("uploads") { popUpTo("collection") }
                    }
                )
            }
            composable("uploads") { UploadScreen(onBack = { nav.popBackStack() }, onOpenDraft = { nav.navigate("capture/$it") }) }
        }
    }
}
