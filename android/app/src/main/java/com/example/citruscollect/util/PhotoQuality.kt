package com.example.citruscollect.util

/** 小尺寸灰度图的拍摄建议，不推断病害、不拒收照片。阈值需经真机校准。 */
object PhotoQuality {
    data class Assessment(val warnings: List<String>, val meanLuminance: Double, val detailVariance: Double)

    fun assess(luminance: IntArray, width: Int, height: Int): Assessment {
        require(width >= 3 && height >= 3 && width.toLong() * height == luminance.size.toLong())
        require(luminance.all { it in 0..255 })
        val mean = luminance.average()
        var sum = 0.0
        var square = 0.0
        var count = 0
        for (y in 1 until height - 1) for (x in 1 until width - 1) {
            val index = y * width + x
            val laplacian = luminance[index - 1] + luminance[index + 1] +
                luminance[index - width] + luminance[index + width] - 4 * luminance[index]
            sum += laplacian
            square += laplacian.toDouble() * laplacian
            count++
        }
        val variance = (square / count - (sum / count) * (sum / count)).coerceAtLeast(0.0)
        val warnings = buildList {
            if (mean < 35 || luminance.count { it <= 12 }.toDouble() / luminance.size > .65)
                add("画面偏暗，建议补光或调整角度")
            if (mean > 225 || luminance.count { it >= 245 }.toDouble() / luminance.size > .65)
                add("画面偏亮，建议避开直射光")
            if (variance < 50) add("清晰度可能不足，请检查对焦和叶片细节")
        }
        return Assessment(warnings, mean, variance)
    }
}

/** elapsedRealtime 时间戳防止系统时间调整使旧定位看起来更新。 */
data class GeoFix(
    val latitude: Double,
    val longitude: Double,
    val accuracyM: Double,
    val elapsedRealtimeMs: Long
) {
    fun usableAt(nowElapsedMs: Long): Boolean = latitude.isFinite() && longitude.isFinite() &&
        latitude in -90.0..90.0 && longitude in -180.0..180.0 && accuracyM.isFinite() &&
        accuracyM in 0.0..1_000.0 && nowElapsedMs - elapsedRealtimeMs in 0L..120_000L
}
