package com.example.citruscollect

import android.graphics.Bitmap
import androidx.test.core.app.ApplicationProvider
import androidx.room.Room
import com.example.citruscollect.data.*
import com.example.citruscollect.data.diagnosis.*
import com.example.citruscollect.data.entity.BatchEntity
import com.example.citruscollect.network.Backend
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class DiagnosisContributionTest {
    private class MemorySession : SessionStore {
        override val username = MutableStateFlow<String?>(null)
        override val token = MutableStateFlow<String?>(null)
        override val role = MutableStateFlow<String?>(null)
        override val baseUrl = MutableStateFlow<String?>(null)
        override suspend fun accessToken() = token.value
        override suspend fun refreshToken(): String? = null
        override suspend fun baseUrlValue() = baseUrl.value
        override suspend fun saveLogin(baseUrl: String, username: String, role: String, accessToken: String, refreshToken: String, expiresIn: Int) {
            this.baseUrl.value = baseUrl; this.username.value = username; this.role.value = role; token.value = accessToken
        }
        override suspend fun saveTokens(accessToken: String, refreshToken: String, expiresIn: Int) { token.value = accessToken }
        override suspend fun clear() { token.value = null }
    }

    @Test fun explicitContributionCopiesImageAndDoesNotRelabelOrDuplicate() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val collection = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        val diagnosis = Room.inMemoryDatabaseBuilder(context, DiagnosisDatabase::class.java).build()
        val dir = File(context.cacheDir, "diagnosis-test-${System.nanoTime()}").apply { mkdirs() }
        val store = MemorySession()
        try {
            store.saveLogin("http://localhost:18080/api/v1/", "diagnosis-test", "collector", "access", "refresh", 3600)
            val auth = AuthRepository(Backend(), store)
            val owner = requireNotNull(auth.currentOwnerKey())
            collection.sampleDao().insertBatch(BatchEntity(batchId = "open", name = "开放批次", ownerKey = owner))
            collection.sampleDao().insertBatch(BatchEntity(batchId = "closed", name = "已关闭", ownerKey = owner, closed = true))
            val repo = DiagnosisRepository(diagnosis.diagnosisDao(), auth, File(dir, "private"), collection)
            val image = File(dir, "input.jpg")
            image.outputStream().use { Bitmap.createBitmap(20,20,Bitmap.Config.ARGB_8888).compress(Bitmap.CompressFormat.JPEG, 90, it) }
            val id = repo.createDraft(image, "image/jpeg")
            try { repo.contribute(id, "closed"); fail("closed batch") } catch (_: IllegalArgumentException) { }
            val sampleId = repo.contribute(id, "open")
            assertEquals(sampleId, repo.contribute(id, "open"))
            val sample = collection.sampleDao().byId(sampleId)!!
            assertEquals("unknown", sample.classId)
            assertEquals("draft", sample.uploadState)
            assertNull(sample.uploadId)
            val pictures = collection.imageDao().bySampleList(sampleId)
            assertEquals(1, pictures.size)
            val row = diagnosis.diagnosisDao().get(id)!!
            assertNotEquals(row.imagePath, pictures.single().filePath)
            File(pictures.single().filePath).delete()
            assertTrue(File(row.imagePath).isFile)
            collection.imageDao().deleteSample(sampleId)
            assertNull(repo.observe(id).first()!!.contributedSampleId)
            val replacement = repo.contribute(id, "open")
            assertNotEquals(sampleId, replacement)
            assertEquals(replacement, repo.contribute(id, "open"))
            assertEquals(replacement, repo.observe(id).first()!!.contributedSampleId)
            assertEquals(1, collection.imageDao().bySampleList(replacement).size)
            assertTrue(File(row.imagePath).isFile)
        } finally {
            store.clear(); collection.close(); diagnosis.close(); dir.deleteRecursively()
        }
    }
}
