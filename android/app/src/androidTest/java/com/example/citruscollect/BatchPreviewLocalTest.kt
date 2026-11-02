package com.example.citruscollect

import androidx.activity.compose.setContent
import androidx.compose.runtime.CompositionLocalProvider
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.example.citruscollect.data.AppDatabase
import com.example.citruscollect.data.AuthRepository
import com.example.citruscollect.data.entity.BatchEntity
import com.example.citruscollect.data.entity.SampleEntity
import com.example.citruscollect.ui.LocalAppContainer
import com.example.citruscollect.ui.screens.CaptureHomeScreen
import com.example.citruscollect.ui.theme.CitrusTheme
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Exercises the real capture-home preview without a server, camera or uploaded files. */
@RunWith(AndroidJUnit4::class)
class BatchPreviewLocalTest {
    @Test fun previewFollowsSelectedBatchAndNeverFallsBackToOtherBatches(): Unit = runBlocking {
        check(BuildConfig.LOCAL_DEBUG) { "Only run in the isolated local debug app" }
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val container = (context.applicationContext as CitrusApplication).container
        val dao = AppDatabase.get(context).sampleDao()
        val device = UiDevice.getInstance(instrumentation)
        val url = "http://127.0.0.1:1/api/v1/"
        val username = "batch-preview-test"
        val owner = AuthRepository.accountKey(url, username)
        container.sessionStore.saveLogin(url, username, "collector", "local-access", "local-refresh", 1800)
        container.authRepository.ownerKey.first { it == owner }
        val prefix = "preview-${System.nanoTime()}"
        val batchA = "$prefix-a"
        val batchB = "$prefix-b"
        val emptyBatch = "$prefix-empty"
        listOf(batchA, batchB, emptyBatch).forEach {
            dao.insertBatch(BatchEntity(it, it, ownerKey = owner))
        }
        // More than six newer records in B must not hide the older records in A.
        val rows = listOf(
            SampleEntity("$prefix-A001", cultivarId = "huyou", part = "leaf", classId = "unknown", batchId = batchA, ownerKey = owner, createdAt = 1),
            SampleEntity("$prefix-A002", cultivarId = "huyou", part = "leaf", classId = "unknown", batchId = batchA, ownerKey = owner, uploadState = "uploaded", createdAt = 2),
            SampleEntity("$prefix-L001", cultivarId = "huyou", part = "leaf", classId = "unknown", ownerKey = owner, createdAt = 30)
        ) + (1..7).map {
            SampleEntity("$prefix-B00$it", cultivarId = "huyou", part = "leaf", classId = "unknown", batchId = batchB, ownerKey = owner, createdAt = 10L + it)
        }
        rows.forEach { dao.insert(it) }
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        try {
            scenario.onActivity { activity ->
                container.batchId = batchA
                activity.setContent {
                    CompositionLocalProvider(LocalAppContainer provides container) {
                        CitrusTheme { CaptureHomeScreen({}, {}, {}) }
                    }
                }
            }
            assertTrue("Current batch is missing from preview", device.wait(Until.hasObject(By.text("IMG-A002")), 10000))
            assertFalse("Another batch leaked into preview", device.hasObject(By.textStartsWith("IMG-B")))
            assertFalse(device.hasObject(By.text("IMG-L001")))
            assertTrue(device.hasObject(By.textContains("2 张图片")))

            scenario.onActivity { container.batchId = batchB }
            assertTrue(device.wait(Until.hasObject(By.text("IMG-B007")), 10000))
            assertFalse(device.hasObject(By.textStartsWith("IMG-A")))
            assertTrue(device.hasObject(By.textContains("7 张图片")))

            scenario.onActivity { container.batchId = emptyBatch }
            assertTrue(device.wait(Until.hasObject(By.text("还没有照片，拍下第一张就会生成记录")), 10000))
            assertFalse(device.hasObject(By.textStartsWith("IMG-")))

            scenario.onActivity { container.batchId = null }
            assertTrue(device.wait(Until.hasObject(By.text("还没有采集批次")), 10000))
            assertFalse("Unbatched history leaked into preview", device.hasObject(By.textStartsWith("IMG-")))
        } finally {
            scenario.close()
            rows.forEach { dao.deleteById(it.sampleId) }
            AppDatabase.get(context).openHelper.writableDatabase.execSQL(
                "DELETE FROM batches WHERE batchId IN (?, ?, ?)", arrayOf(batchA, batchB, emptyBatch))
            container.sessionStore.clear()
        }
    }
}
