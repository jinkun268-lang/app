package com.example.citruscollect.data.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import com.example.citruscollect.data.entity.BatchEntity
import com.example.citruscollect.data.entity.SampleEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface SampleDao {
    @Query("SELECT * FROM samples WHERE uploadState = 'uploaded' ORDER BY createdAt DESC")
    fun observeUploaded(): Flow<List<SampleEntity>>

    @Query("DELETE FROM samples WHERE sampleId = :sampleId")
    suspend fun deleteById(sampleId: String)
    @Query("DELETE FROM samples WHERE uploadState = 'draft' AND uploadId IS NULL AND cultivarId = 'unknown' AND classId = 'unknown' AND part = 'leaf' AND symptoms = '' AND note = '' AND NOT EXISTS (SELECT 1 FROM images WHERE images.sampleId = samples.sampleId)")
    suspend fun deleteAbandonedEmptyDrafts(): Int
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(sample: SampleEntity)

    @Update
    suspend fun update(sample: SampleEntity)

    @Query("SELECT * FROM samples WHERE sampleId = :sampleId")
    suspend fun byId(sampleId: String): SampleEntity?

    @Query("SELECT * FROM samples WHERE sampleId = :sampleId")
    fun observeById(sampleId: String): Flow<SampleEntity?>

    /** 未上传完成的草稿与待上传对象。 */
    @Query("SELECT * FROM samples WHERE uploadState IN ('draft','pending','uploading','failed','needs_photos') ORDER BY createdAt DESC")
    fun observePending(): Flow<List<SampleEntity>>

    @Query("SELECT COUNT(*) FROM samples WHERE uploadState IN ('draft','pending','failed','needs_photos')")
    fun observePendingCount(): Flow<Int>

    @Query("UPDATE samples SET uploadId = :uploadId WHERE sampleId = :sampleId")
    suspend fun setUploadId(sampleId: String, uploadId: String)

    @Query("UPDATE samples SET uploadError = :error WHERE sampleId = :sampleId")
    suspend fun setUploadError(sampleId: String, error: String?)

    // ---- 本地采集批次：只负责共同信息，不改变“一张图片一条记录” ----

    @Query("SELECT * FROM batches ORDER BY createdAt DESC")
    fun observeBatches(): Flow<List<BatchEntity>>

    @Query("SELECT * FROM batches WHERE batchId = :batchId")
    suspend fun batchById(batchId: String): BatchEntity?

    @Query("SELECT * FROM batches ORDER BY createdAt DESC LIMIT 1")
    suspend fun latestBatch(): BatchEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertBatch(batch: BatchEntity)

    @Update
    suspend fun updateBatch(batch: BatchEntity)

    @Query("SELECT COUNT(*) FROM samples WHERE batchId = :batchId")
    fun observeBatchCount(batchId: String): Flow<Int>
}
