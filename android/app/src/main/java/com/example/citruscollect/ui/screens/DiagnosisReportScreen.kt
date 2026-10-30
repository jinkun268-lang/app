package com.example.citruscollect.ui.screens

import android.app.DatePickerDialog
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.citruscollect.data.diagnosis.result
import com.example.citruscollect.ui.LocalAppContainer
import com.example.citruscollect.ui.theme.CitrusColors
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import java.time.LocalDate

@Composable
fun DiagnosisReportScreen(id: String, onBack: () -> Unit, onNewPhoto: () -> Unit, onCollectionRecord: (String) -> Unit) {
    val container = LocalAppContainer.current
    val context = LocalContext.current
    val repo = container.diagnosisRepository
    val row by repo.observe(id).collectAsState(initial = null)
    val batches by container.repository.observeBatches().collectAsState(initial = emptyList())
    val scope = rememberCoroutineScope()
    var contribution by remember { mutableStateOf(false) }
    var selectedBatch by remember { mutableStateOf("") }
    var agreed by remember { mutableStateOf(false) }
    var contributing by remember { mutableStateOf(false) }
    var editFollow by remember { mutableStateOf(false) }
    var followDate by remember { mutableStateOf("") }
    var observation by remember { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }
    val record = row
    if (record == null) {
        Column(Modifier.padding(24.dp)) { TextButton(onClick = onBack) { Text("返回") }; Text("正在读取本账号的识别记录…") }
        return
    }
    val result = record.result()
    val working = record.status in setOf("analyzing", "advice_loading")
    fun request(adviceOnly: Boolean) {
        container.appScope.launch {
            try { if (adviceOnly) repo.retryAdvice(id) else repo.analyze(id) }
            catch (e: CancellationException) { throw e }
            catch (_: Exception) { /* 失败保存在记录中 */ }
        }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            TextButton(onClick = onBack) { Text("返回") }
            TextButton(onClick = onNewPhoto) { Text("重新拍一张") }
        }
        ScreenTitle("识别报告", displayDate(record.createdAt))
        AppSection {
            DiagnosisPhoto(record.imagePath)
            if (working) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                Text(if (record.status == "advice_loading") "正在获取处理建议…" else "正在识别照片，请稍候…")
                Text("你可以离开本页，结果会保存在“我的记录”。", color = CitrusColors.Muted, style = MaterialTheme.typography.bodySmall)
            }
            record.error?.let { Text(it, color = CitrusColors.Red) }
            if (result == null && !working) {
                Text(if (record.status == "draft") "照片已保存，尚未识别" else "本次未能完成识别", style = MaterialTheme.typography.titleMedium)
                Text("图片仍保存在本机。检查网络或等待服务可用后，可以重试。", color = CitrusColors.Muted)
                Button(onClick = { request(false) }, modifier = Modifier.fillMaxWidth()) { Text(if (record.status == "draft") "发送图片并识别" else "重试识别") }
            }
            result?.recognition?.let { recognition ->
                Text("识别结果", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                recognition.candidates.sortedByDescending { it.score }.forEach { candidate ->
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(candidate.name, modifier = Modifier.weight(1f))
                        Text("${(candidate.score * 100).toInt()}%", color = CitrusColors.Green)
                    }
                    LinearProgressIndicator(progress = { candidate.score.toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                }
                Text("分数代表模型匹配程度，不是确诊概率。", style = MaterialTheme.typography.bodySmall, color = CitrusColors.Muted)
                if (recognition.warning.isNotBlank()) Text(recognition.warning, style = MaterialTheme.typography.bodySmall, color = CitrusColors.Muted)
            }
        }
        result?.advice?.let { advice ->
            AppSection {
                Text("接下来怎么做", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text(advice.title, style = MaterialTheme.typography.titleMedium)
                Text(advice.message, color = CitrusColors.Muted)
                // 非匹配状态不显示上次的针对性方案。
                if (advice.status == "matched" && record.status !in setOf("failed", "advice_failed")) {
                    advice.actions.forEachIndexed { index, action ->
                        Text("${index + 1}. ${action.title}", fontWeight = FontWeight.Bold)
                        Text(action.detail, style = MaterialTheme.typography.bodyMedium)
                    }
                }
                if (advice.status in setOf("unavailable", "unmapped") || record.status == "advice_failed") {
                    OutlinedButton(onClick = { request(true) }, enabled = !working) { Text("重新获取建议") }
                }
                if (advice.status in setOf("uncertain", "conflict")) {
                    OutlinedButton(onClick = onNewPhoto) { Text("补拍清晰照片") }
                }
                advice.sources.forEach { source ->
                    val uri = Uri.parse(source.url)
                    if (uri.scheme in setOf("http", "https")) TextButton(onClick = {
                        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, uri)) }.onFailure { message = "暂时无法打开参考资料" }
                    }) { Text("参考资料：${source.title}", style = MaterialTheme.typography.bodySmall) }
                }
                Button(onClick = {
                    followDate = record.followUpDate ?: LocalDate.now().plusDays(3).toString()
                    observation = record.observation; editFollow = true
                }, enabled = !working, modifier = Modifier.fillMaxWidth()) { Text(if (record.followUpDate == null) "安排后续观察" else "记录后续观察") }
            }
        }
        if (record.followUpDate != null || record.observation.isNotBlank()) AppSection {
            Text("后续观察", style = MaterialTheme.typography.titleMedium)
            record.followUpDate?.let { Text("观察日期：$it") }
            Text(record.observation.ifBlank { "尚未填写观察情况" }, color = CitrusColors.Muted)
            Text("日期仅作记录，不会发送系统通知。", style = MaterialTheme.typography.bodySmall, color = CitrusColors.Muted)
        }
        AppSection {
            Text("现场信息", style = MaterialTheme.typography.titleMedium)
            Text("${mapOf("huyou" to "胡柚", "xiangyou" to "香柚", "citrus" to "其他柑橘")[record.cropId]} · ${mapOf("leaf" to "叶片", "fruit" to "果实", "branch" to "枝条")[record.part]} · ${mapOf("young" to "幼树", "adult" to "成龄树", "unknown" to "树龄不清楚")[record.treeAge]}")
            if (record.symptom.isNotBlank()) Text(record.symptom, color = CitrusColors.Muted)
        }
        if (result != null) AppSection {
            Text("愿意将这次观察用于采集吗？", style = MaterialTheme.typography.titleMedium)
            Text("需要单独同意并选择批次。模型判断只作线索，不会自动成为训练标签。", color = CitrusColors.Muted, style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = {
                val sample = record.contributedSampleId
                if (sample != null) onCollectionRecord(sample) else { selectedBatch = batches.firstOrNull { !it.closed }?.batchId.orEmpty(); agreed = false; contribution = true }
            }, enabled = !working, modifier = Modifier.fillMaxWidth()) { Text(if (record.contributedSampleId == null) "选择批次并转入采集" else "查看已转入的采集记录") }
        }
        message?.let { Text(it, color = CitrusColors.Green) }
    }
    if (contribution) AlertDialog(onDismissRequest = { if (!contributing) contribution = false }, title = { Text("自愿转入数据采集") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (batches.none { !it.closed }) Text("请先到数据采集新建或重新开启一个批次，再回来选择。")
            else {
                ChoiceField("选择未关闭的批次", batches.filter { !it.closed }.map { it.batchId to it.name }, selectedBatch, { selectedBatch = it }, !contributing)
                Row { Checkbox(checked = agreed, onCheckedChange = { agreed = it }, enabled = !contributing); Text("同意将图片与现场信息转入采集，供人工审核。", style = MaterialTheme.typography.bodySmall) }
            }
        }
    }, confirmButton = { TextButton(enabled = agreed && selectedBatch.isNotBlank() && !contributing, onClick = {
        scope.launch {
            contributing = true
            try { val sample = repo.contribute(id, selectedBatch); contribution = false; onCollectionRecord(sample) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { message = e.message ?: "转入失败，请重试"; contribution = false }
            finally { contributing = false }
        }
    }) { Text(if (contributing) "正在保存…" else "同意并转入") } }, dismissButton = { TextButton(onClick = { contribution = false }, enabled = !contributing) { Text("取消") } })
    if (editFollow) AlertDialog(onDismissRequest = { editFollow = false }, title = { Text("后续观察") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedButton(onClick = {
                val d = runCatching { LocalDate.parse(followDate) }.getOrDefault(LocalDate.now().plusDays(3))
                DatePickerDialog(context, { _, y, m, day -> followDate = LocalDate.of(y, m + 1, day).toString() }, d.year, d.monthValue - 1, d.dayOfMonth).show()
            }) { Text("观察日期：$followDate") }
            OutlinedTextField(value = observation, onValueChange = { observation = it.take(1000) }, label = { Text("现场变化（可稍后补充）") }, modifier = Modifier.fillMaxWidth())
            Text("记录新梢、受影响范围与上次相比的变化。", style = MaterialTheme.typography.bodySmall)
        }
    }, confirmButton = { TextButton(onClick = {
        scope.launch {
            try { repo.saveFollowUp(id, followDate, observation); editFollow = false; message = "观察记录已保存在本机" }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { message = e.message ?: "保存失败"; editFollow = false }
        }
    }) { Text("保存") } }, dismissButton = { TextButton(onClick = { editFollow = false }) { Text("取消") } })
}
