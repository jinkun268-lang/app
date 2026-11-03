package com.example.citruscollect.data

import com.example.citruscollect.data.diagnosis.*
import com.example.citruscollect.network.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import okhttp3.mockwebserver.*
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class DiagnosisRepositoryTest {
    @Test fun metadataAndImageAreSentWithoutPostingTheResultBack() = runBlocking {
        val server = MockWebServer(); server.start()
        val dir = kotlin.io.path.createTempDirectory().toFile()
        try {
            val store = FakeSessionStore()
            store.saveLogin(server.url("/api/v1/").toString(), "alice", "collector", "access", "refresh", 3600)
            val dao = MemoryDao()
            val repo = DiagnosisRepository(dao, AuthRepository(Backend(), store), File(dir, "private"), imageSize = { 20 to 20 })
            val source = File(dir, "photo.jpg").apply { writeText("original-once") }
            val id = repo.createDraft(source, "image/jpeg", symptom = "叶片有斑")
            val hash = com.example.citruscollect.util.sha256Streaming(source)
            val result = """{"recognition":{"image_id":"$id","sha256":"$hash","model":"real","model_version":"1","scope":"leaf","candidates":[{"label":"x","name":"初判","score":0.9}],"warning":"","created_at":"2026-11-03T00:00:00Z"},"advice":{"status":"unmapped","title":"未匹配","message":"待确认"},"receipt":"signed"}"""
            server.enqueue(MockResponse().setBody("""{"record_id":"$id","state":"receiving","inference_status":"awaiting_image"}"""))
            server.enqueue(MockResponse().setBody(result))
            repo.analyze(id)
            assertEquals("succeeded", dao.get(id)!!.status)
            assertEquals("uploaded", dao.get(id)!!.archiveState)
            assertEquals(2, server.requestCount)
            val metadata = server.takeRequest()
            assertEquals("PUT", metadata.method)
            assertEquals("/api/v1/diagnoses/$id", metadata.path)
            val text = metadata.body.readUtf8()
            assertTrue(text.contains(hash)); assertTrue(text.contains("叶片有斑")); assertFalse(text.contains("recognition"))
            val inference = server.takeRequest()
            assertTrue(inference.path!!.startsWith("/api/v1/diagnoses?"))
            assertEquals("original-once", inference.body.readUtf8())
            val original = dao.get(id)!!.resultJson
            server.enqueue(MockResponse().setBody("""{"record_id":"$id","state":"complete","inference_status":"succeeded","current_name":"人工修正","correction_version":1,"result":$result}"""))
            repo.syncArchive(id)
            assertEquals("GET", server.takeRequest().method)
            assertEquals("人工修正", dao.get(id)!!.correctedName)
            assertEquals(original, dao.get(id)!!.resultJson)
        } finally { server.shutdown(); dir.deleteRecursively() }
    }
    @Test fun failedInferenceStillShowsTheServerRecordAndAllowsReadingManualCorrection() = runBlocking {
        val server = MockWebServer(); server.start()
        val dir = kotlin.io.path.createTempDirectory().toFile()
        try {
            val store = FakeSessionStore()
            store.saveLogin(server.url("/api/v1/").toString(), "alice", "collector", "access", "refresh", 3600)
            val dao = MemoryDao()
            val repo = DiagnosisRepository(dao, AuthRepository(Backend(), store), dir, imageSize = { 20 to 20 })
            val source = File(dir, "source").apply { writeText("image") }
            val id = repo.createDraft(source, "image/jpeg")
            server.enqueue(MockResponse().setBody("""{"record_id":"$id","state":"receiving","inference_status":"awaiting_image"}"""))
            server.enqueue(MockResponse().setResponseCode(503).setBody("{}"))
            server.enqueue(MockResponse().setBody("""{"record_id":"$id","state":"complete","inference_status":"failed","current_name":"系统识别错误","correction_version":0,"inference_error":"模型不可用","result":null}"""))
            try { repo.analyze(id); fail("inference should fail") } catch (_: retrofit2.HttpException) { }
            assertEquals("failed", dao.get(id)!!.status)
            assertEquals("uploaded", dao.get(id)!!.archiveState)
            assertNull(dao.get(id)!!.resultJson)
            assertEquals(3, server.requestCount)
            repeat(3) { server.takeRequest() }
            server.enqueue(MockResponse().setBody("""{"record_id":"$id","state":"complete","inference_status":"failed","current_name":"人工修正","correction_version":1,"result":null}"""))
            repo.syncArchive(id)
            assertEquals("人工修正", dao.get(id)!!.correctedName)
            assertNull(dao.get(id)!!.resultJson)
            assertEquals("GET", server.takeRequest().method)
        } finally { server.shutdown(); dir.deleteRecursively() }
    }
    class MemoryDao : DiagnosisDao {
        val rows = MutableStateFlow<List<DiagnosisEntity>>(emptyList())
        var cancelAfterLoadingWrite = false
        override fun observeAll(): Flow<List<DiagnosisEntity>> = rows
        override suspend fun get(id: String) = rows.value.find { it.id == id }
        override suspend fun insert(row: DiagnosisEntity) { rows.value += row }
        override suspend fun update(row: DiagnosisEntity) {
            rows.value = rows.value.map { if (it.id == row.id) row else it }
            if (cancelAfterLoadingWrite && row.status in setOf("analyzing", "advice_loading")) throw CancellationException("cancel immediately after Room commit")
        }
        override suspend fun recoverInterrupted() { rows.value = rows.value.map { if (it.status in listOf("analyzing", "advice_loading")) it.copy(status = if(it.resultJson == null) "failed" else "advice_failed") else it } }
        override suspend fun recoverArchiveUploads() { rows.value = rows.value.map { if (it.archiveState == "uploading") it.copy(archiveState = "pending") else it } }
    }
    @Test fun cancellationImmediatelyAfterLoadingWriteIsRetryableWithoutRestart() = runBlocking {
        val url = "http://localhost:18080/api/v1/"
        val store = FakeSessionStore()
        store.saveLogin(url, "alice", "collector", "access", "refresh", 3600)
        val auth = AuthRepository(Backend(), store)
        val key = requireNotNull(auth.currentOwnerKey())
        for (adviceOnly in listOf(false, true)) {
            val dao = MemoryDao()
            val previous = """{"recognition":{"image_id":"id","sha256":"hash","model":"real","model_version":"1","scope":"leaf","candidates":[{"label":"x","name":"x","score":0.9}],"warning":"","created_at":"now"},"advice":{"status":"unmapped","title":"未匹配","message":"待确认"},"receipt":"signed"}"""
            dao.insert(DiagnosisEntity("id", key, "/private/original", "image/jpeg", resultJson = if (adviceOnly) previous else null))
            val repo = DiagnosisRepository(dao, auth, File("unused"))
            repo.recoverInterrupted()
            dao.cancelAfterLoadingWrite = true
            try {
                if (adviceOnly) repo.retryAdvice("id") else repo.analyze("id")
                fail("cancellation must propagate")
            } catch (_: CancellationException) { }
            val row = requireNotNull(dao.get("id"))
            assertEquals(if (adviceOnly) "advice_failed" else "failed", row.status)
            assertEquals("/private/original", row.imagePath)
            assertEquals(if (adviceOnly) previous else null, row.resultJson)
        }
    }
    @Test fun importsAreLocalAndFailedRequestKeepsPrivateImageAndObservation() = runBlocking {
        val server = MockWebServer(); server.start()
        val dir = kotlin.io.path.createTempDirectory().toFile()
        try {
            val store = FakeSessionStore()
            store.saveLogin(server.url("/api/v1/").toString(), "alice", "collector", "access", "refresh", 3600)
            val dao = MemoryDao()
            val repo = DiagnosisRepository(dao, AuthRepository(Backend(), store), File(dir, "private"), imageSize = { 20 to 20 })
            val source = File(dir, "camera.jpg").apply { writeText("test-image") }
            val id = repo.createDraft(source, "image/jpeg")
            assertEquals(0, server.requestCount)
            assertNotEquals(source.absolutePath, dao.get(id)!!.imagePath)
            repo.saveFollowUp(id, "2026-11-01", "三天后检查")
            server.enqueue(MockResponse().setResponseCode(503).setBody("{}"))
            try { repo.analyze(id); fail("must fail without real model") } catch (_: retrofit2.HttpException) { }
            assertEquals("failed", dao.get(id)!!.status)
            assertNull(dao.get(id)!!.resultJson)
            assertTrue(File(dao.get(id)!!.imagePath).isFile)
            assertEquals("三天后检查", dao.get(id)!!.observation)
            assertEquals("/api/v1/diagnoses/$id", server.takeRequest().path)
            store.saveLogin(server.url("/api/v1/").toString(), "bob", "collector", "bob", "refresh", 3600)
            assertTrue(repo.observeAll().first().isEmpty())
            try { repo.analyze(id); fail("cross-account must fail") } catch (_: AuthExpiredException) { }
            assertEquals(1, server.requestCount)
        } finally { server.shutdown(); dir.deleteRecursively() }
    }
    @Test fun accountSwitchDuringRequestCannotPublishResult() = runBlocking {
        val server = MockWebServer(); server.start()
        val dir = kotlin.io.path.createTempDirectory().toFile()
        try {
            val store = FakeSessionStore(); val url = server.url("/api/v1/").toString()
            store.saveLogin(url, "alice", "collector", "access", "refresh", 3600)
            val dao = MemoryDao()
            val repo = DiagnosisRepository(dao, AuthRepository(Backend(), store), File(dir, "private"), imageSize = { 20 to 20 })
            val source = File(dir, "source").apply { writeText("test-image") }
            val id = repo.createDraft(source, "image/jpeg")
            val hash = com.example.citruscollect.util.sha256Streaming(source)
            server.enqueue(MockResponse().setBody("""{"record_id":"$id","state":"receiving","inference_status":"awaiting_image"}"""))
            server.enqueue(MockResponse().setBody("""{"recognition":{"image_id":"$id","sha256":"$hash","model":"real","model_version":"1","scope":"leaf","candidates":[{"label":"x","name":"x","score":0.9}],"warning":"","created_at":"now"},"advice":{"status":"unmapped","title":"未匹配","message":"待确认"},"receipt":"signed"}""").setBodyDelay(500, java.util.concurrent.TimeUnit.MILLISECONDS))
            val job = async { runCatching { repo.analyze(id) } }
            withContext(Dispatchers.IO) { server.takeRequest(); server.takeRequest() }
            store.saveLogin(url, "bob", "collector", "bob", "refresh", 3600)
            assertTrue(job.await().isFailure)
            assertNull(dao.get(id)!!.resultJson)
            assertTrue(repo.observeAll().first().isEmpty())
            assertTrue(File(dao.get(id)!!.imagePath).isFile)
        } finally { server.shutdown(); dir.deleteRecursively() }
    }
    @Test fun cancellationPersistsRetryableStatusAndOriginal() = runBlocking {
        val server = MockWebServer(); server.start()
        val dir = kotlin.io.path.createTempDirectory().toFile()
        try {
            val store = FakeSessionStore()
            store.saveLogin(server.url("/api/v1/").toString(), "alice", "collector", "access", "refresh", 3600)
            val dao = MemoryDao()
            val repo = DiagnosisRepository(dao, AuthRepository(Backend(), store), File(dir, "private"), imageSize = { 20 to 20 })
            val source = File(dir, "source").apply { writeText("test-image") }
            val id = repo.createDraft(source, "image/jpeg")
            server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
            val job = launch { repo.analyze(id) }
            withContext(Dispatchers.IO) { server.takeRequest() }
            job.cancelAndJoin()
            assertEquals("failed", dao.get(id)!!.status)
            assertTrue(File(dao.get(id)!!.imagePath).isFile)
            assertNull(dao.get(id)!!.resultJson)
        } finally { server.shutdown(); dir.deleteRecursively() }
    }
    @Test fun oldCameraCallbackCannotImportForNewAccount() = runBlocking {
        val dir = kotlin.io.path.createTempDirectory().toFile()
        try {
            val store = FakeSessionStore()
            val url = "http://localhost:18080/api/v1/"
            store.saveLogin(url, "bob", "collector", "bob", "refresh", 3600)
            val dao = MemoryDao()
            val repo = DiagnosisRepository(dao, AuthRepository(Backend(), store), dir, imageSize = { 20 to 20 })
            val source = File(dir, "camera.jpg").apply { writeText("test") }
            try { repo.createDraft(source, "image/jpeg", expectedOwnerKey = AuthRepository.accountKey(url, "alice")); fail("stale callback") } catch (_: AuthExpiredException) { }
            assertTrue(dao.rows.value.isEmpty())
        } finally { dir.deleteRecursively() }
    }
    @Test fun processRestartMakesInProgressRecordRetryable() = runBlocking {
        val dao = MemoryDao()
        dao.insert(DiagnosisEntity("id", "owner", "/private/image", "image/jpeg", status = "analyzing"))
        val repo = DiagnosisRepository(dao, AuthRepository(Backend(), FakeSessionStore()), File("unused"))
        repo.recoverInterrupted()
        assertEquals("failed", dao.get("id")!!.status)
        assertEquals("/private/image", dao.get("id")!!.imagePath)
    }
}
