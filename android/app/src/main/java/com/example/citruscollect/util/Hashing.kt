package com.example.citruscollect.util

import java.io.File
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/** 流式计算文件 SHA256（64 位小写十六进制），不在内存里一次性读入整个文件。 */
fun sha256Streaming(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input ->
        val buffer = ByteArray(64 * 1024)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
        }
    }
    return digest.digest().joinToString("") { "%02x".format(it) }
}

/**
 * 把采集时间戳格式化为带时区偏移的 RFC3339 字符串（如 `2026-10-20T09:12:33.123+08:00`）。
 * 服务端要求 `captured_at` 必须带偏移（Z 或 ±hh:mm），否则 422。
 */
fun formatCapturedAt(epochMillis: Long, timeZone: TimeZone = TimeZone.getDefault()): String {
    val formatter = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSSXXX", Locale.US)
    formatter.timeZone = timeZone
    return formatter.format(Date(epochMillis))
}
