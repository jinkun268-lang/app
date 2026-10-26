package com.example.citruscollect

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.example.citruscollect.data.AppDatabase
import com.example.citruscollect.data.AuthRepository
import com.example.citruscollect.data.DataStoreSessionStore
import com.example.citruscollect.data.repository.SampleRepository
import com.example.citruscollect.network.Backend
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import okhttp3.OkHttpClient
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.json.JSONObject

/**
 * 真实闭环（instrumentation）：连接真实 FastAPI，采集端用真实 Repository 完成
 * 登录 → 生成两张图落 Room → 确认 → 上传（declare/逐图 PUT/complete）。
 *
 * 参数（由主执行者通过 `-e` 传入，不能硬编码、不输出令牌）：
 *   baseUrl、collectorUsername、collectorPassword、adminUsername、adminPassword
 *
 * 末端管理员侧校验（预览/审核/质量/导出 ZIP）留给主执行者脚本，通过打印出的
 * `sample_id` 关联；本测试不冒充 Android 之外的上传。
 */
@RunWith(AndroidJUnit4::class)
class E2EUploadInstrumentedTest {

    private lateinit var db: AppDatabase
    private val databaseName = "client-chain-${System.nanoTime()}.db"

    @Before
    fun setUp() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        db = Room.databaseBuilder(context, AppDatabase::class.java, databaseName)
            .allowMainThreadQueries()
            .build()
    }

    @After
    fun tearDown() {
        db.close()
        InstrumentationRegistry.getInstrumentation().targetContext.deleteDatabase(databaseName)
    }

    @Test
    fun fullUploadFlowAgainstRealServer(): Unit = runBlocking {
        val args = InstrumentationRegistry.getArguments()
        val baseUrl = args.getString("baseUrl").orEmpty().ifBlank { Backend.DEFAULT_BASE_URL }
        val collectorUsername = requireArg(args, "collectorUsername")
        val collectorPassword = requireArg(args, "collectorPassword")
        // 管理员凭据由主执行者脚本用于末端校验，这里仅要求传入，不输出、不硬编码。
        requireArg(args, "adminUsername")
        requireArg(args, "adminPassword")

        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val attempts = AtomicInteger(0)
        val http = OkHttpClient.Builder().addInterceptor { chain ->
            if (chain.request().method == "PUT" && attempts.incrementAndGet() in 2..3) {
                throw IOException("Deliberate client interruption before second image")
            }
            chain.proceed(chain.request())
        }.build()
        val backend = Backend(baseUrl, http)
        val session = DataStoreSessionStore(context)
        val auth = AuthRepository(backend, session)
        val repository = SampleRepository(db.sampleDao(), db.imageDao(), backend, auth)

        auth.login(baseUrl, collectorUsername, collectorPassword)

        val sampleId = repository.createSample("unknown", "leaf", "unknown")
        val file1 = writeJpeg(context, "e2e_1", 32, 32, 0xFF3366AA.toInt())
        val file2 = writeJpeg(context, "e2e_2", 32, 32, 0xFF66AA33.toInt())
        val image1 = repository.addImage(sampleId, "close_up", file1, "image/jpeg", 32, 32)
        repository.addImage(sampleId, "context", file2, "image/jpeg", 32, 32)
        val bootstrap = auth.bootstrap()
        val cultivar = bootstrap.cultivars.first { it.is_active }.cultivar_id
        repository.saveConfirm(sampleId, cultivar, "leaf", "unknown", "", "Android中断恢复链路测试，不是研究样本")

        try {
            repository.upload(sampleId)
            fail("Expected interrupted upload")
        } catch (expected: com.example.citruscollect.network.UploadException) {
            assertEquals("failed", db.sampleDao().byId(sampleId)?.uploadState)
        }
        val uploadId = db.sampleDao().byId(sampleId)?.uploadId
        assertNotNull("Upload ID must survive failure", uploadId)
        val partial = auth.authorized { token -> backend.services().upload.status("Bearer $token", uploadId!!) }
        assertEquals(1, partial.received_images.size)
        assertEquals(1, partial.missing_images.size)
        db.close()
        db = Room.databaseBuilder(context, AppDatabase::class.java, databaseName).build()
        val resumed = SampleRepository(db.sampleDao(), db.imageDao(), backend, auth)
        val outcome = resumed.upload(sampleId)
        assertEquals("Only missing second image is retried after the bounded automatic retry", 4, attempts.get())
        File(context.getExternalFilesDir(null), "client-recovery-result.json").writeText(
            JSONObject().put("sample_id", sampleId).put("image_id", image1)
                .put("sha256", com.example.citruscollect.util.sha256Streaming(file1))
                .put("interruption_recovery", true).toString()
        )

        assertEquals(2, outcome.imageCount)
        assertEquals("uploaded", db.sampleDao().byId(sampleId)?.uploadState)

        Log.i(
            "E2EUpload",
            "UPLOAD_OK sample_id=$sampleId upload_id=${outcome.uploadId} " +
                "completed_at=${outcome.completedAt}"
        )
    }

    private fun requireArg(args: android.os.Bundle, key: String): String =
        args.getString(key).orEmpty().ifBlank {
            throw IllegalArgumentException("缺少 instrumentation 参数：$key")
        }

    private fun writeJpeg(context: Context, name: String, width: Int, height: Int, color: Int): File {
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(color)
        val file = File(context.cacheDir, "$name.jpg")
        FileOutputStream(file).use { out ->
            bitmap.compress(Bitmap.CompressFormat.JPEG, 90, out)
        }
        bitmap.recycle()
        return file
    }
}
