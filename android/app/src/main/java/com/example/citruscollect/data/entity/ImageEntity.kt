package com.example.citruscollect.data.entity

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/** 对象的一张原图；文件落在应用私有目录，这里只存路径与属性。 */
@Entity(
    tableName = "images",
    foreignKeys = [ForeignKey(
        entity = SampleEntity::class,
        parentColumns = ["sampleId"],
        childColumns = ["sampleId"],
        onDelete = ForeignKey.CASCADE
    )],
    indices = [Index("sampleId")]
)
data class ImageEntity(
    @PrimaryKey val imageId: String,
    val sampleId: String,
    /** close_up / context / other */
    val viewType: String,
    val filePath: String,
    val mimeType: String,
    val width: Int,
    val height: Int,
    val fileSize: Long,
    val sha256: String = "",
    val capturedAt: Long = System.currentTimeMillis(),
    val recognitionJson: String? = null
)
