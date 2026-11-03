package com.example.citruscollect.network

import kotlinx.serialization.Serializable
import okhttp3.RequestBody
import retrofit2.http.*

@Serializable data class AdviceAction(val title: String, val detail: String)
@Serializable data class AdviceSource(val title: String, val url: String)
@Serializable data class DiagnosisAdvice(val status: String, val title: String, val message: String,
    val actions: List<AdviceAction> = emptyList(), val sources: List<AdviceSource> = emptyList(), val version: String? = null)
@Serializable data class DiagnosisResult(val recognition: RecognitionResult, val advice: DiagnosisAdvice, val receipt: String)
@Serializable data class AdviceRequest(val receipt: String)
@Serializable data class DiagnosisInput(
    val crop_id: String, val part: String, val tree_age: String, val symptom: String,
    val captured_at: String, val mime_type: String, val file_size: Long, val sha256: String, val device_model: String = ""
)
@Serializable data class DiagnosisPrepared(val record_id: String, val state: String, val inference_status: String? = null)
@Serializable data class DiagnosisSnapshot(
    val record_id: String, val state: String, val inference_status: String? = null,
    val current_name: String, val correction_version: Int, val inference_error: String? = null,
    val result: DiagnosisResult? = null
)
interface DiagnosisService {
    @PUT("diagnoses/{id}")
    suspend fun prepare(@Header("Authorization") authorization: String, @Path("id") id: String, @Body metadata: DiagnosisInput): DiagnosisPrepared
    @GET("diagnoses/{id}")
    suspend fun snapshot(@Header("Authorization") authorization: String, @Path("id") id: String): DiagnosisSnapshot
    @POST("diagnoses")
    suspend fun diagnose(@Header("Authorization") authorization: String, @Header("X-Image-ID") imageId: String,
        @Query("crop_id") cropId: String, @Query("part") part: String, @Query("tree_age") treeAge: String,
        @Body image: RequestBody): DiagnosisResult
    @POST("diagnoses/advice")
    suspend fun advice(@Header("Authorization") authorization: String, @Body request: AdviceRequest): DiagnosisAdvice
}
