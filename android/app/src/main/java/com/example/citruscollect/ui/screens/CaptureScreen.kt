package com.example.citruscollect.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.example.citruscollect.data.entity.ImageEntity
import com.example.citruscollect.ui.LocalAppContainer
import com.example.citruscollect.ui.theme.CitrusColors
import com.example.citruscollect.util.UuidV7
import com.example.citruscollect.util.GeoFix
import com.example.citruscollect.util.locateForCapture
import com.example.citruscollect.util.photoQualityWarning
import android.os.SystemClock
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private fun labels(): Pair<String, String> {
    val calendar = java.util.Calendar.getInstance()
    val morning = calendar.get(java.util.Calendar.HOUR_OF_DAY) < 12
    val day = SimpleDateFormat("M月d日", Locale.CHINA).format(Date())
    return (if (morning) "上午采集" else "下午采集") to day
}

/** 采集首页：批次条 + 连续拍摄入口 + 最近记录。 */
@Composable
fun CaptureHomeScreen(
    onStartCapture: () -> Unit,
    onOpenRecords: () -> Unit,
    onOpenBatches: () -> Unit
) {
    val container = LocalAppContainer.current
    val pending by container.repository.observePending().collectAsState(initial = emptyList())
    val uploaded by container.repository.observeUploaded().collectAsState(initial = emptyList())
    val all = remember(pending, uploaded) {
        (pending + uploaded).distinctBy { it.sampleId }.sortedByDescending { it.createdAt }
    }
    val batches by container.repository.observeBatches().collectAsState(initial = emptyList())
    val batch = batches.firstOrNull { it.batchId == container.batchId }
    val batchCount = all.count { it.batchId == container.batchId }

    Column(Modifier.fillMaxSize().background(CitrusColors.Screen).verticalScroll(rememberScrollState())) {
        Column(Modifier.padding(start = 18.dp, end = 18.dp, top = 14.dp, bottom = 12.dp)) {
            Text("开始采集", fontSize = 21.sp, fontWeight = FontWeight.Bold, color = CitrusColors.Ink)
            Text("连续拍摄，不打断采集节奏", fontSize = 11.sp, color = CitrusColors.Muted,
                modifier = Modifier.padding(top = 3.dp))
        }

        Surface(
            color = CitrusColors.GreenSoft,
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp).clickable(onClick = onOpenBatches)
        ) {
            Row(Modifier.padding(horizontal = 12.dp, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(21.dp).clip(RoundedCornerShape(5.dp)).background(Color(0xFFDCE7D6)))
                Column(Modifier.weight(1f).padding(start = 9.dp)) {
                    Text(batch?.name ?: "还没有采集批次", fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                        color = CitrusColors.Ink)
                    Text(
                        if (batch == null) "先去“采集批次”新建，再开始连续拍摄"
                        else "${batch.place.ifBlank { "未填写地点" }} · $batchCount 张图片${if (batch.closed) " · 已关闭，请切换批次" else ""}",
                        fontSize = 10.sp, color = Color(0xFF7C8875), modifier = Modifier.padding(top = 2.dp)
                    )
                }
                Text("切换 ›", fontSize = 11.sp, color = CitrusColors.Green, modifier = Modifier.padding(6.dp))
            }
        }

        LazyRow(
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 14.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            if (all.isEmpty()) {
                item { Text("还没有照片，拍下第一张就会生成记录", fontSize = 11.sp, color = CitrusColors.Faint) }
            }
            items(all.take(6), key = { it.sampleId }) { sample ->
                val images by container.repository.imagesOf(sample.sampleId).collectAsState(initial = emptyList())
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    images.firstOrNull()?.let { LocalPhoto(it, Modifier.size(54.dp).clip(RoundedCornerShape(6.dp))) }
                    Text("IMG-" + sample.sampleId.takeLast(4).uppercase(Locale.ROOT), fontSize = 9.sp,
                        color = CitrusColors.Faint, modifier = Modifier.padding(top = 4.dp))
                }
            }
        }

        TextButtonRow(onOpenRecords)

        Surface(
            color = CitrusColors.Green,
            shape = RoundedCornerShape(18.dp),
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)
        ) {
            Column(Modifier.padding(22.dp)) {
                Text("FIELD COLLECTION", fontSize = 10.sp, color = Color(0xFFC8D9BF), letterSpacing = 2.sp)
                Text("留住每一处观察。", fontSize = 25.sp, color = Color.White, modifier = Modifier.padding(top = 9.dp))
                Text(
                    "同一地点连续拍摄，照片自动归入当前批次。\n每张图片单独填写、审核和上传。",
                    fontSize = 11.sp, color = Color(0xFFC7D7BF), lineHeight = 20.sp,
                    modifier = Modifier.padding(top = 9.dp)
                )
                Surface(
                    color = Color(0xFFF4F3E5),
                    shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.fillMaxWidth().padding(top = 20.dp).clickable(onClick = {
                        if (batch?.closed == true || batch == null) onOpenBatches() else onStartCapture()
                    })
                ) {
                    Text("开始连续拍摄", fontSize = 12.sp, fontWeight = FontWeight.Medium, color = CitrusColors.Green,
                        textAlign = TextAlign.Center, modifier = Modifier.padding(vertical = 13.dp))
                }
            }
        }

        Surface(
            color = Color(0xFFF1F2E9),
            shape = RoundedCornerShape(12.dp),
            border = BorderStroke(1.dp, Color(0xFFE5E9DC)),
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 16.dp)
        ) {
            Text(
                "同一地点连续拍摄，图片自动归入当前批次。每张图拥有自己的编号、信息和上传状态，批量操作只省步骤，不把它们绑在一起。",
                fontSize = 11.sp, color = Color(0xFF7D886E), lineHeight = 19.sp,
                modifier = Modifier.padding(14.dp)
            )
        }
    }
}

@Composable
private fun TextButtonRow(onOpenRecords: () -> Unit) {
    Surface(
        color = CitrusColors.White,
        shape = RoundedCornerShape(10.dp),
        border = BorderStroke(1.dp, Color(0xFFDCE3D6)),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp).clickable(onClick = onOpenRecords)
    ) {
        Text("查看图片记录", fontSize = 12.sp, color = CitrusColors.Ink, textAlign = TextAlign.Center,
            modifier = Modifier.padding(vertical = 12.dp))
    }
}

/**
 * 相机会话：每按一次快门就新建一条图片记录。
 * 传 retakeSampleId/retakeImageId 时为重拍，只替换该记录的原图。
 */
@Composable
fun CaptureSessionScreen(
    retakeSampleId: String? = null,
    retakeImageId: String? = null,
    onCaptured: (String) -> Unit,
    onOpenRecord: (String) -> Unit,
    onDone: () -> Unit,
    onBack: () -> Unit
) {
    val context = LocalContext.current
    val container = LocalAppContainer.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()
    val ownerKey by container.authRepository.ownerKey.collectAsState(initial = null)
    val retaking = retakeSampleId != null && retakeImageId != null
    var session by rememberSaveable(retakeSampleId) { mutableStateOf(listOf<String>()) }

    var granted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }
    var cameraReady by remember { mutableStateOf(false) }
    var captureInProgress by remember { mutableStateOf(false) }
    var captureError by remember { mutableStateOf<String?>(null) }
    var qualityNotice by remember { mutableStateOf<Pair<String?, String>?>(null) }
    var position by remember { mutableStateOf<GeoFix?>(null) }
    var locating by remember { mutableStateOf(false) }
    var locationMessage by remember { mutableStateOf("可选：记录拍摄位置") }
    fun requestPosition() {
        locating = true
        scope.launch {
            try {
                position = withContext(Dispatchers.IO) { locateForCapture(context) }
                locationMessage = position?.let { "已定位 ±${it.accuracyM.toInt()}m（2分钟内有效）" }
                    ?: "未取得有效定位，仍可拍摄并手填批次地点"
            } finally { locating = false }
        }
    }
    val locationLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { permissions ->
        if (permissions.values.any { it }) requestPosition()
        else { position = null; locationMessage = "未授权定位，仍可拍摄并手填批次地点" }
    }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { allowed ->
        granted = allowed
        if (!allowed) captureError = "未授予相机权限，无法拍摄"
    }

    val imageCapture = remember { ImageCapture.Builder().build() }
    BackHandler(enabled = captureInProgress) { }

    val batches by container.repository.observeBatches().collectAsState(initial = emptyList())
    val batch = batches.firstOrNull { it.batchId == container.batchId }

    LaunchedEffect(Unit) { if (!granted) launcher.launch(Manifest.permission.CAMERA) }

    qualityNotice?.let { (recordId, warning) ->
        AlertDialog(
            onDismissRequest = { qualityNotice = null },
            title = { Text("照片已保存，请检查拍摄质量") },
            text = { Text("$warning\n这是本地拍摄建议，不是病害诊断；原图已保留。") },
            confirmButton = { TextButton(onClick = { qualityNotice = null }) { Text("保留并继续") } },
            dismissButton = { if (recordId != null) TextButton(onClick = {
                qualityNotice = null; onOpenRecord(recordId)
            }) { Text("查看并重拍") } }
        )
    }

    Column(Modifier.fillMaxSize().background(Color(0xFF183323))) {
        Row(
            Modifier.fillMaxWidth().background(Color.White).padding(horizontal = 18.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Surface(color = Color(0xFFF2F4ED), shape = CircleShape,
                modifier = Modifier.size(30.dp).clickable(enabled = !captureInProgress, onClick = onBack)) {
                Box(contentAlignment = Alignment.Center) { Text("‹", fontSize = 18.sp, color = CitrusColors.Ink) }
            }
            Spacer(Modifier.weight(1f))
            Text(if (retaking) "重拍照片" else "连续拍摄", fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                color = CitrusColors.Ink)
            Spacer(Modifier.weight(1f))
            Surface(color = Color.Transparent, shape = RoundedCornerShape(8.dp),
                border = BorderStroke(1.dp, Color(0xFFDCE3D6)),
                modifier = Modifier.clickable(enabled = !captureInProgress, onClick = onDone)) {
                Text("完成采集", fontSize = 11.sp, color = CitrusColors.Ink,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 7.dp))
            }
        }

        Row(Modifier.fillMaxWidth().background(Color(0xFF244532)).padding(horizontal = 12.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text(if (locating) "正在定位，可继续拍摄…" else locationMessage,
                fontSize = 10.sp, color = Color.White, modifier = Modifier.weight(1f))
            TextButton(enabled = !locating, onClick = {
                locationLauncher.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
            }) { Text("获取定位", color = Color.White, fontSize = 10.sp) }
            if (position != null) TextButton(onClick = { position = null; locationMessage = "不记录位置" }) {
                Text("清除", color = Color.White, fontSize = 10.sp)
            }
        }

        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (granted) {
                CameraPreview(imageCapture, lifecycleOwner, Modifier.fillMaxSize(),
                    onReady = { cameraReady = it }, onError = { captureError = it })
            } else {
                Text("需要相机权限才能拍摄", color = Color.White, modifier = Modifier.align(Alignment.Center))
            }
            Text(
                "${labels().second} · ${batch?.name ?: "历史记录"}${if (batch?.closed == true) " · 批次已关闭" else ""}",
                fontSize = 11.sp, color = Color(0xFFE2E9D8),
                modifier = Modifier.align(Alignment.TopCenter).padding(top = 15.dp)
            )
            Surface(color = Color(0xA6213B2C), shape = RoundedCornerShape(20.dp),
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 20.dp)) {
                Text("每拍一张，保存一条独立图片记录", fontSize = 11.sp, color = Color(0xFFEFF5E8),
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
            }
            captureError?.let {
                Text(it, color = Color(0xFFFFD9D0), fontSize = 11.sp, textAlign = TextAlign.Center,
                    modifier = Modifier.align(Alignment.Center).padding(24.dp))
            }
        }

        if (session.isNotEmpty() && !retaking) {
            LazyRow(
                contentPadding = PaddingValues(10.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.fillMaxWidth().background(Color(0xFF1E3829))
            ) {
                items(session, key = { it }) { id ->
                    val images by container.repository.imagesOf(id).collectAsState(initial = emptyList())
                    images.firstOrNull()?.let { image ->
                        LocalPhoto(image, Modifier.size(42.dp).clip(RoundedCornerShape(5.dp))
                            .clickable { onOpenRecord(id) })
                    }
                }
            }
        } else {
            Box(Modifier.fillMaxWidth().background(Color(0xFF1E3829)).padding(10.dp)) {
                Text(if (retaking) "拍完会替换原图并返回信息页" else "已拍照片会显示在这里",
                    fontSize = 11.sp, color = Color(0xFFA7BBA0))
            }
        }

        Row(
            Modifier.fillMaxWidth().background(Color(0xFF183323)).padding(horizontal = 20.dp, vertical = 17.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(if (retaking) "重拍" else "已拍 ${session.size} 张", fontSize = 11.sp, color = Color.White,
                modifier = Modifier.weight(1f))
            Box(
                Modifier.size(63.dp).clip(CircleShape)
                    .background(Color.White)
                    .clickable(enabled = granted && cameraReady && !captureInProgress && ownerKey != null && (retaking || batch?.closed != true)) {
                        captureInProgress = true
                        captureError = null
                        shoot(context, container, imageCapture, retakeSampleId, retakeImageId,
                            container.batchId, batch?.defaultCultivarId ?: "unknown",
                            ownerKey, position?.takeIf { it.usableAt(SystemClock.elapsedRealtime()) }) { result, warning, error ->
                            if (result != null) {
                                if (retakeSampleId != null) onCaptured(retakeSampleId)
                                else session = session + result
                            }
                            captureError = error
                            if (warning != null && !retaking) qualityNotice = result to warning
                            captureInProgress = false
                        }
                    },
                contentAlignment = Alignment.Center
            ) {
                Box(Modifier.size(45.dp).clip(CircleShape).background(Color(0xFFDFE7DC)))
            }
            Text(if (retaking) "完成后返回" else "完成采集", fontSize = 11.sp, color = Color(0xFFC8D9BF),
                modifier = Modifier.weight(1f).clickable(onClick = onDone).padding(8.dp),
                textAlign = TextAlign.End)
        }
        if (!cameraReady && granted) {
            Text("相机准备中…", fontSize = 10.sp, color = Color(0xFFA7BBA0),
                modifier = Modifier.fillMaxWidth().background(Color(0xFF183323)).padding(bottom = 6.dp),
                textAlign = TextAlign.Center)
        }
    }
}

private fun shoot(
    context: android.content.Context,
    container: com.example.citruscollect.AppContainer,
    imageCapture: ImageCapture,
    retakeSampleId: String?,
    retakeImageId: String?,
    batchId: String?,
    cultivarId: String,
    expectedOwnerKey: String?,
    position: GeoFix?,
    onSaved: (String?, String?, String?) -> Unit
) {
    val file = File(context.filesDir, "capture_${UuidV7.generate()}.jpg")
    imageCapture.takePicture(
        ImageCapture.OutputFileOptions.Builder(file).build(),
        ContextCompat.getMainExecutor(context),
        object : ImageCapture.OnImageSavedCallback {
            override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                container.appScope.launch {
                    var persisted = false
                    try {
                        if (expectedOwnerKey == null || container.authRepository.currentOwnerKey() != expectedOwnerKey)
                            throw IllegalStateException("拍摄期间账号已切换，请重新拍摄")
                        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                        BitmapFactory.decodeFile(file.absolutePath, bounds)
                        val quality = runCatching { photoQualityWarning(file) }.getOrElse { "质量检查暂不可用，请打开原图确认" }
                        val id = if (retakeSampleId != null && retakeImageId != null) {
                            container.repository.replaceImage(
                                retakeSampleId, retakeImageId, file, bounds.outWidth, bounds.outHeight,
                                latitude = position?.latitude, longitude = position?.longitude,
                                locationAccuracyM = position?.accuracyM, qualityWarning = quality
                            )
                            null
                        } else {
                            container.repository.capturePhoto(
                                file = file, mimeType = "image/jpeg",
                                width = bounds.outWidth, height = bounds.outHeight,
                                batchId = batchId, cultivarId = cultivarId,
                                latitude = position?.latitude, longitude = position?.longitude,
                                locationAccuracyM = position?.accuracyM, qualityWarning = quality,
                                expectedOwnerKey = expectedOwnerKey
                            )
                        }
                        persisted = true
                        withContext(Dispatchers.Main) { onSaved(id, quality, null) }
                    } catch (e: Exception) {
                        if (!persisted) file.delete()
                        withContext(Dispatchers.Main) { onSaved(null, null, e.message ?: "照片保存失败，请重试") }
                    }
                }
            }

            override fun onError(exc: ImageCaptureException) {
                file.delete()
                onSaved(null, null, "拍摄失败，请重试")
            }
        }
    )
}

@Composable
private fun CameraPreview(
    imageCapture: ImageCapture,
    lifecycleOwner: androidx.lifecycle.LifecycleOwner,
    modifier: Modifier,
    onReady: (Boolean) -> Unit,
    onError: (String) -> Unit
) {
    val context = LocalContext.current
    val previewView = remember {
        PreviewView(context).apply { scaleType = PreviewView.ScaleType.FILL_CENTER }
    }

    AndroidView(factory = { previewView }, modifier = modifier)

    LaunchedEffect(lifecycleOwner) {
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            onReady(false)
            val provider = future.get()
            val preview = Preview.Builder().build().also { it.setSurfaceProvider(previewView.surfaceProvider) }
            try {
                provider.unbindAll()
                provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, imageCapture)
                onReady(true)
            } catch (e: Exception) {
                onReady(false)
                onError("相机初始化失败：${e.message}")
            }
        }, ContextCompat.getMainExecutor(context))
    }
}
