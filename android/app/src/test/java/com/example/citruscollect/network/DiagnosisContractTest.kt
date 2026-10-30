package com.example.citruscollect.network
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
class DiagnosisContractTest {
 @Test fun adviceRetrySendsOnlySignedReceipt() = runBlocking {
  val server = MockWebServer(); server.start()
  try {
   server.enqueue(MockResponse().setBody("""{"status":"unavailable","title":"暂无建议","message":"未配置知识","actions":[],"sources":[],"version":null}"""))
   val service = requireNotNull(Backend(server.url("/api/v1/").toString()).services().diagnosis)
   val advice = service.advice("Bearer token", AdviceRequest("signed-receipt"))
   assertEquals("unavailable", advice.status); assertTrue(advice.actions.isEmpty())
   val request = server.takeRequest()
   assertEquals("/api/v1/diagnoses/advice", request.path)
   assertEquals("Bearer token", request.getHeader("Authorization"))
   assertEquals("""{"receipt":"signed-receipt"}""", request.body.readUtf8())
  } finally { server.shutdown() }
 }
}
