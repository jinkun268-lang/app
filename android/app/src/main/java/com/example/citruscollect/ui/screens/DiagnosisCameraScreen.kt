package com.example.citruscollect.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import java.io.File

/** 识别拍照不创建采集批次或 sample。照片只先写私有缓存，确认后才进入识别记录。 */
@Composable
fun DiagnosisCameraScreen(onCaptured: (File) -> Unit, onBack: () -> Unit) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    var granted by remember { mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    val previewView = remember { PreviewView(context) }
    val capture = remember { ImageCapture.Builder().build() }
    var cameraReady by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var taking by remember { mutableStateOf(false) }
    val active = remember { booleanArrayOf(true) }
    DisposableEffect(Unit) { onDispose { active[0] = false } }
    DisposableEffect(granted) {
        var provider: ProcessCameraProvider? = null
        val preview = Preview.Builder().build()
        var disposed = false
        if (granted) {
            val future = ProcessCameraProvider.getInstance(context)
            future.addListener({
                if (!disposed) {
                    try {
                        provider = future.get()
                        preview.setSurfaceProvider(previewView.surfaceProvider)
                        provider?.bindToLifecycle(lifecycle, CameraSelector.DEFAULT_BACK_CAMERA, preview, capture)
                        cameraReady = true
                    } catch (_: Exception) { error = "相机暂时无法打开，请返回后重试，或从相册选择。" }
                }
            }, ContextCompat.getMainExecutor(context))
        }
        onDispose { disposed = true; cameraReady = false; provider?.unbind(preview, capture) }
    }
    Column(Modifier.fillMaxSize().padding(18.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        TextButton(onClick = onBack, enabled = !taking) { Text("返回") }
        Text("拍清一片叶，或一个果实", style = MaterialTheme.typography.titleLarge)
        Text("主体完整、光线均匀，让病斑细节清楚可见。", style = MaterialTheme.typography.bodyMedium)
        if (granted) {
            AndroidView(factory = { previewView }, modifier = Modifier.fillMaxWidth().weight(1f))
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Button(enabled = cameraReady && !taking, modifier = Modifier.fillMaxWidth(), onClick = {
                val file = File(context.cacheDir, "diagnosis-${java.util.UUID.randomUUID()}.jpg")
                capture.targetRotation = previewView.display?.rotation ?: android.view.Surface.ROTATION_0
                taking = true
                capture.takePicture(ImageCapture.OutputFileOptions.Builder(file).build(), ContextCompat.getMainExecutor(context),
                    object : ImageCapture.OnImageSavedCallback {
                        override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                            if (active[0]) { taking = false; onCaptured(file) } else file.delete()
                        }
                        override fun onError(exception: ImageCaptureException) {
                            file.delete()
                            if (active[0]) { taking = false; error = "照片没有保存成功，请重新拍摄。" }
                        }
                    })
            }) { Text(if (taking) "正在保存…" else "拍照并使用") }
        } else {
            Text("需要相机权限才能拍照。你也可以返回，从相册选择图片。")
            Button(onClick = { permission.launch(Manifest.permission.CAMERA) }) { Text("允许使用相机") }
        }
    }
}
