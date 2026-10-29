package com.example.citruscollect.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.citruscollect.data.entity.BatchEntity
import com.example.citruscollect.data.entity.SampleEntity
import com.example.citruscollect.ui.LocalAppContainer
import com.example.citruscollect.ui.theme.CitrusColors
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 采集批次：承载一次外业采集的共同信息（地点、日期、采集人、默认品种）。
 * 批次可同步到服务端，也可恢复云端批次，图片保持独立记录。
 */
@Composable
fun BatchesScreen(onCapture: () -> Unit) {
    val container = LocalAppContainer.current
    val repository = container.repository
    val scope = rememberCoroutineScope()

    val batches by repository.observeBatches().collectAsState(initial = emptyList())
    val pending by repository.observePending().collectAsState(initial = emptyList())
    val uploaded by repository.observeUploaded().collectAsState(initial = emptyList())
    val all = remember(pending, uploaded) { (pending + uploaded).distinctBy { it.sampleId } }
    val username by container.sessionStore.username.collectAsState(initial = null)

    var cultivars by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    LaunchedEffect(Unit) {
        runCatching { container.authRepository.bootstrap() }.onSuccess { bootstrap ->
            cultivars = bootstrap.cultivars.filter { it.is_active }.associate { it.cultivar_id to it.name }
        }
    }

    var creating by remember { mutableStateOf(false) }
    var creatingBusy by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<BatchEntity?>(null) }
    var syncing by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }

    LazyColumn(Modifier.fillMaxSize().background(CitrusColors.Screen)) {
        item {
            Column(Modifier.padding(start = 18.dp, end = 18.dp, top = 14.dp, bottom = 14.dp)) {
                Text("采集批次", fontSize = 21.sp, fontWeight = FontWeight.Bold, color = CitrusColors.Ink)
                Text("按地点与时间整理图片", fontSize = 11.sp, color = CitrusColors.Muted,
                    modifier = Modifier.padding(top = 3.dp))
                Text(
                    "批次负责共同信息：地点、日期、采集人、默认品种。图片仍然各自独立成条。",
                    fontSize = 11.sp, color = CitrusColors.Faint, modifier = Modifier.padding(top = 10.dp)
                )
            }
        }

        item {
            Surface(
                color = CitrusColors.Green,
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp).clickable { message = null; creating = true }
            ) {
                Text("新建采集批次", fontSize = 12.sp, color = Color.White,
                    modifier = Modifier.padding(vertical = 12.dp), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            }
        }

        item {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("云端同步可在其他设备恢复批次", fontSize = 11.sp, modifier = Modifier.weight(1f))
                TextButton(enabled = !syncing, onClick = {
                    syncing = true
                    scope.launch {
                        try { message = "同步完成，共 ${repository.syncBatches()} 个云端批次" }
                        catch (e: CancellationException) { throw e }
                        catch (e: Exception) { message = e.message ?: "同步失败，本地批次已保留" }
                        finally { syncing = false }
                    }
                }) { Text(if (syncing) "同步中…" else "同步 / 恢复") }
            }
            message?.let { Text(it, color = CitrusColors.Green, modifier = Modifier.padding(horizontal = 18.dp)) }
        }
        if (batches.isEmpty()) {
            item {
                Column(Modifier.fillMaxWidth().padding(vertical = 48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("还没有采集批次", fontSize = 14.sp, color = CitrusColors.Muted)
                    Text("新建一个批次，再开始连续拍摄", fontSize = 11.sp, color = CitrusColors.Faint,
                        modifier = Modifier.padding(top = 6.dp))
                }
            }
        }

        val history = all.filter { it.batchId == null }
        if (history.isNotEmpty()) {
            item {
                BatchCard(
                    batch = BatchEntity(
                        batchId = "",
                        name = "历史记录",
                        place = "旧版本采集，未归入批次",
                        createdAt = history.minOf { it.createdAt }
                    ),
                    records = history,
                    current = container.batchId == null,
                    onClick = { container.batchId = null }
                )
            }
        }

        items(batches, key = { it.batchId }) { batch ->
            val records: List<SampleEntity> = all.filter { it.batchId == batch.batchId }
            BatchCard(
                batch = batch,
                records = records,
                current = container.batchId == batch.batchId,
                onClick = {
                    container.batchId = batch.batchId
                    message = if (batch.closed) "已选择关闭批次，可查看记录；重开后可继续采集" else "已切换到「${batch.name}」"
                },
                onEdit = { editing = batch },
                onToggleClosed = {
                    scope.launch {
                        try { repository.setBatchClosed(batch.batchId, !batch.closed) }
                        catch (e: CancellationException) { throw e }
                        catch (e: Exception) { message = e.message ?: "更新失败" }
                    }
                }
            )
        }

        item {
            Text(
                "— 共 ${batches.size} 个批次 —",
                fontSize = 10.sp, color = CitrusColors.Faint,
                modifier = Modifier.fillMaxWidth().padding(vertical = 20.dp),
                textAlign = androidx.compose.ui.text.style.TextAlign.Center
            )
        }
    }

    message?.let {
        LaunchedEffect(it) {
            kotlinx.coroutines.delay(2400)
            message = null
        }
    }

    editing?.let { target ->
        EditBatchDialog(target, cultivars, onDismiss = { editing = null }, onSave = { name, place, collector, cultivar, note ->
            scope.launch {
                try {
                    repository.updateBatch(target.batchId, name, place, collector, cultivar, note)
                    editing = null
                    message = "已保存，点击同步可更新云端"
                } catch (e: CancellationException) { throw e }
                catch (e: Exception) { message = e.message ?: "保存失败" }
            }
        })
    }
    if (creating) NewBatchDialog(
        collector = username.orEmpty(),
        cultivars = cultivars,
        error = message,
        busy = creatingBusy,
        onDismiss = { if (!creatingBusy) creating = false },
        onCreate = { name, place, cultivarId ->
            creatingBusy = true
            scope.launch {
                try {
                    val id = repository.createBatch(name, place, username.orEmpty(), cultivarId)
                    container.batchId = id
                    creating = false
                    onCapture()
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    message = e.message ?: "创建批次失败"
                } finally { creatingBusy = false }
            }
        }
    )
}

@Composable
private fun BatchCard(batch: BatchEntity, records: List<SampleEntity>, current: Boolean, onClick: () -> Unit, onEdit: (() -> Unit)? = null, onToggleClosed: (() -> Unit)? = null) {
    val uploaded = records.count { it.uploadState == "uploaded" }
    val pending = records.size - uploaded
    Surface(
        color = if (current) Color(0xFFF2F6EE) else CitrusColors.White,
        shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, if (current) Color(0xFF8FA987) else CitrusColors.Line),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp).clickable(onClick = onClick)
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(batch.name, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = CitrusColors.Ink)
                Spacer(Modifier.weight(1f))
                if (batch.closed) BatchPill("已关闭")
                if (current) BatchPill("当前")
            }
            Text(
                "${monthDay(dayOf(batch.createdAt))} · ${batch.place.ifBlank { "未填写地点" }}" +
                    (if (batch.collector.isNotBlank()) " · ${batch.collector}" else ""),
                fontSize = 11.sp, color = Color(0xFF8A9581), modifier = Modifier.padding(top = 5.dp)
            )
            Row(Modifier.padding(top = 15.dp), horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                CountItem(records.size, "图片")
                CountItem(uploaded, "已上传")
                CountItem(pending, "未上传")
            }
            if (onEdit != null) {
                Text(if (batch.syncPending) "本地已保存 · 待同步" else "已同步", fontSize = 10.sp, color = CitrusColors.Muted, modifier = Modifier.padding(top = 8.dp))
                Row {
                    TextButton(onClick = onEdit) { Text("编辑") }
                    TextButton(onClick = { onToggleClosed?.invoke() }) { Text(if (batch.closed) "重新开启" else "关闭批次") }
                }
            }
        }
    }
}

@Composable
private fun NewBatchDialog(
    collector: String,
    cultivars: Map<String, String>,
    error: String?,
    busy: Boolean,
    onDismiss: () -> Unit,
    onCreate: (String, String, String) -> Unit
) {
    var name by remember { mutableStateOf("") }
    var place by remember { mutableStateOf("") }
    var cultivar by remember { mutableStateOf(cultivars.keys.firstOrNull().orEmpty()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = CitrusColors.White,
        title = { Text("新建采集批次") },
        text = {
            Column {
                Text("批次承载地点、日期、采集人和默认品种；每张图片仍然独立成条。",
                    fontSize = 12.sp, color = CitrusColors.Muted, modifier = Modifier.padding(bottom = 12.dp))
                OutlinedTextField(
                    value = name, onValueChange = { name = it.take(128) },
                    label = { Text("批次名称", fontSize = 12.sp) },
                    placeholder = { Text("例如：胡柚园 · 上午采集", fontSize = 12.sp) },
                    singleLine = true, modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = place, onValueChange = { place = it.take(256) },
                    label = { Text("地点", fontSize = 12.sp) },
                    placeholder = { Text("例如：常山·青石镇 · A区", fontSize = 12.sp) },
                    singleLine = true, keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp)
                )
                Text("默认品种", fontSize = 11.sp, color = Color(0xFF65755B), modifier = Modifier.padding(top = 12.dp, bottom = 6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp),
                    modifier = Modifier.fillMaxWidth()
                        .horizontalScroll(androidx.compose.foundation.rememberScrollState())) {
                    cultivars.forEach { (id, label) ->
                        val active = id == cultivar
                        Surface(
                            color = if (active) CitrusColors.Green else CitrusColors.White,
                            shape = RoundedCornerShape(7.dp),
                            border = BorderStroke(1.dp, if (active) CitrusColors.Green else Color(0xFFDCE5D4)),
                            modifier = Modifier.clickable { cultivar = id }
                        ) {
                            Text(label, fontSize = 11.sp, color = if (active) Color.White else CitrusColors.Ink,
                                modifier = Modifier.padding(horizontal = 9.dp, vertical = 6.dp))
                        }
                    }
                }
                error?.let { Text(it, color = androidx.compose.material3.MaterialTheme.colorScheme.error) }
                if (collector.isNotBlank()) {
                    Text("采集人：$collector", fontSize = 11.sp, color = CitrusColors.Faint,
                        modifier = Modifier.padding(top = 12.dp))
                }
            }
        },
        confirmButton = {
            TextButton(enabled = name.isNotBlank() && !busy, onClick = { onCreate(name, place, cultivar.ifBlank { "unknown" }) }) {
                Text(if (busy) "创建中…" else "创建并开始拍摄")
            }
        },
        dismissButton = { TextButton(enabled = !busy, onClick = onDismiss) { Text("取消") } }
    )
}

@Composable
private fun BatchPill(text: String) {
    Surface(color = Color(0xFFE4EDDF), shape = RoundedCornerShape(4.dp)) {
        Text(text, fontSize = 10.sp, color = Color(0xFF68815A), modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp))
    }
}

@Composable
private fun CountItem(value: Int, label: String) {
    Row(verticalAlignment = Alignment.Bottom) {
        Text("$value", fontSize = 19.sp, fontWeight = FontWeight.Medium, color = CitrusColors.Ink)
        Text(label, fontSize = 11.sp, color = Color(0xFF79876D), modifier = Modifier.padding(start = 5.dp, bottom = 2.dp))
    }
}

private fun dayOf(millis: Long): String =
    SimpleDateFormat("yyyy-MM-dd", Locale.CHINA).format(Date(millis))

private fun monthDay(day: String): String = day.takeLast(5).replace("-", "月") + "日"

@Composable
private fun EditBatchDialog(batch: BatchEntity, cultivars: Map<String, String>, onDismiss: () -> Unit, onSave: (String, String, String, String, String) -> Unit) {
    var name by remember(batch.batchId) { mutableStateOf(batch.name) }
    var place by remember(batch.batchId) { mutableStateOf(batch.place) }
    var collector by remember(batch.batchId) { mutableStateOf(batch.collector) }
    var cultivar by remember(batch.batchId) { mutableStateOf(batch.defaultCultivarId) }
    var note by remember(batch.batchId) { mutableStateOf(batch.note) }
    AlertDialog(onDismissRequest = onDismiss, title = { Text("编辑采集批次") }, text = {
        Column(Modifier.verticalScroll(androidx.compose.foundation.rememberScrollState())) {
            OutlinedTextField(name, { name = it.take(128) }, label = { Text("批次名称") }, singleLine = true)
            OutlinedTextField(place, { place = it.take(256) }, label = { Text("地点") }, singleLine = true)
            OutlinedTextField(collector, { collector = it.take(128) }, label = { Text("采集人") }, singleLine = true)
            Text("默认品种", modifier = Modifier.padding(top = 8.dp))
            Row(Modifier.fillMaxWidth().horizontalScroll(androidx.compose.foundation.rememberScrollState())) {
                cultivars.forEach { (id, name) ->
                    androidx.compose.material3.FilterChip(selected = cultivar == id, onClick = { cultivar = id }, label = { Text(name) })
                }
            }
            OutlinedTextField(note, { note = it.take(500) }, label = { Text("备注") })
        }
    }, confirmButton = { TextButton(enabled = name.isNotBlank() && cultivar.isNotBlank(), onClick = { onSave(name, place, collector, cultivar, note) }) { Text("保存") } },
       dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } })
}
