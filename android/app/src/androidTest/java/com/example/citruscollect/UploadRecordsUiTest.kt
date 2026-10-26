package com.example.citruscollect

import android.content.Intent
import android.graphics.Bitmap
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.example.citruscollect.data.AppDatabase
import com.example.citruscollect.network.UploadException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** Real service + Room + UI: uploaded records remain visible, withdraw, edit, and submit again. */
@RunWith(AndroidJUnit4::class)
class UploadRecordsUiTest {
    @Test fun uploadWithdrawEditAndReupload(): Unit = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val app = context.applicationContext as CitrusApplication
        val args = InstrumentationRegistry.getArguments()
        app.container.authRepository.login(requireNotNull(args.getString("baseUrl")),
            requireNotNull(args.getString("collectorUsername")), requireNotNull(args.getString("collectorPassword")))
        app.container.authRepository.bootstrap(forceRefresh = true)
        val repository = app.container.repository
        val device = UiDevice.getInstance(instrumentation)
        val ids = mutableSetOf<String>()
        val sampleId = repository.createSample("unknown", "leaf", "unknown", note = "upload-record-test").also { ids.add(it) }
        val file = File(context.filesDir, "upload-record-test-${System.nanoTime()}.jpg")
        val bitmap = Bitmap.createBitmap(32, 32, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(android.graphics.Color.GREEN)
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) }; bitmap.recycle()
        fun click(text: String) {
            var node = requireNotNull(device.wait(Until.findObject(By.text(text)), 15000)) { "Missing UI: $text" }
            while (!node.isClickable && node.parent != null) node = node.parent
            node.click()
        }
        var activeId = sampleId
        try {
            val oldImageId = repository.addImage(sampleId, "context", file, "image/jpeg", 32, 32)
            repository.saveConfirm(sampleId, "unknown", "leaf", "unknown", "", "upload-record-test")
            repository.upload(sampleId)
            assertTrue(repository.observeUploaded().first().any { it.sampleId == sampleId })
            try { repository.updateViewType(oldImageId, "other"); fail("Uploaded image was editable") } catch (_: UploadException) { }
            context.startActivity(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
            click("上传记录")
            requireNotNull(device.wait(Until.findObject(By.textStartsWith("已上传（")), 10000)).click()
            assertNotNull(device.wait(Until.findObject(By.text("记录 ${sampleId.takeLast(8)} · 已上传")), 10000))
            click("查看详情")
            assertNotNull(device.wait(Until.findObject(By.text("胡柚")), 10000))
            assertTrue(device.wait(Until.gone(By.text("字典加载失败，请重试")), 1000))
            assertTrue(device.wait(Until.gone(By.text("保存信息")), 3000))
            click("返回")
            click("撤回"); click("确认撤回")
            assertNotNull(device.wait(Until.findObject(By.text("已撤回，可修改后重新上传")), 20000))
            assertNull(repository.sampleById(sampleId).first())
            val restored = repository.observePending().first().single { it.note == "upload-record-test" }
            activeId = restored.sampleId; ids.add(activeId)
            val newImage = repository.imagesOf(activeId).first().single()
            assertNotEquals(sampleId, activeId); assertNotEquals(oldImageId, newImage.imageId)
            assertEquals("context", newImage.viewType); assertTrue(file.exists())
            click("编辑记录")
            assertNotNull(device.wait(Until.findObject(By.text("胡柚")), 10000))
            device.findObjects(By.clazz("android.widget.EditText")).last().text = "edited-after-withdrawal"
            click("保存信息")
            click("上传")
            assertNotNull(device.wait(Until.findObject(By.textStartsWith("上传完成：")), 30000))
            assertNotNull(device.wait(Until.findObject(By.text("记录 ${activeId.takeLast(8)} · 已上传")), 10000))
            assertEquals("uploaded", repository.sampleById(activeId).first()?.uploadState)
            assertEquals("edited-after-withdrawal", repository.sampleById(activeId).first()?.note)
        } finally {
            if (repository.sampleById(activeId).first()?.uploadState == "uploaded") {
                ids.add(repository.withdraw(activeId))
            }
            withContext(Dispatchers.IO) {
                ids.forEach { AppDatabase.get(context).sampleDao().deleteById(it) }
                file.delete()
            }
        }
    }
}
