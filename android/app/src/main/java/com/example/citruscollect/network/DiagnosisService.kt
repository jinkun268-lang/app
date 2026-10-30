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
interface DiagnosisService {
    @POST("diagnoses")
    suspend fun diagnose(@Header("Authorization") authorization: String, @Header("X-Image-ID") imageId: String,
        @Query("crop_id") cropId: String, @Query("part") part: String, @Query("tree_age") treeAge: String,
        @Body image: RequestBody): DiagnosisResult
    @POST("diagnoses/advice")
    suspend fun advice(@Header("Authorization") authorization: String, @Body request: AdviceRequest): DiagnosisAdvice
}
