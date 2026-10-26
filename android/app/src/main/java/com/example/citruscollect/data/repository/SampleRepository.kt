package com.example.citruscollect.data.repository

import android.os.Build
import com.example.citruscollect.data.AuthRepository
import com.example.citruscollect.data.dao.ImageDao
import com.example.citruscollect.data.dao.SampleDao
import com.example.citruscollect.data.entity.BatchEntity
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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import retrofit2.HttpException
import java.io.File
import java.io.IOException
import java.util.TimeZone
import com.example.citruscollect.network.RecognitionResult
import com.example.citruscollect.network.CitrusJson
import kotlinx.serialization.encodeToString
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.MediaType.Companion.toMediaType

/** 采集数据的本地仓库，负责 Room 读写与上传编排。 */
class SampleRepository(
    private val sampleDao: SampleDao,
    private val imageDao: ImageDao,
    private val backend: Backend,
    private val authRepository: AuthRepository
) {
    private val uploadMutex = Mutex()

    fun observePending(): Flow<List<SampleEntity>> = sampleDao.observePending()
    fun observeUploaded(): Flow<List<SampleEntity>> = sampleDao.observeUploaded()
    fun observePendingCount(): Flow<Int> = sampleDao.observePendingCount()
    fun imagesOf(sampleId: String): Flow<List<ImageEntity>> = imageDao.bySample(sampleId)
    fun sampleById(sampleId: String): Flow<SampleEntity?> = sampleDao.observeById(sampleId)

    suspend fun recognizeImage(imageId: String): RecognitionResult {
        val image = uploadMutex.withLock {
            val current = imageDao.byId(imageId) ?: throw UploadException("照片不存在")
            requireEditable(current.sampleId)
            current
        }
        withContext(Dispatchers.IO) {
            if (sha256Streaming(File(image.filePath)) != image.sha256) throw UploadException("照片已变更，请重新打开后识别")
        }
        suspend fun request() = authRepository.authorizedServices { services, token ->
            services.recognition.recognize("Bearer $token", imageId, File(image.filePath).asRequestBody(image.mimeType.toMediaType()))
        }
        val result = try { request() } catch (_: IOException) { request() }
        if (result.image_id != imageId || result.sha256 != image.sha256 || result.candidates.isEmpty() ||
            result.candidates.size > 5 || result.candidates.any { !it.score.isFinite() || it.score !in 0.0..1.0 }) {
            throw UploadException("识别结果与照片不一致，请重试")
        }
        uploadMutex.withLock {
            val latest = imageDao.byId(imageId) ?: throw UploadException("照片已删除")
            requireEditable(latest.sampleId)
            if (latest.sha256 != image.sha256) throw UploadException("照片已重拍，请重新识别")
            imageDao.update(latest.copy(recognitionJson = CitrusJson.json.encodeToString(result)))
        }
        return result
    }

    /** A suggestion for one photo must never silently relabel other photos in a legacy multi-photo record. */
    suspend fun adoptRecognition(imageId: String, candidateIndex: Int): String = uploadMutex.withLock {
        val image = imageDao.byId(imageId) ?: throw UploadException("照片不存在")
        requireEditable(image.sampleId)
        val result = image.recognitionJson?.let { CitrusJson.json.decodeFromString<RecognitionResult>(it) }
            ?: throw UploadException("请先识别这张照片")
        if (result.sha256 != image.sha256) throw UploadException("旧识别结果已失效，请重新识别")
        val candidate = result.candidates.getOrNull(candidateIndex) ?: throw UploadException("请选择候选类别")
        val source = sampleDao.byId(image.sampleId) ?: throw UploadException("记录不存在")
        val split = imageDao.bySampleList(source.sampleId).size > 1
        val targetId = if (split) UuidV7.generate() else source.sampleId
        val targetImageId = if (split) UuidV7.generate() else image.imageId
        val suggestion = "模型建议：${candidate.name}（分数${"%.3f".format(java.util.Locale.ROOT, candidate.score)}；${result.model}/${result.model_version}，需专业核验）"
        val combinedNote = listOf(source.note, suggestion).filter { it.isNotBlank() }.joinToString("\n")
        val note = if (combinedNote.length <= 500) combinedNote else source.note
        val updated = source.copy(sampleId = targetId, part = if (result.scope == "leaf") "leaf" else source.part,
            classId = candidate.class_id ?: "unknown", note = note,
            // 单图记录本来就只描述这一张图，采用结果不需要再改变上传状态。
            uploadState = if (split) "pending" else source.uploadState, uploadError = null)
        withContext(Dispatchers.IO + NonCancellable) {
            imageDao.adoptRecognition(image, image.copy(imageId = targetImageId, sampleId = targetId,
                recognitionJson = CitrusJson.json.encodeToString(result.copy(image_id = targetImageId, accepted = true, accepted_index = candidateIndex))), updated)
        }
        targetId
    }

    suspend fun saveDraftMetadata(sampleId: String, cultivar: String, part: String, classId: String, symptoms: String, note: String) = uploadMutex.withLock {
        requireEditable(sampleId)
        val source = sampleDao.byId(sampleId) ?: throw UploadException("记录不存在")
        sampleDao.update(source.copy(cultivarId = cultivar, part = part, classId = classId, symptoms = symptoms, note = note))
    }

    /** Server withdrawal is idempotent. Retain local originals and give the editable copy fresh declaration IDs. */
    suspend fun withdraw(sampleId: String): String = uploadMutex.withLock {
        val sample = sampleDao.byId(sampleId) ?: throw UploadException("记录不存在")
        if (sample.uploadState != "uploaded") throw UploadException("只有已上传记录可以撤回")
        val images = imageDao.bySampleList(sampleId)
        images.forEach { if (!File(it.filePath).isFile) throw UploadException("本地照片缺失，无法保留可编辑副本") }
        suspend fun withdrawOnce() = authRepository.authorizedServices { services, token -> services.upload.withdraw("Bearer $token", sampleId) }
        // This specific command is idempotent, so a lost response or stale connection may be retried once.
        val response = try { withdrawOnce() } catch (_: IOException) { withdrawOnce() }
        if (response.sample_id != sampleId || response.state != "withdrawn") throw UploadException("撤回回执与记录不一致")
        val newId = UuidV7.generate()
        withContext(Dispatchers.IO + NonCancellable) {
            imageDao.restoreWithdrawn(sampleId, sample.copy(sampleId = newId, uploadState = "pending", uploadId = null, uploadError = null),
                images.map { it.copy(imageId = UuidV7.generate(), sampleId = newId) })
        }
        newId
    }

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

    /**
     * 一张照片一条记录：每次拍照都新建独立记录并立即落 Room，
     * 之后的编辑、上传、撤回都只作用于这一张图片。
     */
    suspend fun capturePhoto(
        file: File,
        mimeType: String,
        width: Int,
        height: Int,
        viewType: String = "close_up",
        capturedAt: Long = System.currentTimeMillis(),
        batchId: String? = null,
        cultivarId: String = "unknown"
    ): String = uploadMutex.withLock {
        if (!file.isFile || file.length() == 0L || width <= 0 || height <= 0) throw UploadException("照片保存失败，不会创建空记录")
        val sampleId = UuidV7.generate()
        val image = withContext(Dispatchers.IO) {
            ImageEntity(
                imageId = UuidV7.generate(),
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
        }
        val sample = SampleEntity(
            sampleId = sampleId,
            cultivarId = cultivarId,
            part = "leaf",
            classId = "unknown",
            batchId = batchId,
            createdAt = capturedAt
        )
        withContext(Dispatchers.IO + NonCancellable) { imageDao.addCapturedImage(image, sample) }
        sampleId
    }

    // ---- 本地采集批次 ----

    fun observeBatches(): Flow<List<BatchEntity>> = sampleDao.observeBatches()

    suspend fun latestBatch(): BatchEntity? = sampleDao.latestBatch()

    fun batchCount(batchId: String): Flow<Int> = sampleDao.observeBatchCount(batchId)

    /** 新建本地批次并返回它的 id；批次只承载共同信息，不上传。 */
    suspend fun createBatch(
        name: String,
        place: String,
        collector: String,
        defaultCultivarId: String
    ): String = uploadMutex.withLock {
        val id = UuidV7.generate()
        sampleDao.insertBatch(
            BatchEntity(
                batchId = id,
                name = name.ifBlank { "未命名采集" },
                place = place.trim(),
                collector = collector.trim(),
                defaultCultivarId = defaultCultivarId
            )
        )
        id
    }

    /** 放弃一条还没开始上传的记录，本地原图一并删除；已声明或已上传的记录只能撤回。 */
    suspend fun discardRecord(sampleId: String): Boolean = uploadMutex.withLock {
        val sample = sampleDao.byId(sampleId) ?: return@withLock false
        if (sample.uploadId != null || sample.uploadState == "uploaded") {
            throw UploadException("已开始上传的记录不能放弃，请在已上传记录里撤回")
        }
        val images = imageDao.bySampleList(sampleId)
        withContext(Dispatchers.IO + NonCancellable) {
            images.forEach { File(it.filePath).delete() }
            imageDao.deleteSample(sampleId)
        }
        true
    }

    /** 拍摄后立即落 Room：返回生成的 imageId，供取消重复导入参考。 */
    suspend fun addImage(
        sampleId: String,
        viewType: String,
        file: File,
        mimeType: String,
        width: Int,
        height: Int,
        capturedAt: Long = System.currentTimeMillis(),
        createIfMissing: Boolean = false
    ): String = uploadMutex.withLock {
        if (!file.isFile || file.length() == 0L || width <= 0 || height <= 0) throw UploadException("照片保存失败，不会创建空记录")
        val newSample = if (createIfMissing && sampleDao.byId(sampleId) == null) {
            SampleEntity(sampleId = sampleId, cultivarId = "unknown", part = "leaf", classId = "unknown")
        } else { requireEditable(sampleId); null }
        if (imageDao.bySampleList(sampleId).size >= MAX_IMAGES) throw UploadException("每份对象最多 12 张图，请先删除或重拍")
        val id = UuidV7.generate()
        withContext(Dispatchers.IO + NonCancellable) { imageDao.addCapturedImage(
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
            ), newSample
        ) }
        id
    }

    private suspend fun requireEditable(sampleId: String) {
        val sample = sampleDao.byId(sampleId) ?: throw UploadException("对象不存在")
        if (sample.uploadId != null || sample.uploadState !in setOf("draft", "pending", "failed", "needs_photos")) {
            throw UploadException("已开始上传的照片不能修改，请新建采集记录")
        }
    }

    suspend fun cleanupAbandonedEmptyDrafts(): Int = uploadMutex.withLock { sampleDao.deleteAbandonedEmptyDrafts() }

    suspend fun deleteImage(imageId: String, deleteRecordIfLast: Boolean = false): Boolean = uploadMutex.withLock {
        val image = imageDao.byId(imageId) ?: throw UploadException("照片不存在")
        requireEditable(image.sampleId)
        withContext(Dispatchers.IO + NonCancellable) {
            val deletedRecord = imageDao.removePhoto(image, deleteRecordIfLast)
            File(image.filePath).delete()
            deletedRecord
        }
    }

    /** 新文件完整写入并校验后才替换记录；保留原照片的 ID 与视角。 */
    suspend fun replaceImage(sampleId: String, imageId: String, file: File, width: Int, height: Int) = uploadMutex.withLock {
        requireEditable(sampleId)
        val old = imageDao.byId(imageId)?.takeIf { it.sampleId == sampleId }
            ?: throw UploadException("待重拍照片不存在")
        withContext(Dispatchers.IO + NonCancellable) {
            require(file.isFile && file.length() > 0 && width > 0 && height > 0) { "新照片保存失败，原照片已保留" }
            require(file.absolutePath != old.filePath) { "重拍必须使用新文件" }
            val replacement = old.copy(filePath = file.absolutePath, width = width, height = height,
                mimeType = "image/jpeg", fileSize = file.length(), sha256 = sha256Streaming(file),
                capturedAt = System.currentTimeMillis(), recognitionJson = null)
            imageDao.update(replacement)
            File(old.filePath).delete()
        }
    }

    suspend fun setUploadState(sampleId: String, state: String) {
        sampleDao.byId(sampleId)?.let { sampleDao.update(it.copy(uploadState = state)) }
    }

    suspend fun updateViewType(imageId: String, viewType: String) = uploadMutex.withLock {
        val image = imageDao.byId(imageId) ?: throw UploadException("照片不存在")
        requireEditable(image.sampleId)
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
    ) = uploadMutex.withLock {
        requireEditable(sampleId)
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
        if (sample.uploadState in setOf("draft", "needs_photos")) {
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
            android.util.Log.w("CitrusUpload", "Upload failed (${e.javaClass.simpleName})", e)
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
        is java.net.SocketTimeoutException -> "上传连接超时，自动重试后仍失败，请点击上传继续补传"
        is IOException -> "网络连接中断，自动重试后仍失败，请点击上传继续补传"
        else -> "上传失败，请稍后重试"
    }

    companion object {
        const val MAX_IMAGES = 12
        const val MAX_IMAGE_BYTES = 20L * 1024 * 1024
        const val MAX_TOTAL_BYTES = 120L * 1024 * 1024
    }
}
