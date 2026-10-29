package com.example.citruscollect

import android.graphics.Bitmap
import android.graphics.Color
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.example.citruscollect.network.Backend
import com.example.citruscollect.network.LoginRequest
import com.example.citruscollect.util.UuidV7
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** 显式传baseUrl才执行的真服务验收；保留带“功能验收”标记的记录供人工查看。 */
@RunWith(AndroidJUnit4::class)
class CollectionLiveTest {
    @Test fun closedOfflineBatchBackgroundUploadReviewAndRealExpertAnswer(): Unit = runBlocking {
        val base = requireNotNull(InstrumentationRegistry.getArguments().getString("baseUrl"))
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val container = (context.applicationContext as CitrusApplication).container
        container.authRepository.login(base, "collector1", "12345678")
        val repository = container.repository
        val batch = repository.createBatch("功能验收（测试数据）", "本地模拟器", "collector1", "huyou")
        val photo = File(context.filesDir, "live-${UuidV7.generate()}.png")
        val bitmap = Bitmap.createBitmap(128, 128, Bitmap.Config.ARGB_8888)
        for (y in 0 until 128) for (x in 0 until 128)
            bitmap.setPixel(x, y, if ((x / 8 + y / 8) % 2 == 0) Color.rgb(50, 110, 50) else Color.rgb(170, 200, 150))
        photo.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
        val id = repository.capturePhoto(photo, "image/png", 128, 128, batchId = batch, cultivarId = "huyou",
            latitude = 30.1, longitude = 120.2, locationAccuracyM = 12.0,
            expectedOwnerKey = container.authRepository.currentOwnerKey())
        repository.saveConfirm(id, "huyou", "leaf", "unknown", "功能验收图片，非真实病害", "保留原始采集标注")
        repository.setBatchClosed(batch, true)
        repository.enqueueUpload(id)
        val uploaded = withTimeout(60_000) {
            repository.sampleById(id).filterNotNull().first { it.uploadState == "uploaded" || it.uploadState == "failed" }
        }
        assertEquals(uploaded.uploadError, "uploaded", uploaded.uploadState)
        assertEquals(30.1, uploaded.latitude!!, 0.0001)
        assertTrue(repository.refreshReview(id).contains("review_status"))
        assertEquals("保留原始采集标注", repository.sampleById(id).first()?.note)
        val qid = UuidV7.generate()
        val question = repository.submitQuestion("功能验收：请确认图片是否可见（测试咨询）", id, qid)
        assertEquals(1, question.images.size)
        assertEquals(qid, repository.submitQuestion(question.text, id, qid).question_id)
        val backend = Backend(base)
        val expert = backend.services().auth.login(LoginRequest("expert", "12345678"))
        val request = Request.Builder().url(base.trimEnd('/') + "/questions/$qid/answer")
            .header("Authorization", "Bearer ${expert.access_token}")
            .patch("{\"answer\":\"功能验收答复：图片已收到；这是测试记录，不是诊断。\"}".toRequestBody("application/json".toMediaType())).build()
        OkHttpClient().newCall(request).execute().use { assertEquals(it.body?.string(), 200, it.code) }
        val answered = repository.questions().single { it.question_id == qid }
        assertEquals("answered", answered.status)
        assertTrue(answered.answer.orEmpty().contains("功能验收答复"))
        container.batchId = batch
    }
}
