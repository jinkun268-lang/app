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
    /** draft / pending / uploading / uploaded / failed，见采集端本地状态机。 */
    val uploadState: String = "draft",
    /** 声明成功后服务端返回的 upload_id；重入恢复时复用，避免整包重传。 */
    val uploadId: String? = null,
    /** 最近一次失败的可展示原因。 */
    val uploadError: String? = null,
    val createdAt: Long = System.currentTimeMillis()
)
