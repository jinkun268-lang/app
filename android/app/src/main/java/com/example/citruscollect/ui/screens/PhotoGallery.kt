package com.example.citruscollect.ui.screens

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.example.citruscollect.data.entity.ImageEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Decode off the UI thread, bound memory usage, and honour CameraX JPEG orientation. */
@Composable
internal fun LocalPhoto(photo: ImageEntity, modifier: Modifier, fullSize: Boolean = false) {
    val bitmap by produceState<Bitmap?>(null, photo.filePath, photo.capturedAt, fullSize) {
        value = withContext(Dispatchers.IO) {
            runCatching {
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeFile(photo.filePath, bounds)
                val limit = if (fullSize) 2048 else 320
                var sample = 1
                while (maxOf(bounds.outWidth, bounds.outHeight) / sample > limit) sample *= 2
                val decoded = BitmapFactory.decodeFile(photo.filePath, BitmapFactory.Options().apply { inSampleSize = sample })
                    ?: return@runCatching null
                val exif = ExifInterface(photo.filePath)
                val orientation = exif.getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
                val matrix = Matrix().apply {
                    when (orientation) {
                        ExifInterface.ORIENTATION_ROTATE_90 -> postRotate(90f)
                        ExifInterface.ORIENTATION_ROTATE_180 -> postRotate(180f)
                        ExifInterface.ORIENTATION_ROTATE_270 -> postRotate(270f)
                        ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> postScale(-1f, 1f)
                        ExifInterface.ORIENTATION_FLIP_VERTICAL -> postScale(1f, -1f)
                        ExifInterface.ORIENTATION_TRANSPOSE -> { postRotate(90f); postScale(-1f, 1f) }
                        ExifInterface.ORIENTATION_TRANSVERSE -> { postRotate(270f); postScale(-1f, 1f) }
                    }
                }
                Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
            }.getOrNull()
        }
    }
    Box(modifier.background(Color(0xffeeeeee)), contentAlignment = Alignment.Center) {
        val loaded = bitmap
        if (loaded != null) Image(loaded.asImageBitmap(), "照片预览", Modifier.fillMaxSize(),
            contentScale = if (fullSize) ContentScale.Fit else ContentScale.Crop)
        else Text("照片加载中或文件不可用", style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
fun PhotoGallery(
    images: List<ImageEntity>,
    editable: Boolean,
    busy: Boolean = false,
    onDelete: (String, Boolean) -> Unit,
    onRetake: (String) -> Unit,
    beforeRecognitionApply: suspend () -> Unit = {},
    onRecognitionAdopted: (String) -> Unit = {}
) {
    var selectedId by remember { mutableStateOf<String?>(null) }
    var deleteId by remember { mutableStateOf<String?>(null) }
    var recognizeId by remember { mutableStateOf<String?>(null) }
    val selected = images.firstOrNull { it.imageId == selectedId }
    Column(Modifier.fillMaxWidth()) {
        Text(if (images.size == 1) "1 张图片 · 点击查看" else "${images.size} 张图片 · 点击查看",
            Modifier.padding(horizontal = 16.dp, vertical = 6.dp), style = MaterialTheme.typography.labelLarge)
        if (images.isEmpty()) Text("还没有照片", Modifier.padding(16.dp))
        LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            itemsIndexed(images, key = { _, photo -> photo.imageId }) { index, photo ->
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    LocalPhoto(photo, Modifier.size(76.dp).clickable(enabled = !busy) { selectedId = photo.imageId })
                    Text("照片 ${index + 1}", style = MaterialTheme.typography.labelSmall)
                    if (editable || photo.recognitionJson != null) TextButton(enabled = !busy, onClick = { recognizeId = photo.imageId }) { Text(if (editable) "识别此图" else "识别结果") }
                }
            }
        }
    }
    if (selected != null) {
        // Reserve space for system bars on devices whose dialog window reports the full display height.
        val previewHeight = (LocalConfiguration.current.screenHeightDp - 96).coerceAtLeast(180).dp
        var scale by remember(selected.filePath) { mutableFloatStateOf(1f) }
        var x by remember(selected.filePath) { mutableFloatStateOf(0f) }
        var y by remember(selected.filePath) { mutableFloatStateOf(0f) }
        Dialog(onDismissRequest = { if (!busy) selectedId = null }, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
            Surface(Modifier.fillMaxWidth().height(previewHeight)) {
                Box(Modifier.fillMaxSize().safeDrawingPadding().padding(12.dp)) {
                    Row(Modifier.align(Alignment.TopCenter).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text("照片 ${images.indexOf(selected) + 1} · 双指缩放", Modifier.weight(1f))
                        TextButton(enabled = !busy, onClick = { selectedId = null }) { Text("关闭预览") }
                    }
                    Box(Modifier.fillMaxSize().padding(top = 56.dp, bottom = if (editable) 136.dp else 88.dp).clipToBounds().background(Color.Black)
                        .pointerInput(selected.filePath) {
                            detectTransformGestures { _, pan, zoom, _ ->
                                scale = (scale * zoom).coerceIn(1f, 5f)
                                x = if (scale == 1f) 0f else (x + pan.x).coerceIn(-size.width * (scale - 1) / 2, size.width * (scale - 1) / 2)
                                y = if (scale == 1f) 0f else (y + pan.y).coerceIn(-size.height * (scale - 1) / 2, size.height * (scale - 1) / 2)
                            }
                        }) {
                        LocalPhoto(selected, Modifier.fillMaxSize().graphicsLayer {
                            scaleX = scale; scaleY = scale; translationX = x; translationY = y
                        }, fullSize = true)
                    }
                    Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth()) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        OutlinedButton(enabled = editable && !busy, modifier = Modifier.weight(1f),
                            onClick = { deleteId = selected.imageId }) { Text("删除照片") }
                        Button(enabled = editable && !busy, modifier = Modifier.weight(1f),
                            onClick = { selectedId = null; onRetake(selected.imageId) }) { Text("重拍此照片") }
                    }
                    if (!editable) Text("已开始上传的照片仅可预览", style = MaterialTheme.typography.labelSmall)
                    if (editable) TextButton(enabled = !busy, onClick = { recognizeId = selected.imageId; selectedId = null }) { Text("识别此图") }
                    }
                }
            }
        }
    }
    images.firstOrNull { it.imageId == recognizeId }?.let { image ->
        SingleRecognitionDialog(image, images.size, beforeRecognitionApply, readOnly = !editable,
            onDismiss = { recognizeId = null }, onAdopted = onRecognitionAdopted)
    }
    if (deleteId != null) AlertDialog(
        onDismissRequest = { deleteId = null }, title = { Text(if (images.size == 1) "删除这条记录？" else "删除这张照片？") },
        text = { Text(if (images.size == 1) "这条记录只有这张图片，删除后记录和本地原图都会移除。" else "删除后无法恢复，可以重新拍摄。") },
        confirmButton = { TextButton(enabled = !busy, onClick = {
            val id = deleteId!!; val last = images.size == 1
            deleteId = null; selectedId = null; onDelete(id, last)
        }) { Text(if (images.size == 1) "删除图片和记录" else "确认删除") } },
        dismissButton = { Column {
            if (images.size == 1) TextButton(enabled = !busy, onClick = {
                val id = deleteId!!; deleteId = null; selectedId = null; onDelete(id, false)
            }) { Text("仅删图片，保留补拍") }
            TextButton(onClick = { deleteId = null }) { Text("取消") }
        } }
    )
}
