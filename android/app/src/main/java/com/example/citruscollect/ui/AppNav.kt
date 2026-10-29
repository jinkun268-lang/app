package com.example.citruscollect.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.example.citruscollect.ui.screens.BatchesScreen
import com.example.citruscollect.ui.screens.CaptureHomeScreen
import com.example.citruscollect.ui.screens.CaptureSessionScreen
import com.example.citruscollect.ui.screens.ConfirmScreen
import com.example.citruscollect.ui.screens.LoginScreen
import com.example.citruscollect.ui.screens.QuestionScreen
import com.example.citruscollect.ui.screens.RecordsScreen
import com.example.citruscollect.ui.theme.CitrusColors
import kotlinx.coroutines.launch

@Composable
fun AppNav() {
    val container = LocalAppContainer.current
    val token by container.sessionStore.token.collectAsState(initial = null)
    val ownerKey by container.authRepository.ownerKey.collectAsState(initial = null)

    if (token == null) {
        LoginScreen()
    } else if (ownerKey != null) {
        key(ownerKey) { MainNav() }
    }
}

private val TABS = listOf(
    Triple("capture", "◎", "采集"),
    Triple("records", "▦", "图片记录"),
    Triple("batches", "▤", "采集批次"),
    Triple("questions", "?", "专家咨询")
)

@Composable
private fun MainNav() {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val nav = rememberNavController()
    val backStack by nav.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    val tabRoute = when {
        route?.startsWith("confirm") == true -> "records"
        else -> route
    }

    fun openTab(target: String) {
        nav.navigate(target) {
            launchSingleTop = true
            popUpTo("capture") { saveState = true }
            restoreState = true
        }
    }

    Scaffold(
        containerColor = CitrusColors.Screen,
        bottomBar = {
            if (route in setOf("capture", "records", "batches", "questions")) {
                Column(Modifier.background(CitrusColors.White).navigationBarsPadding()) {
                    HorizontalDivider(color = CitrusColors.Line)
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        TABS.forEach { (key, icon, label) ->
                            val active = tabRoute == key
                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                modifier = Modifier.weight(1f).clickable { openTab(key) }.padding(vertical = 4.dp)
                            ) {
                                Box(
                                    Modifier.clip(RoundedCornerShape(10.dp))
                                        .background(if (active) Color(0xFFE8EFE4) else Color.Transparent)
                                        .padding(horizontal = 16.dp, vertical = 5.dp),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Text(icon, fontSize = 16.sp,
                                        color = if (active) CitrusColors.Green else Color(0xFF94A08F))
                                }
                                Text(label, fontSize = 10.sp,
                                    fontWeight = if (active) FontWeight.Bold else FontWeight.Normal,
                                    color = if (active) CitrusColors.Green else Color(0xFF94A08F),
                                    modifier = Modifier.padding(top = 3.dp))
                            }
                        }
                    }
                }
            }
        }
    ) { padding ->
        NavHost(
            navController = nav,
            startDestination = "capture",
            modifier = Modifier.padding(padding)
        ) {
            composable("capture") {
                CaptureHomeScreen(
                    onStartCapture = { nav.navigate("shoot") },
                    onOpenRecords = { openTab("records") },
                    onOpenBatches = { openTab("batches") }
                )
            }
            composable("records") {
                RecordsScreen(
                    onOpenRecord = { nav.navigate("confirm/$it") },
                    onCapture = { nav.navigate("shoot") },
                    onOpenBatches = { openTab("batches") },
                    onLogout = { scope.launch { container.authRepository.logout() } }
                )
            }
            composable("questions") { QuestionScreen() }
            composable("batches") {
                BatchesScreen(onCapture = { nav.navigate("shoot") })
            }
            composable(
                "shoot?retakeSample={retakeSample}&retake={retake}",
                arguments = listOf(
                    navArgument("retakeSample") { type = NavType.StringType; nullable = true; defaultValue = null },
                    navArgument("retake") { type = NavType.StringType; nullable = true; defaultValue = null }
                )
            ) { entry ->
                val retakeSample = entry.arguments?.getString("retakeSample")?.takeIf { it.isNotBlank() }
                CaptureSessionScreen(
                    retakeSampleId = retakeSample,
                    retakeImageId = entry.arguments?.getString("retake")?.takeIf { it.isNotBlank() },
                    onCaptured = { nav.popBackStack() },
                    onOpenRecord = { nav.navigate("confirm/$it") },
                    onDone = { nav.popBackStack() },
                    onBack = { nav.popBackStack() }
                )
            }
            composable("confirm/{sampleId}") { entry ->
                ConfirmScreen(
                    sampleId = entry.arguments?.getString("sampleId").orEmpty(),
                    onOpenRecord = { nav.navigate("confirm/$it") },
                    onRecordDeleted = {
                        if (!nav.popBackStack("records", false)) nav.popBackStack("capture", false)
                    },
                    onBack = { nav.popBackStack() },
                    onRetake = { imageId ->
                        val sampleId = entry.arguments?.getString("sampleId").orEmpty()
                        nav.navigate("shoot?retakeSample=$sampleId" + (imageId?.let { "&retake=$it" } ?: ""))
                    },
                    onSaved = {
                        if (!nav.popBackStack("records", false)) {
                            nav.navigate("records") { popUpTo("capture") { inclusive = false } }
                        }
                    }
                )
            }
        }
    }
}
