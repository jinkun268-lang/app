package com.example.citruscollect.data.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/** 采集对象：一个真实对象对应一行，多张图片关联到 [ImageEntity]。 */
@Entity(tableName = "samples")
data class SampleEntity(
    @PrimaryKey val sampleId: String,
    val schemaVersion: Int = 1,
    val cultivarId: String,
    val part: String,
    val classId: String,
    val symptoms: String = "",
    val note: String = "",
    val taxonomyVersion: Int = 1,
    /** draft / needs_photos / pending / uploading / uploaded / failed。 */
    val uploadState: String = "draft",
    /** 声明成功后服务端返回的 upload_id；重入恢复时复用，避免整包重传。 */
    val uploadId: String? = null,
    /** 最近一次失败的可展示原因。 */
    val uploadError: String? = null,
    /** 所属本地批次；旧版本记录为 null，显示在“历史记录”里。 */
    val batchId: String? = null,
    val ownerKey: String? = null,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val locationAccuracyM: Double? = null,
    val captureQualityWarning: String? = null,
    val reviewJson: String? = null,
    val createdAt: Long = System.currentTimeMillis()
)
