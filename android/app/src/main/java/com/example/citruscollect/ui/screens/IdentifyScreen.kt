package com.example.citruscollect.ui.screens

import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.example.citruscollect.ui.LocalAppContainer
import com.example.citruscollect.ui.theme.CitrusColors
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

@Composable
fun IdentifyScreen(photoPath: String?, onPhotoConsumed: () -> Unit, onCamera: () -> Unit, onReport: (String) -> Unit) {
    val context = LocalContext.current
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val owner by container.authRepository.ownerKey.collectAsState(initial = null)
    var imagePath by rememberSaveable { mutableStateOf<String?>(null) }
    var imageOwner by rememberSaveable { mutableStateOf<String?>(null) }
    var mime by rememberSaveable { mutableStateOf("image/jpeg") }
    var crop by rememberSaveable { mutableStateOf("huyou") }
    var part by rememberSaveable { mutableStateOf("leaf") }
    var age by rememberSaveable { mutableStateOf("unknown") }
    var symptom by rememberSaveable { mutableStateOf("") }
    var consent by rememberSaveable { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(photoPath) {
        if (photoPath != null) {
            imagePath = photoPath; mime = "image/jpeg"
            imageOwner = container.authRepository.currentOwnerKey()
            consent = false; error = null; onPhotoConsumed()
        }
    }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) {
            val selectedOwner = owner
            scope.launch {
                busy = true; error = null
                var file: File? = null
                try {
                    file = withContext(Dispatchers.IO) {
                        val target = File(context.cacheDir, "diagnosis-import-${java.util.UUID.randomUUID()}")
                        try {
                            context.contentResolver.openInputStream(uri)?.use { input ->
                                target.outputStream().use { output ->
                                    val buffer = ByteArray(8192); var count = 0L
                                    while (true) { val n = input.read(buffer); if (n < 0) break; count += n; require(count <= 20L * 1024 * 1024) { "单张图片不能超过20MB" }; output.write(buffer, 0, n) }
                                }
                            } ?: throw IllegalArgumentException("无法读取这张图片，请重新选择")
                            val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                            BitmapFactory.decodeFile(target.path, options)
                            require(options.outWidth > 0 && options.outHeight > 0 && options.outWidth.toLong() * options.outHeight <= 24_000_000) { "图片无法读取或超过2400万像素，请更换图片" }
                            require(options.outMimeType in setOf("image/jpeg", "image/png", "image/webp")) { "请选择JPEG、PNG或WebP图片" }
                            target
                        } catch (e: Exception) { target.delete(); throw e }
                    }
                    if (selectedOwner == null || container.authRepository.currentOwnerKey() != selectedOwner) {
                        file.delete(); error = "账号已切换，请重新选择图片"
                    } else {
                        val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                        withContext(Dispatchers.IO) { BitmapFactory.decodeFile(file.path, options) }
                        imagePath = file.path; imageOwner = selectedOwner; mime = options.outMimeType
                        consent = false
                    }
                } catch (e: CancellationException) { file?.delete(); throw e }
                catch (e: Exception) { error = e.message ?: "读取图片失败，请重新选择" }
                finally { busy = false }
            }
        }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        ScreenTitle("先看清，再判断", "无需创建批次。先拍照，识别后再获取处理建议。")
        AppSection {
            imagePath?.let { DiagnosisPhoto(it) } ?: Text("拍清一片叶，或一个果实。光线均匀，避免反光，保留病斑细节。", color = CitrusColors.Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = onCamera, enabled = !busy, modifier = Modifier.weight(1f)) { Text("拍照") }
                OutlinedButton(onClick = { picker.launch("image/*") }, enabled = !busy, modifier = Modifier.weight(1f)) { Text("从相册选择") }
            }
        }
        AppSection {
            Text("补充一点现场情况", style = MaterialTheme.typography.titleMedium)
            ChoiceField("种的是什么", listOf("huyou" to "胡柚", "xiangyou" to "香柚", "citrus" to "其他柑橘"), crop, { crop = it }, !busy)
            ChoiceField("拍的是什么部位", listOf("leaf" to "叶片", "fruit" to "果实", "branch" to "枝条"), part, { part = it }, !busy)
            ChoiceField("树的生长情况", listOf("unknown" to "不清楚", "young" to "幼树 / 新栽树", "adult" to "成龄树"), age, { age = it }, !busy)
            OutlinedTextField(value = symptom, onValueChange = { symptom = it.take(300) }, label = { Text("还有哪些现象（选填）") }, modifier = Modifier.fillMaxWidth(), enabled = !busy)
            Row {
                Checkbox(checked = consent, onCheckedChange = { consent = it }, enabled = !busy)
                Text("同意发送这张图片进行本次识别。不会自动加入采集数据集。", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 10.dp))
            }
            error?.let { Text(it, color = CitrusColors.Red) }
            Button(enabled = !busy && imagePath != null && consent, modifier = Modifier.fillMaxWidth(), onClick = {
                val path = imagePath ?: return@Button
                val expectedOwner = imageOwner ?: return@Button
                scope.launch {
                    busy = true; error = null
                    try {
                        val id = container.diagnosisRepository.createDraft(File(path), mime, crop, part, age, symptom, expectedOwner)
                        onReport(id)
                        container.appScope.launch {
                            try { container.diagnosisRepository.analyze(id) }
                            catch (e: CancellationException) { throw e }
                            catch (_: Exception) { /* 仓库持久化失败，报告页展示 */ }
                        }
                    } catch (e: CancellationException) { throw e }
                    catch (e: Exception) { error = e.message ?: "保存失败，请重试" }
                    finally { busy = false }
                }
            }) { Text(if (busy) "正在保存…" else "开始识别") }
            Text("模型未连接或无法判断时，会如实提示；不会用示例结果替代真实识别。", color = CitrusColors.Muted, style = MaterialTheme.typography.bodySmall)
        }
    }
}
