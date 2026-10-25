package com.example.citruscollect.data.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.example.citruscollect.data.entity.ImageEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface ImageDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(image: ImageEntity)

    @Query("SELECT * FROM images WHERE sampleId = :sampleId ORDER BY capturedAt ASC")
    fun bySample(sampleId: String): Flow<List<ImageEntity>>

    @Query("SELECT * FROM images WHERE sampleId = :sampleId ORDER BY capturedAt ASC")
    suspend fun bySampleList(sampleId: String): List<ImageEntity>

    @Query("UPDATE images SET viewType = :viewType WHERE imageId = :imageId")
    suspend fun updateViewType(imageId: String, viewType: String)
}
