package com.example.citruscollect.network

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class CollectionContractTest {
    @Test fun batchPutDoesNotSendResponseOnlyFieldsAndNullResponseUsesDefaults() = kotlinx.coroutines.runBlocking {
        val server = okhttp3.mockwebserver.MockWebServer()
        server.start()
        try {
            server.enqueue(okhttp3.mockwebserver.MockResponse().setHeader("Content-Type", "application/json").setBody("""{"batch_id":"id","name":"采集","default_cultivar_id":null,"note":null,"closed":false}"""))
            val result = requireNotNull(Backend(server.url("/").toString()).services().collection)
                .putBatch("Bearer collector", "id", BatchRequest(name = "采集"))
            val request = server.takeRequest()
            val body = CitrusJson.json.parseToJsonElement(request.body.readUtf8()).jsonObject
            assertEquals("PUT", request.method)
            assertEquals("/batches/id", request.path)
            assertEquals("Bearer collector", request.getHeader("Authorization"))
            assertEquals(setOf("name", "place", "collector", "default_cultivar_id", "note", "closed"), body.keys)
            assertEquals("unknown", result.default_cultivar_id)
            assertEquals("", result.note)
        } finally { server.shutdown() }
    }

    @Test fun nullableLocationIsAbsentRatherThanInventedZero() {
        val declaration = UploadDeclaration("sample", 1, cultivar_id = "unknown", part = "leaf", class_id = "unknown", images = emptyList())
        val json = CitrusJson.json.parseToJsonElement(CitrusJson.json.encodeToString(declaration)).jsonObject
        assertFalse(json.containsKey("latitude"))
        assertFalse(json.containsKey("longitude"))
    }
    @Test fun questionsAcceptRealHumanReplyAndServerAdditionalFields() {
        val dto = CitrusJson.json.decodeFromString<QuestionDto>("""{"question_id":"id","text":"叶片发黄","status":"answered","answer":"请补充叶背照片","owner_id":"owner","created_at":"2026-10-29T01:00:00Z","sample":null,"images":[]}""")
        assertEquals("请补充叶背照片", dto.answer)
        assertEquals("answered", dto.status)
    }
    @Test fun batchPaginationDecodesClosedState() {
        val page = CitrusJson.json.decodeFromString<BatchPage>("""{"items":[{"batch_id":"id","name":"采集","closed":true,"owner_id":"owner","updated_at":"today"}],"total":51,"page":2,"page_size":50}""")
        assertTrue(page.items.single().closed)
        assertEquals(51, page.total)
    }
}
