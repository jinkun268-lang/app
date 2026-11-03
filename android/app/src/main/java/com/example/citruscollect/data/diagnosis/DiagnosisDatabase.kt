package com.example.citruscollect.data.diagnosis

import android.content.Context
import androidx.room.*
import com.example.citruscollect.network.CitrusJson
import com.example.citruscollect.network.DiagnosisResult
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "diagnoses", indices = [Index("ownerKey")])
data class DiagnosisEntity(
    @PrimaryKey val id: String, val ownerKey: String, val imagePath: String, val mimeType: String,
    val cropId: String = "huyou", val part: String = "leaf", val treeAge: String = "unknown", val symptom: String = "",
    val status: String = "draft", val error: String? = null, val resultJson: String? = null,
    val createdAt: Long = System.currentTimeMillis(), val followUpDate: String? = null, val observation: String = "",
    val contributedSampleId: String? = null, val contributionId: String? = null,
    @ColumnInfo(defaultValue = "'pending'") val archiveState: String = "pending", val archiveError: String? = null,
    val correctedName: String? = null, @ColumnInfo(defaultValue = "0") val correctionVersion: Int = 0
)
fun DiagnosisEntity.result(): DiagnosisResult? = resultJson?.let { runCatching { CitrusJson.json.decodeFromString<DiagnosisResult>(it) }.getOrNull() }

@Dao interface DiagnosisDao {
    @Query("SELECT * FROM diagnoses ORDER BY createdAt DESC") fun observeAll(): Flow<List<DiagnosisEntity>>
    @Query("SELECT * FROM diagnoses WHERE id = :id") suspend fun get(id: String): DiagnosisEntity?
    @Insert suspend fun insert(row: DiagnosisEntity)
    @Update suspend fun update(row: DiagnosisEntity)
    @Query("UPDATE diagnoses SET status = CASE WHEN resultJson IS NULL THEN 'failed' ELSE 'advice_failed' END, error = '上次操作已中断，请重试' WHERE status IN ('analyzing','advice_loading')")
    suspend fun recoverInterrupted()
    @Query("UPDATE diagnoses SET archiveState = 'pending', archiveError = '上次上传已中断，可重试' WHERE archiveState = 'uploading'")
    suspend fun recoverArchiveUploads()
}
@Database(entities = [DiagnosisEntity::class], version = 2, exportSchema = false)
abstract class DiagnosisDatabase : RoomDatabase() {
    abstract fun diagnosisDao(): DiagnosisDao
    companion object {
        @Volatile private var instance: DiagnosisDatabase? = null
        fun get(context: Context): DiagnosisDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(context.applicationContext, DiagnosisDatabase::class.java, "citrus-diagnoses.db")
                .addMigrations(MIGRATION_1_2).build().also { instance = it }
        }
        val MIGRATION_1_2 = object : androidx.room.migration.Migration(1, 2) {
            override fun migrate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE diagnoses ADD COLUMN archiveState TEXT NOT NULL DEFAULT 'pending'")
                db.execSQL("ALTER TABLE diagnoses ADD COLUMN archiveError TEXT")
                db.execSQL("ALTER TABLE diagnoses ADD COLUMN correctedName TEXT")
                db.execSQL("ALTER TABLE diagnoses ADD COLUMN correctionVersion INTEGER NOT NULL DEFAULT 0")
            }
        }
    }
}
