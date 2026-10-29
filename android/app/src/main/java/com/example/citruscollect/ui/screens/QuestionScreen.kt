package com.example.citruscollect.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.citruscollect.util.UuidV7
import com.example.citruscollect.network.QuestionDto
import com.example.citruscollect.ui.LocalAppContainer
import com.example.citruscollect.ui.theme.CitrusColors
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

@Composable
fun QuestionScreen() {
    val container = LocalAppContainer.current
    val repository = container.repository
    val scope = rememberCoroutineScope()
    val uploaded by repository.observeUploaded().collectAsState(initial = emptyList())
    var text by rememberSaveable { mutableStateOf("") }
    var questionId by rememberSaveable { mutableStateOf(UuidV7.generate()) }
    var sampleId by rememberSaveable { mutableStateOf<String?>(null) }
    var questions by remember { mutableStateOf<List<QuestionDto>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var message by remember { mutableStateOf<String?>(null) }

    suspend fun refresh() {
        try { questions = repository.questions() }
        catch (e: CancellationException) { throw e }
        catch (e: Exception) { error = e.message ?: "问题列表加载失败，请重试" }
    }
    LaunchedEffect(Unit) { refresh() }

    LazyColumn(Modifier.fillMaxSize().background(CitrusColors.Screen).padding(16.dp)) {
        item {
            Text("专家咨询", style = androidx.compose.material3.MaterialTheme.typography.titleLarge)
            Text("描述现场情况，可关联已上传图片，由专家回复。", modifier = Modifier.padding(vertical = 8.dp))
            OutlinedTextField(text, { text = it.take(2000); questionId = UuidV7.generate() }, label = { Text("描述问题（${text.length}/2000）") }, minLines = 3,
                enabled = !busy, modifier = Modifier.fillMaxWidth())
            Text("关联图片（可选）", modifier = Modifier.padding(top = 8.dp))
            Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(selected = sampleId == null, onClick = { sampleId = null; questionId = UuidV7.generate() }, label = { Text("不关联") }, enabled = !busy)
                uploaded.forEach { sample ->
                    FilterChip(selected = sampleId == sample.sampleId, onClick = { sampleId = sample.sampleId; questionId = UuidV7.generate() },
                        label = { Text("IMG-${sample.sampleId.takeLast(4).uppercase()}") }, enabled = !busy)
                }
            }
            sampleId?.let { selected ->
                val photos by repository.imagesOf(selected).collectAsState(initial = emptyList())
                photos.firstOrNull()?.let { photo -> LocalPhoto(photo, Modifier.fillMaxWidth().height(160.dp).padding(vertical = 8.dp)) }
            }
            if (uploaded.isEmpty()) Text("上传采集记录后可附带该记录的图片。")
            error?.let { Text(it, color = androidx.compose.material3.MaterialTheme.colorScheme.error) }
            message?.let { Text(it, color = CitrusColors.Green) }
            Button(enabled = text.isNotBlank() && !busy, onClick = {
                busy = true; error = null; message = null
                scope.launch {
                    try {
                        val submitted = repository.submitQuestion(text.trim(), sampleId, questionId)
                        questions = listOf(submitted) + questions.filter { it.question_id != submitted.question_id }
                        text = ""; sampleId = null; questionId = UuidV7.generate(); message = "已提交，等待专家回复"
                    } catch (e: CancellationException) { throw e }
                    catch (e: Exception) { error = e.message ?: "提交失败，内容已保留，请重试" }
                    finally { busy = false }
                }
            }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) { Text(if (busy) "提交中…" else "提交咨询") }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("我的咨询", modifier = Modifier.padding(top = 12.dp))
                TextButton(enabled = !busy, onClick = {
                    scope.launch { busy = true; error = null; try { refresh() } finally { busy = false } }
                }) { Text("刷新答复") }
            }
            if (questions.isEmpty()) Text("暂无咨询记录")
        }
        items(questions, key = { it.question_id }) { question ->
            OutlinedCard(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                Column(Modifier.padding(12.dp)) {
                    Text(if (question.status == "answered") "已答复" else "等待专家答复", color = CitrusColors.Green)
                    Text(question.text)
                    question.sample_id?.let { Text("关联图片 IMG-${it.takeLast(4).uppercase()}") }
                    Text(question.created_at)
                    question.answer?.takeIf { it.isNotBlank() }?.let { Text("专家答复：$it", modifier = Modifier.padding(top = 8.dp)) }
                }
            }
        }
    }
}
