package com.example.citruscollect.data.diagnosis

import android.graphics.BitmapFactory
import androidx.room.withTransaction
import com.example.citruscollect.data.AppDatabase
import com.example.citruscollect.data.AuthRepository
import com.example.citruscollect.data.entity.ImageEntity
import com.example.citruscollect.data.entity.SampleEntity
import com.example.citruscollect.network.*
import com.example.citruscollect.util.UuidV7
import com.example.citruscollect.util.sha256Streaming
import java.io.File
import java.time.LocalDate
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.encodeToString
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import retrofit2.HttpException

/** Recognition archives remain separate from voluntary collection/training contributions. */
class DiagnosisRepository(
    private val dao: DiagnosisDao,
    private val auth: AuthRepository,
    private val filesDir: File,
    private val collectionDb: AppDatabase? = null,
    private val imageSize: (File) -> Pair<Int, Int> = { file ->
        val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, options)
        options.outWidth to options.outHeight
    }
) {
    private val mutex = Mutex()
    private var recovered = false
    private suspend fun ready() {
        if (!recovered) { dao.recoverInterrupted(); dao.recoverArchiveUploads(); recovered = true }
    }
    private suspend fun owner(): String = auth.currentOwnerKey() ?: throw AuthExpiredException("请先登录")
    private suspend fun checkOwner(expected: String) { if (owner() != expected) throw AuthExpiredException("账号已切换，请重新打开记录") }
    private suspend fun owned(id: String): DiagnosisEntity = requireNotNull(dao.get(id)) { "识别记录不存在" }.also { checkOwner(it.ownerKey) }
    fun observeAll(): Flow<List<DiagnosisEntity>> = combine(dao.observeAll(), auth.ownerKey) { rows, key -> rows.filter { key != null && it.ownerKey == key } }
    @OptIn(ExperimentalCoroutinesApi::class)
    fun observe(id: String): Flow<DiagnosisEntity?> = observeAll().map { rows -> rows.find { it.id == id } }.flatMapLatest { row ->
        val sampleId = row?.contributedSampleId
        if (row == null || sampleId == null || collectionDb == null) flowOf(row)
        else collectionDb.sampleDao().observeById(sampleId).map { sample ->
            if (sample?.ownerKey == row.ownerKey) row else row.copy(contributedSampleId = null)
        }
    }
    suspend fun recoverInterrupted() = mutex.withLock { ready() }

    suspend fun createDraft(file: File, mimeType: String, cropId: String = "huyou", part: String = "leaf",
        treeAge: String = "unknown", symptom: String = "", expectedOwnerKey: String? = null): String = withContext(Dispatchers.IO) {
        mutex.withLock {
            ready()
            val key = expectedOwnerKey ?: owner(); checkOwner(key)
            require(cropId in setOf("huyou", "xiangyou", "citrus") && part in setOf("leaf", "fruit", "branch") && treeAge in setOf("adult", "young", "unknown")) { "识别条件无效" }
            require(mimeType in setOf("image/jpeg", "image/png", "image/webp")) { "请选择 JPEG、PNG 或 WebP 图片" }
            require(file.isFile && file.length() in 1..MAX_BYTES) { "图片为空或超过20MiB" }
            require(symptom.length <= 2000) { "现象描述不能超过2000字" }
            val id = UuidV7.generate()
            filesDir.mkdirs()
            val target = File(filesDir, "$id.image")
            var persisted = false
            try {
                file.inputStream().use { input -> target.outputStream().use { output ->
                    val buffer = ByteArray(8192); var total = 0L
                    while (true) { val count = input.read(buffer); if (count < 0) break; total += count
                        require(total <= MAX_BYTES) { "图片超过20MiB" }; output.write(buffer, 0, count) }
                } }
                val (width, height) = imageSize(target)
                require(width > 0 && height > 0 && width.toLong() * height <= 100_000_000L) { "无法读取图片或图片尺寸过大" }
                checkOwner(key)
                // Persist the copied file even if the originating UI is cancelled at this point.
                withContext(NonCancellable) { dao.insert(DiagnosisEntity(id, key, target.absolutePath, mimeType, cropId, part, treeAge, symptom)); persisted = true }
                id
            } catch (e: Throwable) { if (!persisted) target.delete(); throw e }
        }
    }
    suspend fun importImage(file: File, mimeType: String, cropId: String = "huyou", part: String = "leaf", treeAge: String = "unknown", symptom: String = "", expectedOwnerKey: String? = null): String =
        createDraft(file, mimeType, cropId, part, treeAge, symptom, expectedOwnerKey)

    /** Only explicit UI consent calls this method. No network call occurs at import time. */
    suspend fun analyze(id: String) = runRequest(id, false)
    suspend fun retryAdvice(id: String) = runRequest(id, true)
    private suspend fun runRequest(id: String, adviceOnly: Boolean): Unit = withContext(Dispatchers.IO) {
        mutex.withLock {
            ready(); val row = owned(id)
            val previous = row.result()
            var submittedImage = false
            if (adviceOnly) require(previous != null) { "请先完成图片识别" }
            try {
                // Room may commit and then resume with cancellation; include this write in cleanup.
                dao.update(row.copy(status = if (adviceOnly) "advice_loading" else "analyzing", error = null))
                val result = if (adviceOnly) {
                    val advice = auth.authorizedFor(row.ownerKey) { services, token ->
                        requireNotNull(services.diagnosis).advice("Bearer $token", AdviceRequest(previous!!.receipt))
                    }
                    previous!!.copy(advice = advice)
                } else {
                    val file = File(row.imagePath)
                    require(file.isFile && file.length() in 1..MAX_BYTES) { "本地原图缺失或无效" }
                    val hash = sha256Streaming(file)
                    val metadata = DiagnosisInput(row.cropId, row.part, row.treeAge, row.symptom,
                        java.time.Instant.ofEpochMilli(row.createdAt).toString(), row.mimeType, file.length(), hash)
                    val prepared = auth.authorizedFor(row.ownerKey) { services, token ->
                        requireNotNull(services.diagnosis).prepare("Bearer $token", row.id, metadata)
                    }
                    require(prepared.record_id == row.id) { "识别记录编号不一致" }
                    val response = if (prepared.inference_status == "succeeded" || prepared.inference_status == "processing" || (prepared.inference_status == null && prepared.state == "complete")) {
                        val snapshot = fetchSnapshot(row)
                        if (snapshot.result == null) applySnapshot(row, snapshot)
                        requireNotNull(snapshot.result) { "这张图片正在识别，请稍后刷新结果" }
                    } else auth.authorizedFor(row.ownerKey) { services, token ->
                        submittedImage = true
                        requireNotNull(services.diagnosis).diagnose("Bearer $token", row.id, row.cropId, row.part, row.treeAge, file.asRequestBody(row.mimeType.toMediaType()))
                    }
                    require(response.recognition.image_id == row.id && response.recognition.sha256 == hash && response.receipt.isNotBlank()) { "识别结果与图片不一致，请重试" }
                    require(response.recognition.candidates.isNotEmpty() && response.recognition.candidates.all { it.score.isFinite() && it.score in 0.0..1.0 }) { "识别结果无效，请重试" }
                    response
                }
                checkOwner(row.ownerKey)
                val latest = requireNotNull(dao.get(id))
                dao.update(latest.copy(status = "succeeded", error = null, archiveState = if (adviceOnly) latest.archiveState else "uploaded", archiveError = null, resultJson = CitrusJson.json.encodeToString(result)))
            } catch (e: Exception) {
                withContext(NonCancellable) {
                    val latest = dao.get(id)
                    if (latest?.ownerKey == row.ownerKey) dao.update(latest.copy(status = if (adviceOnly) "advice_failed" else "failed", error = when(e) {
                        is CancellationException -> "操作已取消，原图已保留，可重试"
                        is HttpException -> ApiErrors.messageOf(e)
                        is java.io.IOException -> "网络连接失败，原图已保留，请重试"
                        else -> e.message ?: "识别失败，请重试"
                    }))
                }
                if (e is HttpException && submittedImage) runCatching { applySnapshot(row, fetchSnapshot(row)) }
                throw e
            }
        }
    }
    // Compatibility name for the existing report button: only reads server state, never posts model results.
    suspend fun syncArchive(id: String): Unit = withContext(Dispatchers.IO) {
        mutex.withLock {
            ready(); val row = owned(id)
            try { applySnapshot(row, fetchSnapshot(row)) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                checkOwner(row.ownerKey)
                val latest = requireNotNull(dao.get(id))
                dao.update(latest.copy(archiveError = if (e is HttpException) ApiErrors.messageOf(e) else e.message ?: "获取结果失败，请重试"))
            }
        }
    }
    private suspend fun fetchSnapshot(row: DiagnosisEntity): DiagnosisSnapshot = auth.authorizedFor(row.ownerKey) { services, token ->
        requireNotNull(services.diagnosis).snapshot("Bearer $token", row.id)
    }
    private suspend fun applySnapshot(row: DiagnosisEntity, remote: DiagnosisSnapshot) {
        require(remote.record_id == row.id && remote.correction_version >= row.correctionVersion) { "识别记录响应无效" }
        remote.result?.let { require(it.recognition.image_id == row.id) { "识别图片编号不一致" } }
        checkOwner(row.ownerKey)
        val latest = requireNotNull(dao.get(row.id))
        val status = when {
            remote.result != null -> "succeeded"
            remote.inference_status == "failed" -> "failed"
            else -> if (latest.status == "analyzing") "analyzing" else "failed"
        }
        dao.update(latest.copy(archiveState = if (remote.state == "complete") "uploaded" else "pending", archiveError = null,
            status = status, error = if (status == "succeeded") null else remote.inference_error ?: "服务器正在识别，可稍后刷新结果",
            resultJson = remote.result?.let { CitrusJson.json.encodeToString(it) } ?: latest.resultJson,
            correctedName = remote.current_name.takeIf { remote.correction_version > 0 }, correctionVersion = remote.correction_version))
    }
    suspend fun saveFollowUp(id: String, date: String?, observation: String) = mutex.withLock {
        ready(); val row = owned(id)
        date?.takeIf { it.isNotBlank() }?.let { LocalDate.parse(it) }
        require(observation.length <= 4000) { "观察记录不能超过4000字" }
        dao.update(row.copy(followUpDate = date?.takeIf { it.isNotBlank() }, observation = observation))
    }

    /** Explicit contribution creates one independent, unconfirmed draft. Stable reservation survives process death. */
    suspend fun contribute(id: String, batchId: String): String = withContext(Dispatchers.IO) {
        mutex.withLock {
            ready(); var row = owned(id)
            val db = requireNotNull(collectionDb) { "采集库未初始化" }
            row.contributedSampleId?.let { previousId ->
                val previousSample = db.sampleDao().byId(previousId)
                if (previousSample != null) {
                    require(previousSample.ownerKey == row.ownerKey) { "贡献记录账号不一致" }
                    return@withLock previousId
                }
                // A deliberately deleted contribution must not be restored under its old ID.
                row = row.copy(contributedSampleId = null, contributionId = null)
                dao.update(row)
            }
            val sampleId = row.contributionId ?: UuidV7.generate().also { dao.update(row.copy(contributionId = it)) }
            val existing = db.sampleDao().byId(sampleId)
            if (existing != null) {
                require(existing.ownerKey == row.ownerKey) { "贡献记录账号不一致" }
                dao.update(requireNotNull(dao.get(id)).copy(contributedSampleId = sampleId))
                return@withLock sampleId
            }
            val source = File(row.imagePath)
            require(source.isFile) { "本地原图缺失" }
            val target = File(filesDir, "$sampleId.contribution")
            val batch = requireNotNull(db.sampleDao().batchById(batchId)) { "请选择采集批次" }
            require(batch.ownerKey == row.ownerKey && !batch.closed) { "请选择当前账号的开放批次" }
            source.copyTo(target, overwrite = true)
            val (width, height) = imageSize(target)
            require(width > 0 && height > 0) { "原图无效" }
            checkOwner(row.ownerKey)
            withContext(NonCancellable) {
                db.withTransaction {
                    val currentBatch = requireNotNull(db.sampleDao().batchById(batchId))
                    require(currentBatch.ownerKey == row.ownerKey && !currentBatch.closed) { "批次已关闭或账号不一致" }
                    val imageId = UuidV7.generate()
                    db.imageDao().addCapturedImage(ImageEntity(imageId, sampleId, "close_up", target.absolutePath,
                        row.mimeType, width, height, target.length(), sha256Streaming(target), recognitionJson = row.result()?.recognition?.let { CitrusJson.json.encodeToString(it.copy(image_id = imageId, accepted = false, accepted_index = null)) }),
                        SampleEntity(sampleId = sampleId, ownerKey = row.ownerKey, cultivarId = "unknown", part = row.part,
                            classId = "unknown", symptoms = row.symptom.take(500), batchId = batchId,
                            note = "来自拍照识别；模型初判尚未核验，请确认采集信息后再上传。"))
                }
                dao.update(requireNotNull(dao.get(id)).copy(contributedSampleId = sampleId))
            }
            sampleId
        }
    }
    companion object { const val MAX_BYTES = 20L * 1024 * 1024 }
}
