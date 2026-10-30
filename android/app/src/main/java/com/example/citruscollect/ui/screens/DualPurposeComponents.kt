package com.example.citruscollect.ui.screens

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.citruscollect.ui.theme.CitrusColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

@Composable internal fun AppSection(content: @Composable ColumnScope.() -> Unit) {
    Surface(color = CitrusColors.White, shape = RoundedCornerShape(20.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
    }
}
@Composable internal fun ScreenTitle(title: String, subtitle: String) {
    Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = CitrusColors.Ink)
    Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = CitrusColors.Muted)
}
@Composable internal fun ChoiceField(label: String, choices: List<Pair<String,String>>, value: String, onChange: (String) -> Unit, enabled: Boolean = true) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        Text(label, style = MaterialTheme.typography.labelLarge)
        Box {
            OutlinedButton(onClick = { expanded = true }, enabled = enabled, modifier = Modifier.fillMaxWidth()) {
                Text(choices.firstOrNull { it.first == value }?.second ?: "请选择", Modifier.weight(1f))
                Text("⌄")
            }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                choices.forEach { (id, name) -> DropdownMenuItem(text = { Text(name) }, onClick = { expanded = false; onChange(id) }) }
            }
        }
    }
}
@Composable internal fun DiagnosisPhoto(path: String, height: Int = 220) {
    val bitmap by produceState<android.graphics.Bitmap?>(null, path) {
        value = withContext(Dispatchers.IO) {
            try {
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeFile(path, bounds)
                val sample = Integer.highestOneBit((maxOf(bounds.outWidth, bounds.outHeight) / 900).coerceAtLeast(1))
                val decoded = BitmapFactory.decodeFile(path, BitmapFactory.Options().apply { inSampleSize = sample })
                    ?: return@withContext null
                val orientation = runCatching {
                    ExifInterface(path).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
                }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)
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
                Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true).also {
                    if (it !== decoded) decoded.recycle()
                }
            } catch (_: Exception) { null }
        }
    }
    val b = bitmap
    if (b != null) Image(b.asImageBitmap(), contentDescription = "识别照片", contentScale = ContentScale.Fit,
        modifier = Modifier.fillMaxWidth().height(height.dp).clip(RoundedCornerShape(14.dp)).background(CitrusColors.Screen))
    else Text(if (File(path).exists()) "正在读取照片…" else "本地照片不存在，请重新选择图片。", color = CitrusColors.Muted)
}
internal fun displayDate(time: Long): String = java.text.SimpleDateFormat("MM月dd日 HH:mm", java.util.Locale.CHINA).format(java.util.Date(time))
