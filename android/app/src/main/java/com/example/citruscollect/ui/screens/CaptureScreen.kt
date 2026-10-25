package com.example.citruscollect.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.example.citruscollect.ui.LocalAppContainer
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

@Composable
fun CaptureScreen(
    sampleId: String,
    onDone: (String) -> Unit,
    onBack: () -> Unit
) {
    val context = LocalContext.current
    val container = LocalAppContainer.current
    val lifecycleOwner = LocalLifecycleOwner.current

    var granted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }
    var cameraReady by remember { mutableStateOf(false) }
    var captureInProgress by remember { mutableStateOf(false) }
    var captureError by remember { mutableStateOf<String?>(null) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { allowed ->
        granted = allowed
        if (!allowed) captureError = "未授予相机权限，无法拍摄"
    }

    // 拍摄后立即落 Room，旋转/返回不会丢；数量直接来自 Room。
    val images by container.repository.imagesOf(sampleId).collectAsState(initial = emptyList())

    val imageCapture = remember { ImageCapture.Builder().build() }

    LaunchedEffect(Unit) {
        if (!granted) launcher.launch(Manifest.permission.CAMERA)
    }

    Column(modifier = Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            OutlinedButton(onClick = onBack) { Text("返回") }
            Text("拍摄（已拍 ${images.size} 张）", modifier = Modifier.weight(1f).padding(horizontal = 8.dp))
            Button(
                enabled = images.isNotEmpty(),
                onClick = { onDone(sampleId) }
            ) { Text("完成拍摄") }
        }

        Text(if (cameraReady) "相机已就绪" else "相机准备中", modifier = Modifier.padding(horizontal = 16.dp))

        if (captureError != null) {
            Text(
                captureError.orEmpty(),
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(horizontal = 16.dp)
            )
        }

        Box(modifier = Modifier.weight(1f)) {
            if (granted) {
                CameraPreview(imageCapture, lifecycleOwner, Modifier.fillMaxSize(),
                    onReady = { cameraReady = it }, onError = { captureError = it })
            } else {
                Text("需要相机权限才能拍摄", modifier = Modifier.align(Alignment.Center))
            }
        }

        Button(
            enabled = cameraReady && !captureInProgress,
            onClick = {
                captureInProgress = true
                captureError = null
                val file = File(context.filesDir, "capture_${System.currentTimeMillis()}.jpg")
                val options = ImageCapture.OutputFileOptions.Builder(file).build()
                imageCapture.takePicture(
                    options,
                    ContextCompat.getMainExecutor(context),
                    object : ImageCapture.OnImageSavedCallback {
                        override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                            // 立即落 Room（应用级 IO 作用域），旋转/返回不会丢失，也不会重复导入。
                            container.appScope.launch {
                              try {
                                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                                BitmapFactory.decodeFile(file.absolutePath, bounds)
                                container.repository.addImage(
                                    sampleId = sampleId,
                                    viewType = "close_up",
                                    file = file,
                                    mimeType = "image/jpeg",
                                    width = bounds.outWidth,
                                    height = bounds.outHeight
                                )
                              } catch (e: Exception) {
                                withContext(Dispatchers.Main) { captureError = "保存照片失败：${e.message}" }
                              } finally {
                                withContext(Dispatchers.Main) { captureInProgress = false }
                              }
                            }
                        }

                        override fun onError(exc: ImageCaptureException) {
                            captureInProgress = false
                            captureError = "拍摄失败：${exc.message ?: "未知错误"}"
                        }
                    }
                )
            },
            modifier = Modifier.fillMaxWidth().padding(16.dp)
        ) {
            Text("拍摄")
        }
    }
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
        PreviewView(context).apply {
            scaleType = PreviewView.ScaleType.FILL_CENTER
        }
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
                provider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    imageCapture
                )
                onReady(true)
            } catch (e: Exception) {
                onReady(false)
                onError("相机初始化失败：${e.message}")
            }
        }, ContextCompat.getMainExecutor(context))
    }
}
