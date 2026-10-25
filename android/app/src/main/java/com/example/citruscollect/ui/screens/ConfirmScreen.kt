package com.example.citruscollect.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.citruscollect.ui.LocalAppContainer
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.first
import androidx.compose.foundation.horizontalScroll

// 部位与视角是固定业务字典（契约枚举），只有品种/类别来自 bootstrap。
private val PARTS = listOf("leaf" to "叶", "fruit" to "果", "branch" to "枝", "insect" to "虫体", "other" to "其他")
private val VIEW_TYPES = listOf("close_up" to "近景", "context" to "稍远图", "other" to "其他")

@Composable
fun ConfirmScreen(sampleId: String, onBack: () -> Unit, onSaved: () -> Unit) {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()

    val images by container.repository.imagesOf(sampleId).collectAsState(initial = emptyList())

    var cultivars by remember { mutableStateOf(emptyList<Pair<String, String>>()) }
    var classes by remember { mutableStateOf(emptyList<Pair<String, String>>()) }
    var dictionaryAttempt by remember { mutableStateOf(0) }
    var dictionaryReady by remember { mutableStateOf(false) }
    var dictionaryError by remember { mutableStateOf<String?>(null) }

    var cultivar by remember { mutableStateOf("") }
    var part by remember { mutableStateOf("leaf") }
    var classId by remember { mutableStateOf("") }
    var symptoms by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }

    LaunchedEffect(sampleId, dictionaryAttempt) {
        dictionaryReady = false
        dictionaryError = null
        try {
            val stored = container.repository.sampleById(sampleId).first()
            val bootstrap = container.authRepository.bootstrap()
            cultivars = bootstrap.cultivars.filter { it.is_active }.map { it.cultivar_id to it.name }
            classes = bootstrap.classes.filter { it.is_active }.map { it.class_id to it.name }
            cultivar = stored?.cultivarId?.takeIf { id -> cultivars.any { it.first == id } } ?: cultivars.firstOrNull()?.first.orEmpty()
            classId = stored?.classId?.takeIf { id -> classes.any { it.first == id } } ?: classes.firstOrNull()?.first.orEmpty()
            part = stored?.part ?: "leaf"
            symptoms = stored?.symptoms.orEmpty()
            note = stored?.note.orEmpty()
            dictionaryReady = cultivars.isNotEmpty() && classes.isNotEmpty()
        } catch (e: Exception) {
            dictionaryError = "字典加载失败，请重试"
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)
    ) {
        Text("信息确认", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(12.dp))

        if (dictionaryError != null) {
            Text(dictionaryError.orEmpty(), color = MaterialTheme.colorScheme.error)
            OutlinedButton(onClick = { dictionaryAttempt++ }) { Text("重试加载字典") }
        }

        Text("品种")
        ChoiceRow(cultivars, cultivar) { cultivar = it }
        Text("部位")
        ChoiceRow(PARTS, part) { part = it }
        Text("病种（初步类别）")
        ChoiceRow(classes, classId) { classId = it }

        Spacer(Modifier.height(12.dp))
        OutlinedTextField(symptoms, { symptoms = it }, label = { Text("症状") }, modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(note, { note = it }, label = { Text("备注") }, modifier = Modifier.fillMaxWidth())

        Spacer(Modifier.height(16.dp))
        Text("每张图片视角", style = MaterialTheme.typography.titleSmall)
        images.forEach { img ->
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Text("${img.imageId.take(6)}", modifier = Modifier.weight(0.3f))
                ChoiceRow(
                    options = VIEW_TYPES,
                    selected = img.viewType,
                    onSelect = { scope.launch { container.repository.updateViewType(img.imageId, it) } }
                )
            }
        }

        Spacer(Modifier.height(24.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedButton(onClick = onBack, modifier = Modifier.weight(1f)) { Text("取消") }
            Button(
                enabled = dictionaryReady && images.isNotEmpty(),
                onClick = {
                    scope.launch {
                        if (images.isEmpty()) {
                            return@launch
                        }
                        container.repository.saveConfirm(sampleId, cultivar, part, classId, symptoms, note)
                        onSaved()
                    }
                },
                modifier = Modifier.weight(1f)
            ) { Text("保存并结束") }
        }
    }
}

@Composable
private fun ChoiceRow(
    options: List<Pair<String, String>>,
    selected: String,
    onSelect: (String) -> Unit
) {
    Row(modifier = Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        options.forEach { (value, label) ->
            FilterChip(
                selected = selected == value,
                onClick = { onSelect(value) },
                label = { Text(label) }
            )
        }
    }
}
