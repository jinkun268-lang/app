package com.example.citruscollect.data.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import com.example.citruscollect.data.entity.SampleEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface SampleDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(sample: SampleEntity)

    @Update
    suspend fun update(sample: SampleEntity)

    @Query("SELECT * FROM samples WHERE sampleId = :sampleId")
    suspend fun byId(sampleId: String): SampleEntity?

    @Query("SELECT * FROM samples WHERE sampleId = :sampleId")
    fun observeById(sampleId: String): Flow<SampleEntity?>

    /** 未上传完成的草稿与待上传对象。 */
    @Query("SELECT * FROM samples WHERE uploadState IN ('draft','pending','uploading','failed') ORDER BY createdAt DESC")
    fun observePending(): Flow<List<SampleEntity>>

    @Query("SELECT COUNT(*) FROM samples WHERE uploadState IN ('draft','pending','failed')")
    fun observePendingCount(): Flow<Int>

    @Query("UPDATE samples SET uploadId = :uploadId WHERE sampleId = :sampleId")
    suspend fun setUploadId(sampleId: String, uploadId: String)

    @Query("UPDATE samples SET uploadError = :error WHERE sampleId = :sampleId")
    suspend fun setUploadError(sampleId: String, error: String?)
}
