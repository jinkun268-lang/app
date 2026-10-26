package com.example.citruscollect

import android.Manifest
import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** 拍摄 → 每张照片一条记录 → 单图编辑、重拍、删除。 */
@RunWith(AndroidJUnit4::class)
class PhotoUiTest {
    @get:Rule val cameraPermission = GrantPermissionRule.grant(Manifest.permission.CAMERA)

    @Test fun everyPhotoBecomesItsOwnRecordAndCanBeRetakenOrDiscarded(): Unit = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val app = context.applicationContext as CitrusApplication
        val args = InstrumentationRegistry.getArguments()
        app.container.authRepository.login(requireNotNull(args.getString("baseUrl")),
            requireNotNull(args.getString("collectorUsername")), requireNotNull(args.getString("collectorPassword")))
        val repository = app.container.repository
        val oldIds = repository.observePending().first().map { it.sampleId }.toSet()
        val device = UiDevice.getInstance(instrumentation)
        fun waitText(text: String): UiObject2 {
            val found = device.wait(Until.findObject(By.text(text)), 15000)
            if (found == null) {
                device.dumpWindowHierarchy(File(context.getExternalFilesDir(null), "photo-ui-failure.xml"))
                device.takeScreenshot(File(context.getExternalFilesDir(null), "photo-ui-failure.png"))
                error("Missing UI: $text")
            }
            return found
        }
        fun clickText(text: String) {
            var node = waitText(text)
            while (!node.isClickable && node.parent != null) node = node.parent
            node.click()
        }
        context.startActivity(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        clickText("开始采集")
        waitText("拍摄（已拍 0 张）")
        assertEquals(oldIds, repository.observePending().first().map { it.sampleId }.toSet())
        waitText("相机已就绪")

        clickText("拍摄")
        waitText("拍摄（已拍 1 张）")
        val first = repository.observePending().first().first { it.sampleId !in oldIds }
        val firstImage = repository.imagesOf(first.sampleId).first().single()
        assertEquals("draft", first.uploadState)

        // 第二张照片必须成为另一条记录，而不是追加到第一条。
        clickText("拍摄")
        waitText("拍摄（已拍 2 张）")
        val session = repository.observePending().first().filter { it.sampleId !in oldIds }
        assertEquals(2, session.size)
        session.forEach { assertEquals(1, repository.imagesOf(it.sampleId).first().size) }

        // 打开第一条记录（每张缩略图各自一条记录）。
        requireNotNull(device.wait(Until.findObject(By.desc("照片预览")), 15000)).click()
        waitText("编辑图片")
        waitText("下面的信息只属于这张图片，其他图片互不影响。")

        // 取消重拍保留原图。
        clickText("重拍")
        waitText("重拍照片 · 原图暂保留")
        clickText("返回")
        waitText("编辑图片")
        assertEquals(firstImage.filePath, repository.imagesOf(first.sampleId).first().single().filePath)
        assertTrue(File(firstImage.filePath).exists())

        // 重拍只替换当前图片。
        waitText("相机已就绪")
        clickText("重拍")
        waitText("重拍照片 · 原图暂保留")
        waitText("相机已就绪")
        clickText("拍摄并替换原图")
        waitText("编辑图片")
        val replacement = repository.imagesOf(first.sampleId).first().single()
        assertEquals(firstImage.imageId, replacement.imageId)
        assertNotEquals(firstImage.filePath, replacement.filePath)
        assertFalse(File(firstImage.filePath).exists())

        // 删除这条记录：记录与本地原图一起移除。
        clickText("删除")
        waitText("删除这张图片？")
        clickText("删除记录")
        waitText("开始采集")
        assertNull(repository.sampleById(first.sampleId).first())
        assertFalse(File(replacement.filePath).exists())
        assertEquals(1, repository.observePending().first().count { it.sampleId !in oldIds })
    }
}
