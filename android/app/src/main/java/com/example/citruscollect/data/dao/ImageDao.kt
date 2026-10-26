package com.example.citruscollect.data.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import androidx.room.Transaction
import com.example.citruscollect.data.entity.ImageEntity
import com.example.citruscollect.data.entity.SampleEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface ImageDao {
    @Update
    suspend fun updateSample(sample: SampleEntity)

    @Transaction
    suspend fun adoptRecognition(source: ImageEntity, target: ImageEntity, sample: SampleEntity) {
        if (source.sampleId == target.sampleId) {
            updateSample(sample)
            update(target)
        } else {
            insertSample(sample)
            insert(target)
            deleteById(source.imageId)
        }
    }

    @Query("DELETE FROM samples WHERE sampleId = :sampleId")
    suspend fun deleteSample(sampleId: String)

    @Transaction
    suspend fun restoreWithdrawn(oldSampleId: String, replacement: SampleEntity, images: List<ImageEntity>) {
        insertSample(replacement)
        images.forEach { insert(it) }
        deleteSample(oldSampleId)
    }
    @Insert
    suspend fun insertSample(sample: SampleEntity)

    @Query("UPDATE samples SET uploadState = 'draft' WHERE sampleId = :sampleId AND uploadState = 'needs_photos'")
    suspend fun markPhotographed(sampleId: String)

    @Transaction
    suspend fun addCapturedImage(image: ImageEntity, newSample: SampleEntity?) {
        if (newSample != null) insertSample(newSample)
        insert(image)
        markPhotographed(image.sampleId)
    }

    @Query("DELETE FROM samples WHERE sampleId = :sampleId AND uploadId IS NULL AND NOT EXISTS (SELECT 1 FROM images WHERE images.sampleId = :sampleId)")
    suspend fun deleteEmptySample(sampleId: String): Int

    @Query("UPDATE samples SET uploadState = 'needs_photos' WHERE sampleId = :sampleId AND NOT EXISTS (SELECT 1 FROM images WHERE images.sampleId = :sampleId)")
    suspend fun markNeedsPhotos(sampleId: String)

    @Transaction
    suspend fun removePhoto(image: ImageEntity, deleteRecordIfLast: Boolean): Boolean {
        deleteById(image.imageId)
        if (deleteRecordIfLast && deleteEmptySample(image.sampleId) > 0) return true
        markNeedsPhotos(image.sampleId)
        return false
    }

    @Query("SELECT * FROM images WHERE imageId = :imageId")
    suspend fun byId(imageId: String): ImageEntity?

    @Update
    suspend fun update(image: ImageEntity)

    @Query("DELETE FROM images WHERE imageId = :imageId")
    suspend fun deleteById(imageId: String)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(image: ImageEntity)

    @Query("SELECT * FROM images WHERE sampleId = :sampleId ORDER BY capturedAt ASC")
    fun bySample(sampleId: String): Flow<List<ImageEntity>>

    @Query("SELECT * FROM images WHERE sampleId = :sampleId ORDER BY capturedAt ASC")
    suspend fun bySampleList(sampleId: String): List<ImageEntity>

    @Query("UPDATE images SET viewType = :viewType WHERE imageId = :imageId")
    suspend fun updateViewType(imageId: String, viewType: String)
}
