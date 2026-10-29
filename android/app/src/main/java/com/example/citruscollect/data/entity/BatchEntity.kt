package com.example.citruscollect.data.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * 采集批次：承载一次外业采集的共同信息（地点、日期、采集人、默认品种）。
 * 只存在于采集端本地，不上传，也不把图片合并成一条记录。
 */
@Entity(tableName = "batches")
data class BatchEntity(
    @PrimaryKey val batchId: String,
    val name: String,
    val place: String = "",
    val collector: String = "",
    val defaultCultivarId: String = "unknown",
    val note: String = "",
    val closed: Boolean = false,
    val ownerKey: String? = null,
    @androidx.room.ColumnInfo(defaultValue = "1") val syncPending: Boolean = true,
    val createdAt: Long = System.currentTimeMillis()
)
