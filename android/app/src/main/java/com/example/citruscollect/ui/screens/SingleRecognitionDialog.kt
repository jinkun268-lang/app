package com.example.citruscollect.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.example.citruscollect.data.entity.ImageEntity
import com.example.citruscollect.network.ApiErrors
import com.example.citruscollect.network.CitrusJson
import com.example.citruscollect.network.RecognitionResult
import com.example.citruscollect.ui.LocalAppContainer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.io.IOException
import java.util.Locale

@Composable
fun SingleRecognitionDialog(image: ImageEntity, photoCount: Int, beforeApply: suspend () -> Unit, readOnly: Boolean = false,
    onDismiss: () -> Unit, onAdopted: (String) -> Unit) {
    val repository = LocalAppContainer.current.repository
    val scope = rememberCoroutineScope()
    var result by remember(image.imageId, image.sha256) { mutableStateOf(image.recognitionJson?.let {
        runCatching { CitrusJson.json.decodeFromString<RecognitionResult>(it) }.getOrNull()
    }) }
    var working by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var selected by remember { mutableIntStateOf(result?.accepted_index ?: 0) }
    Dialog(onDismissRequest = { if (!working) onDismiss() }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxWidth().padding(16.dp).heightIn(max = 620.dp), shape = MaterialTheme.shapes.large) {
            Column(Modifier.padding(16.dp)) {
                Text("单张识别", style = MaterialTheme.typography.titleLarge)
                Column(Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState())) {
                    LocalPhoto(image, Modifier.fillMaxWidth().height(150.dp), fullSize = true)
                    Text("仅识别当前图片 · 结果需人工复核", style = MaterialTheme.typography.bodySmall)
                    if (working) {
                        LinearProgressIndicator(Modifier.fillMaxWidth().padding(vertical = 12.dp))
                        Text("正在处理，请稍候…")
                    }
                    error?.let { Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(vertical = 8.dp)) }
                    val output = result
                    if (output != null) {
                        Text(output.model, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 12.dp))
                        Text(output.warning, style = MaterialTheme.typography.bodySmall)
                        Text("候选类别（分数不是诊断确定性）", Modifier.padding(top = 10.dp))
                        output.candidates.forEachIndexed { index, candidate ->
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                FilterChip(selected = selected == index, enabled = !working && !readOnly, onClick = { selected = index },
                                    label = { Text(candidate.name) })
                                Text(String.format(Locale.CHINA, "%.1f%%", candidate.score * 100), Modifier.padding(top = 15.dp))
                            }
                        }
                        val candidate = output.candidates.getOrNull(selected)
                        if (candidate?.class_id == null) Text("当前字典未收录该模型类别。采用后初步类别使用“不确定”，模型建议保存在识别结果中。", style = MaterialTheme.typography.bodySmall)
                        if (photoCount > 1 && !readOnly) Text("当前记录有 $photoCount 张照片。采用时将这张图单独成条，其他图片及其类别保持不变。", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall)
                        if (readOnly) Text("已上传，仅查看已保存的识别结果。")
                    } else if (!working) Text("当前接入叶片五分类实验模型，请使用叶片近景。结果需人工复核，不自动填写类别；识别失败时照片仍会保留。", Modifier.padding(vertical = 12.dp))
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(enabled = !working, onClick = onDismiss) { Text("返回") }
                    if (!readOnly) {
                    OutlinedButton(enabled = !working, onClick = {
                        working = true; error = null
                        scope.launch {
                            try { result = repository.recognizeImage(image.imageId); selected = 0 }
                            catch (e: CancellationException) { throw e }
                            catch (e: Exception) {
                                // 识别失败时不再保留旧候选，避免把过期结果误采用。
                                result = null
                                error = recognitionError(e)
                            }
                            finally { working = false }
                        }
                    }) { Text(if (result == null) "开始识别" else "重新识别") }
                    Button(enabled = result != null && !working, onClick = {
                        working = true; error = null
                        scope.launch {
                            try {
                                beforeApply()
                                val target = repository.adoptRecognition(image.imageId, selected)
                                onAdopted(target); onDismiss()
                            } catch (e: CancellationException) { throw e }
                            catch (e: Exception) { error = recognitionError(e) }
                            finally { working = false }
                        }
                    }) { Text("采用结果") }
                    }
                }
            }
        }
    }
}

private fun recognitionError(error: Exception): String = when (error) {
    is HttpException -> ApiErrors.messageOf(error)
    is IOException -> "识别连接失败，照片已保留，请重试"
    else -> error.message ?: "识别失败，请稍后重试"
}
