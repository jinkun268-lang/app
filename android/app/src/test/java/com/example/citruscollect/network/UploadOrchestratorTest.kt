package com.example.citruscollect.network

import com.example.citruscollect.util.UuidV7
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.CopyOnWriteArrayList

class UploadOrchestratorTest {
    private lateinit var server: MockWebServer
    private lateinit var upload: UploadService
    private val putRequests = CopyOnWriteArrayList<RecordedRequest>()

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        val retrofit = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .client(OkHttpClient.Builder().retryOnConnectionFailure(false).build())
            .addConverterFactory(CitrusJson.asConverterFactory("application/json".toMediaType()))
            .build()
        upload = retrofit.create(UploadService::class.java)
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun json(code: Int, body: String) = MockResponse()
        .setResponseCode(code)
        .setHeader("Content-Type", "application/json")
        .setBody(body)

    private fun image(bytes: ByteArray): UploadImage {
        val file = File.createTempFile("img", ".jpg")
        file.writeBytes(bytes)
        return UploadImage(
            imageId = UuidV7.generate(),
            viewType = "close_up",
            capturedAt = "2026-10-20T09:12:33+08:00",
            deviceTimezone = "Asia/Shanghai",
            deviceModel = "Pixel 8",
            mimeType = "image/jpeg",
            width = 8,
            height = 6,
            fileSize = bytes.size.toLong(),
            sha256 = sha256(bytes),
            file = file
        )
    }

    private fun data(vararg images: UploadImage) = UploadRequestData(
        sampleId = "s1",
        treeId = null,
        cultivarId = "huyou",
        part = "leaf",
        classId = "unknown",
        symptoms = null,
        note = null,
        images = images.toList()
    )

    private fun receipt(request: RecordedRequest): String {
        val imageId = request.path!!.substringAfterLast('/')
        // clone 后读取，避免消费 RecordedRequest 的原始 body（测试还要校验字节）。
        val bytes = request.body.clone().readByteArray()
        return """{"upload_id":"u1","image_id":"$imageId","receive_status":"received",
            "sha256":"${sha256(bytes)}","file_size":${bytes.size}}"""
    }

    @Test fun lostAcknowledgementsRetryWithSameDeclarationAndImageBytes() = runBlocking {
        val img = image(byteArrayOf(1, 2, 3))
        val calls = mutableMapOf<String, Int>()
        val declarations = mutableListOf<String>()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val key = "${request.method} ${request.path}"
                val count = (calls[key] ?: 0) + 1
                calls[key] = count
                if (request.path == "/uploads") declarations.add(request.body.clone().readUtf8())
                if (request.method == "PUT") putRequests.add(request)
                // The server may already have applied the request, while its response is lost.
                if (count == 1) return MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AFTER_REQUEST)
                return when {
                    request.path == "/uploads" -> json(200, statusJson(emptyList(), listOf(img.imageId), emptyList()))
                    request.method == "GET" -> statusOk(emptyList(), listOf(img.imageId), emptyList())
                    request.method == "PUT" -> json(200, receipt(request))
                    request.path?.endsWith("/complete") == true -> completeOk(1)
                    else -> MockResponse().setResponseCode(404)
                }
            }
        }
        val outcome = UploadOrchestrator(upload).run(data(img), null, "Bearer token")
        assertEquals("u1", outcome.uploadId)
        assertEquals(1, outcome.imageCount)
        assertEquals(4, calls.size)
        assertTrue(calls.values.all { it == 2 })
        assertEquals(declarations[0], declarations[1])
        assertEquals(2, putRequests.size)
        assertArrayEquals(putRequests[0].body.clone().readByteArray(), putRequests[1].body.clone().readByteArray())
    }

    @Test fun persistentConnectionFailureStopsWithoutFakingCompletion() = runBlocking {
        val img = image(byteArrayOf(1))
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest) = MockResponse()
                .setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AFTER_REQUEST)
        }
        var failure: java.io.IOException? = null
        try { UploadOrchestrator(upload).run(data(img), "u1", "Bearer token") }
        catch (e: java.io.IOException) { failure = e }
        assertTrue(failure != null)
        assertEquals(2, server.requestCount)
    }

    @Test
    fun resumeUploadsOnlyMissingImagesWithRealBytes() = runBlocking {
        val img1 = image(byteArrayOf(1, 2, 3, 4))
        val img2 = image(byteArrayOf(5, 6, 7, 8, 9))
        var declares = 0

        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.method == "POST" && request.path == "/uploads" -> {
                    declares++
                    json(201, """{"upload_id":"u1","sample_id":"s1","state":"receiving",
                        "declared_at":"2026-10-20T01:20:02Z","received_images":[],"missing_images":[],
                        "invalid_images":[]}""")
                }
                request.method == "GET" -> json(
                    200,
                    """{"upload_id":"u1","sample_id":"s1","state":"receiving",
                        "declared_at":"2026-10-20T01:20:02Z",
                        "received_images":["${img1.imageId}"],
                        "missing_images":["${img2.imageId}"],"invalid_images":[]}"""
                )
                request.method == "PUT" -> {
                    putRequests.add(request)
                    json(201, receipt(request))
                }
                request.path?.endsWith("/complete") == true -> json(
                    200,
                    """{"upload_id":"u1","sample_id":"s1","state":"complete",
                        "upload_completed_at":"2026-10-20T01:22:10Z","image_count":2}"""
                )
                else -> MockResponse().setResponseCode(404)
            }
        }

        // 重入恢复：已有 upload_id，不再 declare。
        val outcome = UploadOrchestrator(upload).run(data(img1, img2), "u1", "Bearer token")

        assertEquals(0, declares)
        assertEquals(2, outcome.imageCount)
        // 只补 missing（img2），不整包重传。
        assertEquals(listOf(img2.imageId), putRequests.map { it.path!!.substringAfterLast('/') })
        val put = putRequests[0]
        assertEquals(img2.sha256, put.getHeader("X-Content-SHA256"))
        assertEquals(img2.fileSize, put.body.size)
        assertArrayEquals(img2.file.readBytes(), put.body.readByteArray())
    }

    @Test
    fun firstUploadDeclaresAndPersistsUploadId() = runBlocking {
        val img1 = image(byteArrayOf(1, 2, 3))
        var callbackId: String? = null

        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.method == "POST" && request.path == "/uploads" -> json(
                    201,
                    """{"upload_id":"u1","sample_id":"s1","state":"receiving",
                        "declared_at":"2026-10-20T01:20:02Z","received_images":[],
                        "missing_images":["${img1.imageId}"],"invalid_images":[]}"""
                )
                request.method == "GET" -> json(
                    200,
                    """{"upload_id":"u1","sample_id":"s1","state":"receiving",
                        "declared_at":"2026-10-20T01:20:02Z","received_images":[],
                        "missing_images":["${img1.imageId}"],"invalid_images":[]}"""
                )
                request.method == "PUT" -> json(201, receipt(request))
                request.path?.endsWith("/complete") == true -> json(
                    200,
                    """{"upload_id":"u1","sample_id":"s1","state":"complete",
                        "upload_completed_at":"2026-10-20T01:22:10Z","image_count":1}"""
                )
                else -> MockResponse().setResponseCode(404)
            }
        }

        val outcome = UploadOrchestrator(upload).run(data(img1), null, "Bearer token") { callbackId = it }

        assertEquals("u1", callbackId)
        assertEquals("u1", outcome.uploadId)
        assertEquals(1, outcome.imageCount)
    }

    @Test
    fun completeFailureDoesNotFakeSuccess() = runBlocking {
        val img1 = image(byteArrayOf(1, 2, 3))

        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.method == "GET" -> json(
                    200,
                    """{"upload_id":"u1","sample_id":"s1","state":"receiving",
                        "declared_at":"2026-10-20T01:20:02Z","received_images":[],
                        "missing_images":["${img1.imageId}"],"invalid_images":[]}"""
                )
                request.method == "PUT" -> json(201, receipt(request))
                request.path?.endsWith("/complete") == true -> json(
                    409,
                    """{"error":{"code":"MISSING_IMAGES","message":"仍有未收到或无效的图片",
                        "details":{"missing":["${img1.imageId}"],"invalid":[]},
                        "request_id":"019a0000-0000-7000-8000-0000000000aa"}}"""
                )
                else -> MockResponse().setResponseCode(404)
            }
        }

        var failed = false
        try {
            UploadOrchestrator(upload).run(data(img1), "u1", "Bearer token")
        } catch (e: HttpException) {
            failed = true
            assertEquals(409, e.code())
            assertEquals("MISSING_IMAGES", ApiErrors.parse(e)?.code)
        }
        assertTrue("complete 返回 409 时不得假成功", failed)
    }

    private fun completeJson(imageCount: Int, sampleId: String = "s1") =
        """{"upload_id":"u1","sample_id":"$sampleId","state":"complete",
            "upload_completed_at":"2026-10-20T01:22:10Z","image_count":$imageCount}"""

    private fun completeOk(imageCount: Int, sampleId: String = "s1") = json(200, completeJson(imageCount, sampleId))

    private fun statusJson(
        received: List<String>,
        missing: List<String>,
        invalid: List<String>,
        state: String = "receiving"
    ) =
        """{"upload_id":"u1","sample_id":"s1","state":"$state","declared_at":"2026-10-20T01:20:02Z",
            "received_images":[${received.joinToString { "\"$it\"" }}],
            "missing_images":[${missing.joinToString { "\"$it\"" }}],
            "invalid_images":[${invalid.joinToString { "\"$it\"" }}]}"""

    private fun statusOk(
        received: List<String>,
        missing: List<String>,
        invalid: List<String>,
        state: String = "receiving"
    ) = json(200, statusJson(received, missing, invalid, state))

    @Test
    fun missingAndInvalidAreBothReuploadedWhileReceivedSkipped() = runBlocking {
        val img1 = image(byteArrayOf(1))
        val img2 = image(byteArrayOf(2, 2))
        val img3 = image(byteArrayOf(3, 3, 3))
        var completeCalls = 0
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.method == "GET" -> statusOk(
                    received = listOf(img1.imageId),
                    missing = listOf(img2.imageId),
                    invalid = listOf(img3.imageId)
                )
                request.method == "PUT" -> {
                    putRequests.add(request)
                    json(201, receipt(request))
                }
                request.path?.endsWith("/complete") == true -> {
                    completeCalls++
                    completeOk(3)
                }
                else -> MockResponse().setResponseCode(404)
            }
        }

        val outcome = UploadOrchestrator(upload).run(data(img1, img2, img3), "u1", "Bearer token")

        // 需要补传的是 missing ∪ invalid；received 不重传
        assertEquals(listOf(img2.imageId, img3.imageId), putRequests.map { it.path!!.substringAfterLast('/') })
        assertEquals(1, completeCalls)
        assertEquals(3, outcome.imageCount)
    }

    @Test
    fun unknownOrContradictoryStatusIsRejectedWithoutComplete() = runBlocking {
        val img1 = image(byteArrayOf(1))
        val img2 = image(byteArrayOf(2))
        var completeCalls = 0
        val badStatuses = listOf(
            // 回执对应到别的上传
            """{"upload_id":"u1","sample_id":"other","state":"receiving","declared_at":"2026-10-20T01:20:02Z",
                "received_images":[],"missing_images":["${img1.imageId}","${img2.imageId}"],"invalid_images":[]}""",
            // 未知 state
            """{"upload_id":"u1","sample_id":"s1","state":"broken","declared_at":"2026-10-20T01:20:02Z",
                "received_images":[],"missing_images":["${img1.imageId}","${img2.imageId}"],"invalid_images":[]}""",
            // 未在本地声明中的未知 ID
            """{"upload_id":"u1","sample_id":"s1","state":"receiving","declared_at":"2026-10-20T01:20:02Z",
                "received_images":["${img1.imageId}"],"missing_images":["${UuidV7.generate()}"],"invalid_images":[]}""",
            // 同一 ID 同时出现在两个列表：互斥矛盾
            """{"upload_id":"u1","sample_id":"s1","state":"receiving","declared_at":"2026-10-20T01:20:02Z",
                "received_images":["${img1.imageId}"],"missing_images":["${img1.imageId}"],"invalid_images":["${img2.imageId}"]}""",
            // 并集未覆盖全部声明图片
            """{"upload_id":"u1","sample_id":"s1","state":"receiving","declared_at":"2026-10-20T01:20:02Z",
                "received_images":["${img1.imageId}"],"missing_images":[],"invalid_images":[]}"""
        )
        var statusBody = badStatuses.first()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.method == "GET" -> json(200, statusBody)
                request.method == "PUT" -> {
                    putRequests.add(request)
                    json(201, receipt(request))
                }
                request.path?.endsWith("/complete") == true -> {
                    completeCalls++
                    completeOk(2)
                }
                else -> MockResponse().setResponseCode(404)
            }
        }

        for (bad in badStatuses) {
            statusBody = bad
            var caught = false
            try {
                UploadOrchestrator(upload).run(data(img1, img2), "u1", "Bearer token")
            } catch (_: UploadException) {
                caught = true
            }
            assertTrue("未知或矛盾回执必须明确失败：$bad", caught)
        }
        assertEquals(0, putRequests.size)
        assertEquals(0, completeCalls)
    }

    @Test
    fun tamperedLocalFileIsRejectedBeforeAnyPutOrDeclare() = runBlocking {
        val good = image(byteArrayOf(1, 2, 3))
        val tampered = image(byteArrayOf(4, 5, 6))
        tampered.file.writeBytes(byteArrayOf(9, 9, 9)) // 大小一致但内容被改：哈希不符
        var declares = 0
        var statusBody = statusJson(emptyList(), listOf(tampered.imageId), emptyList())
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.method == "POST" && request.path == "/uploads" -> {
                    declares++
                    json(201, statusBody)
                }
                request.method == "GET" -> json(200, statusBody)
                request.method == "PUT" -> {
                    putRequests.add(request)
                    json(201, receipt(request))
                }
                request.path?.endsWith("/complete") == true -> completeOk(1)
                else -> MockResponse().setResponseCode(404)
            }
        }

        // 首次上传：声明前即校验失败，不创建上传会话
        var caught = false
        try {
            UploadOrchestrator(upload).run(data(good, tampered), null, "Bearer token")
        } catch (_: UploadException) {
            caught = true
        }
        assertTrue(caught)
        assertEquals(0, declares)
        assertEquals(0, putRequests.size)

        // 恢复路径：仅校验待 PUT 文件；大小不符时不发送对应 PUT
        val sizeWrong = image(byteArrayOf(7, 8))
        sizeWrong.file.writeBytes(byteArrayOf(7, 8, 9)) // 实际 3 字节，声明 2 字节
        statusBody = statusJson(emptyList(), listOf(sizeWrong.imageId), emptyList())
        caught = false
        try {
            UploadOrchestrator(upload).run(data(sizeWrong), "u1", "Bearer token")
        } catch (_: UploadException) {
            caught = true
        }
        assertTrue(caught)
        assertEquals(0, putRequests.size)
    }

    @Test
    fun mismatchedPutReceiptFailsWithoutComplete() = runBlocking {
        val img1 = image(byteArrayOf(1, 2, 3))
        var completeCalls = 0
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.method == "GET" -> statusOk(emptyList(), listOf(img1.imageId), emptyList())
                request.method == "PUT" -> {
                    putRequests.add(request)
                    val imageId = request.path!!.substringAfterLast('/')
                    val bytes = request.body.clone().readByteArray()
                    json(
                        201,
                        """{"upload_id":"u1","image_id":"$imageId","receive_status":"received",
                            "sha256":"${"0".repeat(64)}","file_size":${bytes.size}}"""
                    ) // 回执哈希与本次声明不符
                }
                request.path?.endsWith("/complete") == true -> {
                    completeCalls++
                    completeOk(1)
                }
                else -> MockResponse().setResponseCode(404)
            }
        }

        var caught = false
        try {
            UploadOrchestrator(upload).run(data(img1), "u1", "Bearer token")
        } catch (_: UploadException) {
            caught = true
        }
        assertTrue(caught)
        assertEquals(1, putRequests.size) // PUT 已发出
        assertEquals(0, completeCalls)    // 回执不符：不得继续 complete
    }

    @Test
    fun completeReceiptMismatchFails() = runBlocking {
        val img1 = image(byteArrayOf(1, 2, 3))
        var completeBody = completeJson(99) // 数量与声明不符
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.method == "GET" -> statusOk(emptyList(), listOf(img1.imageId), emptyList())
                request.method == "PUT" -> json(201, receipt(request))
                request.path?.endsWith("/complete") == true -> json(200, completeBody)
                else -> MockResponse().setResponseCode(404)
            }
        }

        var caught = false
        try {
            UploadOrchestrator(upload).run(data(img1), "u1", "Bearer token")
        } catch (_: UploadException) {
            caught = true
        }
        assertTrue(caught)

        completeBody = completeJson(1, sampleId = "other") // 不是本次 sample
        caught = false
        try {
            UploadOrchestrator(upload).run(data(img1), "u1", "Bearer token")
        } catch (_: UploadException) {
            caught = true
        }
        assertTrue(caught)
    }

    @Test
    fun allReceivedResumeCompletesEvenWhenLocalFilesAreGone() = runBlocking {
        val img1 = image(byteArrayOf(1))
        val img2 = image(byteArrayOf(2))
        data(img1, img2).images.forEach { it.file.delete() } // 本地文件已不可用
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.method == "GET" -> statusOk(listOf(img1.imageId, img2.imageId), emptyList(), emptyList())
                request.method == "PUT" -> {
                    putRequests.add(request)
                    json(201, receipt(request))
                }
                request.path?.endsWith("/complete") == true -> completeOk(2)
                else -> MockResponse().setResponseCode(404)
            }
        }

        val outcome = UploadOrchestrator(upload).run(data(img1, img2), "u1", "Bearer token")

        assertEquals(0, putRequests.size) // 已接收图片不重传、也不校验本地文件
        assertEquals(2, outcome.imageCount)
        assertEquals("2026-10-20T01:22:10Z", outcome.completedAt) // 服务端完成时间，非本地伪造
    }

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256")
            .digest(bytes)
            .joinToString("") { "%02x".format(it) }
}
