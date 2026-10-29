package com.example.citruscollect.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.json.JSONObject

internal fun reviewSummary(raw: String): String = runCatching {
    val data = JSONObject(raw)
    val status = when (val s = data.optString("review_status")) {
        "unreviewed" -> "待核验"
        "confirmed" -> "已确认"
        "corrected" -> "已修正"
        "unresolved" -> "无法判断"
        else -> s.ifBlank { "待核验" }
    }
    val finalClass = data.optString("final_class_name").takeUnless { it == "null" }.orEmpty()
    status + if (finalClass.isNotBlank()) " · $finalClass" else ""
}.getOrDefault("核验结果暂不可读，请刷新")

@Composable
internal fun ReviewFeedback(raw: String?, busy: Boolean, onRefresh: () -> Unit) {
    OutlinedCard(Modifier.fillMaxWidth().padding(top = 12.dp)) {
        Column(Modifier.padding(12.dp)) {
            Text("专家核验反馈", style = MaterialTheme.typography.titleSmall)
            Text("采集时的原始标注保留在下方。", style = MaterialTheme.typography.bodySmall)
            if (raw == null) Text("尚未获取核验结果") else {
                Text(reviewSummary(raw))
                runCatching { JSONObject(raw) }.getOrNull()?.let { data ->
                    listOf("review_note" to "核验说明", "reviewed_at" to "核验时间").forEach { (key, label) ->
                        data.optString(key).takeIf { it.isNotBlank() && it != "null" }?.let { Text("$label：$it") }
                    }
                    data.optJSONArray("images")?.let { images ->
                        for (i in 0 until images.length()) {
                            val photo = images.optJSONObject(i) ?: continue
                            val quality = photo.optString("quality_status")
                            val label = when (quality) { "usable" -> "可用"; "unusable" -> "不合格"; "pending" -> "待检查"; else -> quality }
                            Text("图片 ${i + 1} 质量：$label")
                            photo.optString("quality_note").takeIf { it.isNotBlank() && it != "null" }?.let { Text("说明：$it") }
                            photo.optString("quality_reason_code").takeIf { it.isNotBlank() && it != "null" }?.let { reason ->
                                val translated = mapOf("blur" to "模糊", "occluded" to "遮挡", "exposure" to "曝光不佳", "wrong_object" to "拍摄对象不符", "duplicate" to "重复图片", "other" to "其他")[reason] ?: reason
                                Text("原因：$translated")
                            }
                        }
                    }
                }
            }
            TextButton(enabled = !busy, onClick = onRefresh) { Text(if (busy) "刷新中…" else "刷新核验结果") }
        }
    }
}
