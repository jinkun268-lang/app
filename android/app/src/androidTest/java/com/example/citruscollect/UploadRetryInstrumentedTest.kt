package com.example.citruscollect

import android.graphics.Bitmap
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.example.citruscollect.data.AppDatabase
import com.example.citruscollect.data.AuthRepository
import com.example.citruscollect.data.DataStoreSessionStore
import com.example.citruscollect.data.repository.SampleRepository
import com.example.citruscollect.network.Backend
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

@RunWith(AndroidJUnit4::class)
class UploadRetryInstrumentedTest {
    @Test fun realServerRecoversFromLostResponsesAtEveryUploadStep(): Unit = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val args = InstrumentationRegistry.getArguments()
        val calls = ConcurrentHashMap<String, AtomicInteger>()
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            val request = chain.request()
            val response = chain.proceed(request)
            if (request.url.encodedPath.startsWith("/api/v1/uploads")) {
                val key = "${request.method} ${request.url.encodedPath}"
                if (calls.computeIfAbsent(key) { AtomicInteger() }.incrementAndGet() == 1) {
                    response.close()
                    throw IOException("Simulated lost response after server applied request")
                }
            }
            response
        }.build()
        val backend = Backend(requireNotNull(args.getString("baseUrl")), client)
        val auth = AuthRepository(backend, DataStoreSessionStore(context))
        auth.login(backend.baseUrl(), requireNotNull(args.getString("collectorUsername")), requireNotNull(args.getString("collectorPassword")))
        val db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        val repository = SampleRepository(db.sampleDao(), db.imageDao(), backend, auth)
        val folder = File(context.cacheDir, "retry-test-${System.nanoTime()}").apply { mkdirs() }
        val id = repository.createSample("unknown", "leaf", "unknown", note = "retry test fixture")
        try {
            repeat(2) { index ->
                val file = File(folder, "$index.jpg")
                val bitmap = Bitmap.createBitmap(32, 32, Bitmap.Config.ARGB_8888)
                bitmap.eraseColor(if (index == 0) android.graphics.Color.GREEN else android.graphics.Color.BLUE)
                file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) }; bitmap.recycle()
                repository.addImage(id, "close_up", file, "image/jpeg", 32, 32)
            }
            repository.saveConfirm(id, "unknown", "leaf", "unknown", "", "retry test fixture")
            val outcome = repository.upload(id)
            assertEquals(2, outcome.imageCount)
            assertEquals("uploaded", repository.sampleById(id).first()?.uploadState)
            assertEquals(5, calls.size)
            assertTrue(calls.values.all { it.get() == 2 })
        } finally {
            if (repository.sampleById(id).first()?.uploadState == "uploaded") repository.withdraw(id)
            db.close(); folder.deleteRecursively()
        }
    }
}
