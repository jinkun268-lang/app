package com.example.citruscollect.network

import com.example.citruscollect.util.sha256Streaming
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.time.Instant
import java.time.format.DateTimeParseException

/** 上传失败（业务或网络），message 为可展示给用户的中文说明。 */
class UploadException(message: String, cause: Throwable? = null) : Exception(message, cause)

/** 参与一次上传的图片规格（从 Room 实体投影而来，不依赖 Android 类型，便于 JVM 测试）。 */
data class UploadImage(
    val imageId: String,
    val viewType: String,
    val capturedAt: String,
    val deviceTimezone: String,
    val deviceModel: String,
    val mimeType: String,
    val width: Int,
    val height: Int,
    val fileSize: Long,
    val sha256: String,
    val file: File
)

data class UploadRequestData(
    val sampleId: String,
    val treeId: String?,
    val cultivarId: String,
    val part: String,
    val classId: String,
    val symptoms: String?,
    val note: String?,
    val images: List<UploadImage>
)

data class UploadOutcome(
    val uploadId: String,
    val sampleId: String,
    val completedAt: String,
    val imageCount: Int
)

/**
 * 上传编排：declare → 状态查询后只补 missing/invalid → complete。
 *
 * - 首次上传没有 uploadId 时先 declare（同声明服务端幂等重放 200）；
 *   declare 前先校验全部本地文件，避免声明成功后才发现文件不可用；
 * - 重入恢复：已有 uploadId 时直接 GET 状态，只补服务端要求重传的
 *   missing ∪ invalid；已 received 的图片不重传，也不因本地文件已
 *   不可用而阻止完成；
 * - status/PUT/complete 回执逐项与本次 upload_id、sample_id 及原始
 *   声明核对，未知 ID 或矛盾回执明确失败，不略过后标记成功；
 * - 成功仅凭服务端 complete 回执（幂等，完成时间为服务端首次完成时间），
 *   不使用本地时间伪造。
 */
class UploadOrchestrator(private val upload: UploadService) {

    suspend fun run(
        data: UploadRequestData,
        existingUploadId: String?,
        authorization: String,
        onUploadId: suspend (String) -> Unit = {}
    ): UploadOutcome {
        var uploadId = existingUploadId
        if (uploadId == null) {
            data.images.forEach { verifyLocalFile(it) }
            val declared = upload.declare(authorization, data.toDeclaration())
            if (declared.upload_id.isBlank() || declared.sample_id != data.sampleId) {
                throw UploadException("上传声明回执与本次上传不一致")
            }
            uploadId = declared.upload_id
            onUploadId(uploadId)
        }

        val status = upload.status(authorization, uploadId)
        val pending = validateStatus(status, uploadId, data)

        for (imageId in pending) {
            val image = data.images.firstOrNull { it.imageId == imageId }
                ?: throw UploadException("服务端要求补传未在本地清单中的图片：$imageId")
            verifyLocalFile(image)
            uploadImage(authorization, uploadId, image)
        }

        val complete = upload.complete(authorization, uploadId)
        return validateComplete(complete, uploadId, data)
    }

    /**
     * 契约校验（contracts UploadStatus）：state ∈ {receiving, complete}；
     * received/missing/invalid 只含声明清单中的 ID、三列表互斥、并集覆盖全部
     * 声明图片；complete 状态不得仍有待补传项。返回需要补传的 missing ∪ invalid。
     */
    private fun validateStatus(status: UploadStatus, uploadId: String, data: UploadRequestData): List<String> {
        if (status.upload_id != uploadId || status.sample_id != data.sampleId) {
            throw UploadException("上传状态回执与本次上传不一致")
        }
        if (status.state != "receiving" && status.state != "complete") {
            throw UploadException("未知上传状态：${status.state}")
        }
        val declared = data.images.map { it.imageId }.toSet()
        val listed = status.received_images + status.missing_images + status.invalid_images
        if (listed.any { it !in declared }) {
            throw UploadException("状态回执包含未在本地清单中的图片")
        }
        if (listed.size != listed.toSet().size) {
            throw UploadException("状态回执的图片列表相互矛盾")
        }
        if (listed.toSet() != declared) {
            throw UploadException("状态回执未覆盖全部声明图片")
        }
        if (status.state == "complete" && (status.missing_images.isNotEmpty() || status.invalid_images.isNotEmpty())) {
            throw UploadException("完成状态仍存在待补传图片，回执矛盾")
        }
        return (status.missing_images + status.invalid_images).distinct()
    }

    private suspend fun uploadImage(authorization: String, uploadId: String, image: UploadImage) {
        val body = image.file.asRequestBody(image.mimeType.toMediaType())
        val receipt = upload.uploadImage(
            authorization = authorization,
            uploadId = uploadId,
            imageId = image.imageId,
            sha256 = image.sha256,
            body = body
        )
        // 契约：成功回执 receive_status 恒为 received（仅表示字节完整，与人工质量审核无关），
        // upload_id/image_id/sha256/file_size 逐项与本次声明一致才继续。
        if (receipt.upload_id != uploadId ||
            receipt.image_id != image.imageId ||
            receipt.receive_status != "received" ||
            !receipt.sha256.equals(image.sha256, ignoreCase = true) ||
            receipt.file_size != image.fileSize
        ) {
            throw UploadException("图片 ${image.imageId} 的接收回执与本次上传不一致")
        }
    }

    /** 流式校验本地文件：存在/可读、大小与 SHA-256 与固定声明一致；IO 调度，不整包读入内存，不修改原文件。 */
    private suspend fun verifyLocalFile(image: UploadImage) {
        withContext(Dispatchers.IO) {
            if (!image.file.isFile || !image.file.canRead()) throw UploadException("图片文件缺失或不可读：${image.imageId}")
            if (image.file.length() != image.fileSize) throw UploadException("图片 ${image.imageId} 大小与声明不符")
            val actual = sha256Streaming(image.file)
            if (!actual.equals(image.sha256, ignoreCase = true)) {
                throw UploadException("图片 ${image.imageId} 内容与声明不符（SHA-256 校验失败）")
            }
        }
    }

    private fun validateComplete(
        complete: UploadCompleteResponse,
        uploadId: String,
        data: UploadRequestData
    ): UploadOutcome {
        if (complete.upload_id != uploadId || complete.sample_id != data.sampleId) {
            throw UploadException("完成回执与本次上传不一致")
        }
        if (complete.state != "complete") throw UploadException("完成回执状态异常：${complete.state}")
        if (complete.image_count != data.images.size) throw UploadException("完成回执图片数量与声明不符")
        if (complete.upload_completed_at.isBlank()) throw UploadException("完成回执缺少完成时间")
        try {
            Instant.parse(complete.upload_completed_at)
        } catch (e: DateTimeParseException) {
            throw UploadException("完成回执时间格式无效", e)
        }
        return UploadOutcome(
            uploadId = uploadId,
            sampleId = complete.sample_id,
            completedAt = complete.upload_completed_at,
            imageCount = complete.image_count
        )
    }

    private fun UploadRequestData.toDeclaration(): UploadDeclaration = UploadDeclaration(
        sample_id = sampleId,
        schema_version = 1,
        tree_id = treeId,
        cultivar_id = cultivarId,
        part = part,
        class_id = classId,
        symptoms = symptoms,
        note = note,
        images = images.map { image ->
            ImageDeclaration(
                image_id = image.imageId,
                view_type = image.viewType,
                captured_at = image.capturedAt,
                device_timezone = image.deviceTimezone,
                device_model = image.deviceModel,
                mime_type = image.mimeType,
                width = image.width,
                height = image.height,
                file_size = image.fileSize,
                sha256 = image.sha256
            )
        }
    )
}
