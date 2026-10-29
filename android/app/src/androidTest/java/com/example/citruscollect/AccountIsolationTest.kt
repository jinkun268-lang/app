package com.example.citruscollect

import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.example.citruscollect.data.*
import com.example.citruscollect.data.entity.SampleEntity
import com.example.citruscollect.data.repository.SampleRepository
import com.example.citruscollect.network.Backend
import com.example.citruscollect.network.UploadException
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AccountIsolationTest {
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
    @Test fun onlyExplicitlyQueuedSamplesResumeAndPermanentFailuresStayStopped(): Unit = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        val store = MemorySession()
        store.saveLogin("http://localhost:18080/api/v1/", "alice", "collector", "a", "r", 100)
        val backend = Backend()
        val auth = AuthRepository(backend, store)
        val repository = SampleRepository(db.sampleDao(), db.imageDao(), backend, auth)
        val scheduled = mutableListOf<String>()
        repository.uploadScheduler = { id, _ -> scheduled.add(id) }
        try {
            val pending = repository.createSample("unknown", "leaf", "unknown")
            repository.setUploadState(pending, "pending")
            repository.resumeQueuedUploads()
            assertTrue(scheduled.isEmpty())
            repository.enqueueUpload(pending)
            assertEquals("queued", db.sampleDao().byId(pending)?.uploadState)
            scheduled.clear()
            repository.resumeQueuedUploads()
            assertEquals(listOf(pending), scheduled)
            repository.queueState(pending, auth.currentOwnerKey()!!, "failed")
            scheduled.clear()
            repository.resumeQueuedUploads()
            assertTrue(scheduled.isEmpty())
        } finally { db.close() }
    }
    @Test fun legacyAndOtherAccountsStayRetainedButCannotBeReadEditedOrQueued(): Unit = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        val store = MemorySession()
        val backend = Backend()
        val auth = AuthRepository(backend, store)
        val repository = SampleRepository(db.sampleDao(), db.imageDao(), backend, auth)
        try {
            db.sampleDao().insert(SampleEntity("legacy", cultivarId = "unknown", part = "leaf", classId = "unknown"))
            store.saveLogin("http://localhost:18080/api/v1/", "alice", "collector", "a", "r", 100)
            val alice = repository.createSample("unknown", "leaf", "unknown")
            val batch = repository.createBatch("alice", "", "alice", "unknown")
            store.saveLogin("http://localhost:18080/api/v1/", "bob", "collector", "b", "r", 100)
            assertTrue(repository.observePending().first().isEmpty())
            assertTrue(repository.observeBatches().first().isEmpty())
            assertNull(repository.sampleById(alice).first())
            assertTrue(repository.imagesOf(alice).first().isEmpty())
            for (id in listOf(alice, "legacy")) {
                try { repository.saveDraftMetadata(id, "unknown", "leaf", "unknown", "", "wrong"); fail("must reject foreign edit") } catch (_: UploadException) { }
                try { repository.enqueueUpload(id); fail("must reject foreign upload") } catch (_: UploadException) { }
            }
            try { repository.setBatchClosed(batch, true); fail("must reject foreign batch") } catch (_: UploadException) { }
            assertEquals(1, repository.observeLegacyCount().first())
            assertEquals(0, repository.cleanupAbandonedEmptyDrafts())
            assertNotNull(db.sampleDao().byId("legacy"))
            store.saveLogin("http://localhost:18080/api/v1/", "alice", "collector", "a", "r", 100)
            assertEquals(alice, repository.observePending().first().single().sampleId)
            store.saveLogin("http://localhost:18081/api/v1/", "alice", "collector", "a", "r", 100)
            assertTrue(repository.observePending().first().isEmpty())
        } finally { db.close() }
    }
}
