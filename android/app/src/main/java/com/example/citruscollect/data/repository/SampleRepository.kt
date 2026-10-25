package com.example.citruscollect.data.repository

import android.os.Build
import com.example.citruscollect.data.AuthRepository
import com.example.citruscollect.data.dao.ImageDao
import com.example.citruscollect.data.dao.SampleDao
import com.example.citruscollect.data.entity.ImageEntity
import com.example.citruscollect.data.entity.SampleEntity
import com.example.citruscollect.network.ApiErrors
import com.example.citruscollect.network.AuthExpiredException
import com.example.citruscollect.network.Backend
import com.example.citruscollect.network.UploadException
import com.example.citruscollect.network.UploadImage
import com.example.citruscollect.network.UploadOrchestrator
import com.example.citruscollect.network.UploadOutcome
import com.example.citruscollect.network.UploadRequestData
import com.example.citruscollect.util.UuidV7
import com.example.citruscollect.util.formatCapturedAt
import com.example.citruscollect.util.sha256Streaming
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import retrofit2.HttpException
import java.io.File
import java.util.TimeZone

/** 采集数据的本地仓库，负责 Room 读写与上传编排。 */
class SampleRepository(
    private val sampleDao: SampleDao,
    private val imageDao: ImageDao,
    private val backend: Backend,
    private val authRepository: AuthRepository
) {
    private val uploadMutex = Mutex()

    fun observePending(): Flow<List<SampleEntity>> = sampleDao.observePending()
    fun observePendingCount(): Flow<Int> = sampleDao.observePendingCount()
    fun imagesOf(sampleId: String): Flow<List<ImageEntity>> = imageDao.bySample(sampleId)
    fun sampleById(sampleId: String): Flow<SampleEntity?> = sampleDao.observeById(sampleId)

    suspend fun createSample(
        cultivarId: String,
        part: String,
        classId: String,
        symptoms: String = "",
        note: String = ""
    ): String {
        val id = UuidV7.generate()
        sampleDao.insert(
            SampleEntity(
                sampleId = id,
                cultivarId = cultivarId,
                part = part,
                classId = classId,
                symptoms = symptoms,
                note = note
            )
        )
        return id
    }

    /** 拍摄后立即落 Room：返回生成的 imageId，供取消重复导入参考。 */
    suspend fun addImage(
        sampleId: String,
        viewType: String,
        file: File,
        mimeType: String,
        width: Int,
        height: Int,
        capturedAt: Long = System.currentTimeMillis()
    ): String {
        val id = UuidV7.generate()
        imageDao.insert(
            ImageEntity(
                imageId = id,
                sampleId = sampleId,
                viewType = viewType,
                filePath = file.absolutePath,
                mimeType = mimeType,
                width = width,
                height = height,
                fileSize = file.length(),
                sha256 = sha256Streaming(file),
                capturedAt = capturedAt
            )
        )
        return id
    }

    suspend fun setUploadState(sampleId: String, state: String) {
        sampleDao.byId(sampleId)?.let { sampleDao.update(it.copy(uploadState = state)) }
    }

    suspend fun updateViewType(imageId: String, viewType: String) {
        imageDao.updateViewType(imageId, viewType)
    }

    /** 信息确认：写入最终采集字段并把对象置为待上传。 */
    suspend fun saveConfirm(
        sampleId: String,
        cultivarId: String,
        part: String,
        classId: String,
        symptoms: String,
        note: String
    ) {
        sampleDao.byId(sampleId)?.let {
            sampleDao.update(
                it.copy(
                    cultivarId = cultivarId,
                    part = part,
                    classId = classId,
                    symptoms = symptoms,
                    note = note,
                    uploadState = "pending"
                )
            )
        }
    }

    /**
     * 上传一个对象：declare → 逐图 PUT（只补 missing）→ complete。
     * 串行互斥避免双击重复；成功仅凭服务端 complete 回执；失败保留待传并记录错误。
     */
    suspend fun upload(sampleId: String): UploadOutcome = uploadMutex.withLock {
        val sample = sampleDao.byId(sampleId) ?: throw UploadException("对象不存在")
        if (sample.uploadState == "uploaded") {
            throw UploadException("该对象已上传")
        }
        if (sample.uploadState == "draft") {
            throw UploadException("请先完成拍摄与信息确认")
        }

        val images = imageDao.bySampleList(sampleId)
        validateForUpload(sample, images)

        sampleDao.update(sample.copy(uploadState = "uploading", uploadError = null))

        val data = UploadRequestData(
            sampleId = sample.sampleId,
            treeId = null,
            cultivarId = sample.cultivarId,
            part = sample.part,
            classId = sample.classId,
            symptoms = sample.symptoms.ifBlank { null },
            note = sample.note.ifBlank { null },
            images = images.map { image -> image.toUploadImage() }
        )

        return try {
            val outcome = authRepository.authorizedServices { services, token ->
                // 认证刷新会重放整个编排：每次执行都读取当前已持久化的 uploadId，
                // 不使用闭包捕获的旧 sample.uploadId，避免重复创建上传会话。
                val currentUploadId = sampleDao.byId(sampleId)?.uploadId
                UploadOrchestrator(services.upload).run(
                    data = data,
                    existingUploadId = currentUploadId,
                    authorization = "Bearer $token"
                ) { uploadId -> sampleDao.setUploadId(sampleId, uploadId) }
            }
            // 用最新记录更新本地状态，避免旧实体覆盖上传期间已保存的 uploadId 等字段
            val latest = sampleDao.byId(sampleId) ?: sample
            sampleDao.update(latest.copy(uploadState = "uploaded", uploadId = outcome.uploadId, uploadError = null))
            outcome
        } catch (e: CancellationException) {
            // 取消：只做最小的本地清理，恢复到可重试状态（保留 uploadId，不置错误信息），
            // NonCancellable 仅包围这段清理，不包围任何网络流程。
            withContext(NonCancellable) {
                val latest = sampleDao.byId(sampleId) ?: sample
                if (latest.uploadState == "uploading") {
                    sampleDao.update(latest.copy(uploadState = "failed", uploadError = null))
                }
            }
            throw e
        } catch (e: UploadException) {
            // 失败同样用最新记录，保留已保存的 uploadId 供下次补传
            val latest = sampleDao.byId(sampleId) ?: sample
            sampleDao.update(latest.copy(uploadState = "failed", uploadError = e.message))
            throw e
        } catch (e: Exception) {
            val message = friendlyMessage(e)
            val latest = sampleDao.byId(sampleId) ?: sample
            sampleDao.update(latest.copy(uploadState = "failed", uploadError = message))
            throw UploadException(message, e)
        }
    }

    private fun validateForUpload(sample: SampleEntity, images: List<ImageEntity>) {
        if (images.isEmpty()) throw UploadException("没有图片，请先拍摄")
        if (images.size > MAX_IMAGES) throw UploadException("每份对象最多 12 张图")
        images.forEach { if (it.fileSize > MAX_IMAGE_BYTES) throw UploadException("单图不能超过 20MiB") }
        if (images.sumOf { it.fileSize } > MAX_TOTAL_BYTES) throw UploadException("图片合计不能超过 120MiB")
        // 旧版本用 UUIDv4 生成的草稿不能伪造 uploaded：给出明确错误，避免被服务端 422 拒绝。
        if (!UuidV7.isValid(sample.sampleId)) {
            throw UploadException("该草稿由旧版本创建，无法上传，请重新采集")
        }
        images.forEach {
            if (!UuidV7.isValid(it.imageId)) {
                throw UploadException("图片 ID 由旧版本创建，无法上传，请重新采集")
            }
        }
    }

    private fun ImageEntity.toUploadImage(): UploadImage = UploadImage(
        imageId = imageId,
        viewType = viewType,
        capturedAt = formatCapturedAt(capturedAt, TimeZone.getDefault()),
        deviceTimezone = TimeZone.getDefault().id,
        deviceModel = Build.MODEL,
        mimeType = mimeType,
        width = width,
        height = height,
        fileSize = fileSize,
        sha256 = sha256,
        file = File(filePath)
    )

    private fun friendlyMessage(e: Throwable): String = when (e) {
        is AuthExpiredException -> e.message ?: "登录已过期"
        is HttpException -> ApiErrors.messageOf(e)
        is UploadException -> e.message ?: "上传失败"
        else -> "上传失败，请稍后重试"
    }

    companion object {
        const val MAX_IMAGES = 12
        const val MAX_IMAGE_BYTES = 20L * 1024 * 1024
        const val MAX_TOTAL_BYTES = 120L * 1024 * 1024
    }
}
