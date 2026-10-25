package com.example.citruscollect.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.citruscollect.ui.LocalAppContainer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

@Composable
fun UploadScreen(onBack: () -> Unit, onOpenDraft: (String) -> Unit) {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val pending by container.repository.observePending().collectAsState(initial = emptyList())
    var uploadingId by remember { mutableStateOf<String?>(null) }
    var message by remember { mutableStateOf<String?>(null) }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Row(modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp)) {
            OutlinedButton(onClick = onBack) { Text("返回") }
        }
        if (message != null) {
            Text(message.orEmpty(), color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(bottom = 8.dp))
        }
        LazyColumn(modifier = Modifier.weight(1f)) {
            items(pending) { s ->
                Row(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                    verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("${s.sampleId.take(8)} · ${s.uploadState}")
                        s.uploadError?.let {
                            Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    Button(
                        enabled = uploadingId == null,
                        onClick = {
                            scope.launch {
                                if (s.uploadState == "draft") {
                                    onOpenDraft(s.sampleId)
                                    return@launch
                                }
                                uploadingId = s.sampleId
                                message = null
                                try {
                                    val outcome = container.repository.upload(s.sampleId)
                                    message = "上传完成：${outcome.sampleId.take(8)}（${outcome.imageCount} 图）"
                                } catch (e: CancellationException) {
                                    // 取消不是业务失败：仓库已把对象恢复到可重试状态，不显示为错误
                                    throw e
                                } catch (e: Exception) {
                                    message = e.message ?: "上传失败"
                                } finally {
                                    uploadingId = null
                                }
                            }
                        }
                    ) {
                        Text(if (uploadingId == s.sampleId) "上传中…" else if (s.uploadState == "draft") "继续采集" else "上传")
                    }
                }
            }
        }
    }
}
