package com.example.citruscollect.network

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import retrofit2.http.*

@Serializable data class BatchDto(val batch_id: String = "", val name: String, val place: String = "", val collector: String = "", val default_cultivar_id: String = "unknown", val note: String = "", val closed: Boolean = false, val created_at: String? = null)
@Serializable data class BatchRequest(val name: String, val place: String = "", val collector: String = "", val default_cultivar_id: String = "unknown", val note: String = "", val closed: Boolean = false, val created_at: String? = null)
@Serializable data class BatchPage(val items: List<BatchDto>, val total: Int = 0, val page: Int = 1, val page_size: Int = 50)
@Serializable data class QuestionRequest(val question_id: String, val text: String, val sample_id: String? = null)
@Serializable data class QuestionDto(val question_id: String, val text: String, val sample_id: String? = null, val answer: String? = null, val status: String = "open", val created_at: String = "", val answered_at: String? = null, val images: List<JsonObject> = emptyList())
@Serializable data class QuestionPage(val items: List<QuestionDto>, val total: Int = 0, val page: Int = 1, val page_size: Int = 50)
interface CollectionService {
    @PUT("batches/{id}") suspend fun putBatch(@Header("Authorization") auth: String, @Path("id") id: String, @Body batch: BatchRequest): BatchDto
    @GET("batches") suspend fun batches(@Header("Authorization") auth: String, @Query("page") page: Int, @Query("page_size") pageSize: Int = 50): BatchPage
    @GET("samples/{id}") suspend fun review(@Header("Authorization") auth: String, @Path("id") id: String): JsonObject
    @POST("questions") suspend fun question(@Header("Authorization") auth: String, @Body question: QuestionRequest): QuestionDto
    @GET("questions") suspend fun questions(@Header("Authorization") auth: String, @Query("page") page: Int, @Query("page_size") pageSize: Int = 50): QuestionPage
}
