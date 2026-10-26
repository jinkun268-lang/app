package com.example.citruscollect

import android.content.Intent
import android.graphics.Bitmap
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.example.citruscollect.data.AppDatabase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class UploadPhotoUiTest {
    @Test fun pendingListSupportsPhotosAndDeclaredDetailsAreReadOnly(): Unit = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val app = context.applicationContext as CitrusApplication
        val args = InstrumentationRegistry.getArguments()
        app.container.authRepository.login(requireNotNull(args.getString("baseUrl")),
            requireNotNull(args.getString("collectorUsername")), requireNotNull(args.getString("collectorPassword")))
        val repository = app.container.repository
        val device = UiDevice.getInstance(instrumentation)
        val sample = repository.createSample("unknown", "leaf", "unknown", note = "upload-photo-fixture")
        val files = mutableListOf<File>()
        fun click(text: String) {
            var node = requireNotNull(device.wait(Until.findObject(By.text(text)), 15000)) { "Missing $text" }
            while (!node.isClickable && node.parent != null) node = node.parent
            node.click()
        }
        suspend fun addPhoto(): String {
            val file = File(context.filesDir, "upload-photo-test-${System.nanoTime()}.jpg")
            files.add(file)
            val bitmap = Bitmap.createBitmap(32, 32, Bitmap.Config.ARGB_8888)
            bitmap.eraseColor(android.graphics.Color.GREEN)
            file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) }
            bitmap.recycle()
            return repository.addImage(sample, "close_up", file, "image/jpeg", 32, 32)
        }
        try {
            addPhoto(); addPhoto()
            repository.saveConfirm(sample, "unknown", "leaf", "unknown", "", "upload-photo-fixture")
            context.startActivity(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
            click("上传记录")
            assertNotNull(device.wait(Until.findObject(By.text("记录 ${sample.takeLast(8)} · 待上传")), 15000))
            requireNotNull(device.wait(Until.findObject(By.desc("照片预览")), 15000)).click()
            click("删除照片"); click("确认删除")
            assertTrue(device.wait(Until.hasObject(By.text("1 张图片 · 点击查看")), 10000))
            assertEquals(1, repository.imagesOf(sample).first().size)
            assertFalse(files.first().exists())
            requireNotNull(device.findObject(By.desc("照片预览"))).click()
            click("重拍此照片")
            click("取消重拍，保留原图")
            assertNotNull(device.wait(Until.findObject(By.text("上传记录")), 10000))
            assertEquals(1, repository.imagesOf(sample).first().size)
            click("编辑记录")
            assertNotNull(device.wait(Until.findObject(By.text("编辑图片")), 10000))
            assertNotNull(device.wait(Until.findObject(By.text("upload-photo-fixture")), 10000))
            click("返回")
            assertNotNull(device.wait(Until.findObject(By.text("上传记录")), 10000))
            withContext(Dispatchers.IO) { AppDatabase.get(context).sampleDao().setUploadId(sample, "test-declared") }
            click("查看详情")
            assertNotNull(device.wait(Until.findObject(By.text("采集详情")), 10000))
            assertTrue(device.wait(Until.gone(By.text("保存信息")), 5000))
            requireNotNull(device.wait(Until.findObject(By.desc("照片预览")), 10000)).click()
            assertNotNull(device.wait(Until.findObject(By.text("已开始上传的照片仅可预览")), 10000))
            val retake = requireNotNull(device.findObject(By.text("重拍此照片")))
            retake.click()
            assertTrue(device.wait(Until.hasObject(By.text("关闭预览")), 1000))
            assertFalse(device.hasObject(By.text("拍摄并替换原图")))
            assertEquals(1, repository.imagesOf(sample).first().size)
            click("关闭预览"); click("返回")
        } finally {
            withContext(Dispatchers.IO) {
                AppDatabase.get(context).openHelper.writableDatabase.delete("samples", "sampleId = ?", arrayOf(sample))
                files.forEach { it.delete() }
            }
        }
    }
}
