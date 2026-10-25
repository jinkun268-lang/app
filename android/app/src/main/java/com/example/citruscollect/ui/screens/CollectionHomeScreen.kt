package com.example.citruscollect.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.citruscollect.ui.LocalAppContainer
import kotlinx.coroutines.launch

@Composable
fun CollectionHomeScreen(
    onStartCapture: (String) -> Unit,
    onOpenUploads: () -> Unit
) {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val pendingCount by container.repository.observePendingCount().collectAsState(initial = 0)

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("待上传：$pendingCount")
        Spacer(Modifier.height(24.dp))
        Button(
            onClick = {
                scope.launch {
                    val id = container.repository.createSample("unknown", "leaf", "unknown")
                    onStartCapture(id)
                }
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("开始采集")
        }
        Spacer(Modifier.height(12.dp))
        OutlinedButton(onClick = onOpenUploads, modifier = Modifier.fillMaxWidth()) {
            Text("查看待上传")
        }
        Spacer(Modifier.height(12.dp))
        OutlinedButton(
            onClick = { scope.launch { container.authRepository.logout() } },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("退出登录")
        }
    }
}
