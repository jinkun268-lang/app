package com.example.citruscollect.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.example.citruscollect.data.dao.ImageDao
import com.example.citruscollect.data.dao.SampleDao
import com.example.citruscollect.data.entity.BatchEntity
import com.example.citruscollect.data.entity.ImageEntity
import com.example.citruscollect.data.entity.SampleEntity

@Database(
    entities = [SampleEntity::class, ImageEntity::class, BatchEntity::class],
    version = 5,
    exportSchema = false
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun sampleDao(): SampleDao
    abstract fun imageDao(): ImageDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null
        val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE images ADD COLUMN recognitionJson TEXT")
            }
        }

        val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS `batches` (`batchId` TEXT NOT NULL, `name` TEXT NOT NULL, " +
                        "`place` TEXT NOT NULL, `collector` TEXT NOT NULL, `defaultCultivarId` TEXT NOT NULL, " +
                        "`note` TEXT NOT NULL, `closed` INTEGER NOT NULL, `createdAt` INTEGER NOT NULL, " +
                        "PRIMARY KEY(`batchId`))"
                )
                db.execSQL("ALTER TABLE samples ADD COLUMN batchId TEXT")
            }
        }

        val MIGRATION_4_5 = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE samples ADD COLUMN ownerKey TEXT")
                db.execSQL("ALTER TABLE batches ADD COLUMN ownerKey TEXT")
                db.execSQL("ALTER TABLE batches ADD COLUMN syncPending INTEGER NOT NULL DEFAULT 1")
                listOf("latitude", "longitude", "locationAccuracyM").forEach { db.execSQL("ALTER TABLE samples ADD COLUMN $it REAL") }
                listOf("captureQualityWarning", "reviewJson").forEach { db.execSQL("ALTER TABLE samples ADD COLUMN $it TEXT") }
            }
        }

        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE samples ADD COLUMN uploadId TEXT")
                db.execSQL("ALTER TABLE samples ADD COLUMN uploadError TEXT")
            }
        }

        fun get(context: Context): AppDatabase =
            INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "citrus-collect.db"
                ).addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5).build().also { INSTANCE = it }
            }
    }
}
