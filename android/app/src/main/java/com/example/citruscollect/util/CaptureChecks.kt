package com.example.citruscollect.util

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Looper
import android.os.SystemClock
import androidx.core.content.ContextCompat
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File
import kotlin.coroutines.resume

fun photoQualityWarning(file: File): String? {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(file.absolutePath, bounds)
    var scale = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / scale > 256) scale *= 2
    val bitmap = BitmapFactory.decodeFile(file.absolutePath, BitmapFactory.Options().apply { inSampleSize = scale })
        ?: return "未能检查照片质量，请打开原图确认清晰度"
    return try {
        if (bitmap.width < 3 || bitmap.height < 3) return "照片尺寸过小，建议重拍"
        val pixels = IntArray(bitmap.width * bitmap.height)
        bitmap.getPixels(pixels, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
        val grayscale = IntArray(pixels.size) { i ->
            val rgb = pixels[i]
            (77 * ((rgb shr 16) and 255) + 150 * ((rgb shr 8) and 255) + 29 * (rgb and 255)) shr 8
        }
        PhotoQuality.assess(grayscale, bitmap.width, bitmap.height).warnings.joinToString("；").ifEmpty { null }
    } finally { bitmap.recycle() }
}

/** 仅用户点击定位后调用；不持续追踪，权限拒绝/关闭GPS/超时均返回空。 */
@Suppress("MissingPermission", "DEPRECATION")
suspend fun locateForCapture(context: Context): GeoFix? {
    val fine = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
    val coarse = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
    if (!fine && !coarse) return null
    val manager = context.getSystemService(Context.LOCATION_SERVICE) as? LocationManager ?: return null
    fun Location.fix() = GeoFix(latitude, longitude, accuracy.toDouble(), elapsedRealtimeNanos / 1_000_000)
    val providers = listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER).filter {
        (fine || it != LocationManager.GPS_PROVIDER) && runCatching { manager.isProviderEnabled(it) }.getOrDefault(false)
    }
    val recent = providers.mapNotNull { runCatching { manager.getLastKnownLocation(it)?.fix() }.getOrNull() }
        .filter { it.usableAt(SystemClock.elapsedRealtime()) }.minByOrNull { it.accuracyM }
    if (recent != null) return recent
    if (providers.isEmpty()) return null
    return withTimeoutOrNull(8_000) {
        suspendCancellableCoroutine { continuation ->
            val listener = object : LocationListener {
                override fun onLocationChanged(location: Location) {
                    val fix = location.fix()
                    if (fix.usableAt(SystemClock.elapsedRealtime()) && continuation.isActive) {
                        manager.removeUpdates(this)
                        continuation.resume(fix)
                    }
                }
                override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit
                override fun onProviderEnabled(provider: String) = Unit
                override fun onProviderDisabled(provider: String) = Unit
            }
            continuation.invokeOnCancellation { runCatching { manager.removeUpdates(listener) } }
            providers.forEach { provider ->
                runCatching { manager.requestLocationUpdates(provider, 0L, 0f, listener, Looper.getMainLooper()) }
            }
        }
    }
}
