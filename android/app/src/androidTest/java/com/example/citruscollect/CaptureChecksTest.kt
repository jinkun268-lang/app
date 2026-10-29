package com.example.citruscollect

import android.graphics.Bitmap
import android.graphics.Color
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.example.citruscollect.util.photoQualityWarning
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class CaptureChecksTest {
    @Test fun actualJpegProducesAdviceAndKeepsOriginalPhoto() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val file = File.createTempFile("quality-", ".jpg", context.cacheDir)
        val bitmap = Bitmap.createBitmap(640, 480, Bitmap.Config.ARGB_8888)
        try {
            bitmap.eraseColor(Color.rgb(4, 4, 4))
            file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 95, it) }
            val original = file.readBytes()
            assertTrue(photoQualityWarning(file).orEmpty().contains("偏暗"))
            assertArrayEquals(original, file.readBytes())
            assertTrue(file.exists())
        } finally { bitmap.recycle(); file.delete() }
    }
}
