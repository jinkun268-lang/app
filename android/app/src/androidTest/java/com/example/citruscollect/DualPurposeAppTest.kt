package com.example.citruscollect

import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DualPurposeAppTest {
    @Test fun growerCanOpenIndependentIdentificationWithoutCreatingBatch() = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val app = instrumentation.targetContext.applicationContext as CitrusApplication
        val base = requireNotNull(InstrumentationRegistry.getArguments().getString("baseUrl"))
        app.container.authRepository.login(base, "collector1", "12345678")
        val before = app.container.repository.latestBatch()?.batchId
        val device = UiDevice.getInstance(instrumentation)
        instrumentation.targetContext.startActivity(Intent(instrumentation.targetContext, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        assertTrue("应有首页入口", device.wait(Until.hasObject(By.text("首页")), 8000))
        assertFalse(device.hasObject(By.text("知识库")))
        device.findObject(By.text("拍照识别")).click()
        assertTrue(device.wait(Until.hasObject(By.text("先看清，再判断")), 5000))
        assertTrue(device.hasObject(By.text("拍照")))
        assertTrue(device.hasObject(By.text("从相册选择")))
        assertEquals(before, app.container.repository.latestBatch()?.batchId)
        assertFalse(device.hasObject(By.text("知识库")))
        device.findObject(By.text("拍照")).click()
        assertTrue(device.wait(Until.hasObject(By.text("拍照并使用")), 8000))
        device.findObject(By.text("拍照并使用")).click()
        assertTrue(device.wait(Until.hasObject(By.text("先看清，再判断")), 10000))
        repeat(4) {
            if (!device.hasObject(By.text("开始识别"))) device.swipe(device.displayWidth / 2, device.displayHeight * 3 / 4, device.displayWidth / 2, device.displayHeight / 4, 30)
        }
        val consent = device.findObject(By.clazz("android.widget.CheckBox"))
        assertNotNull("应有单独上传同意", consent)
        consent.click()
        device.findObject(By.text("开始识别")).click()
        assertTrue(device.wait(Until.hasObject(By.text("识别报告")), 8000))
        assertTrue(device.wait(Until.hasObject(By.text("本次未能完成识别")), 10000))
        assertTrue(device.hasObject(By.text("重试识别")))
        assertEquals(before, app.container.repository.latestBatch()?.batchId)

    }
    @Test fun unavailableModelPreservesIndependentPhotoAndFailure() = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val app = instrumentation.targetContext.applicationContext as CitrusApplication
        val base = requireNotNull(InstrumentationRegistry.getArguments().getString("baseUrl"))
        app.container.authRepository.login(base, "collector1", "12345678")
        val repo = app.container.diagnosisRepository
        val before = app.container.repository.latestBatch()?.batchId
        val photo = java.io.File(app.cacheDir, "diagnosis-live-test.jpg")
        photo.outputStream().use { android.graphics.Bitmap.createBitmap(64,64,android.graphics.Bitmap.Config.ARGB_8888).compress(android.graphics.Bitmap.CompressFormat.JPEG,90,it) }
        val id = repo.createDraft(photo, "image/jpeg")
        photo.delete()
        try { repo.analyze(id); fail("模型未配置应返回503") } catch (e: retrofit2.HttpException) { assertEquals(503, e.code()) }
        val row = repo.observe(id).first()!!
        assertEquals("failed", row.status)
        assertNull(row.resultJson)
        assertTrue(java.io.File(row.imagePath).isFile)
        assertTrue(row.error.orEmpty().isNotBlank())
        assertEquals(before, app.container.repository.latestBatch()?.batchId)
        try { repo.analyze(id); fail("模型未配置应返回503") } catch (e: retrofit2.HttpException) { assertEquals(503, e.code()) }
        assertEquals("failed", repo.observe(id).first()!!.status)
    }
}
