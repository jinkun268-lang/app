package com.example.citruscollect

import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.graphics.BitmapFactory
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.example.citruscollect.data.AppDatabase
import com.example.citruscollect.network.CitrusJson
import com.example.citruscollect.network.RecognitionResult
import com.example.citruscollect.util.UuidV7
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class SingleRecognitionTest {
    @Test fun migrationPreservesOldPhotosAndNotes(): Unit = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val name = "recognition-migration-${System.nanoTime()}.db"
        val path = context.getDatabasePath(name).apply { parentFile!!.mkdirs() }
        val sample = UuidV7.generate(); val image = UuidV7.generate()
        SQLiteDatabase.openOrCreateDatabase(path, null).use { db ->
            db.execSQL("CREATE TABLE samples (sampleId TEXT NOT NULL PRIMARY KEY, schemaVersion INTEGER NOT NULL, cultivarId TEXT NOT NULL, part TEXT NOT NULL, classId TEXT NOT NULL, symptoms TEXT NOT NULL, note TEXT NOT NULL, taxonomyVersion INTEGER NOT NULL, uploadState TEXT NOT NULL, uploadId TEXT, uploadError TEXT, createdAt INTEGER NOT NULL)")
            db.execSQL("CREATE TABLE images (imageId TEXT NOT NULL PRIMARY KEY, sampleId TEXT NOT NULL, viewType TEXT NOT NULL, filePath TEXT NOT NULL, mimeType TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, fileSize INTEGER NOT NULL, sha256 TEXT NOT NULL, capturedAt INTEGER NOT NULL, FOREIGN KEY(sampleId) REFERENCES samples(sampleId) ON UPDATE NO ACTION ON DELETE CASCADE)")
            db.execSQL("CREATE INDEX index_images_sampleId ON images(sampleId)")
            db.execSQL("INSERT INTO samples VALUES (?,1,'unknown','leaf','unknown','kept symptoms','kept note',1,'pending',NULL,NULL,123)", arrayOf(sample))
            db.execSQL("INSERT INTO images VALUES (?,?,'context','kept.jpg','image/jpeg',32,32,99,'kept hash',123)", arrayOf(image, sample))
            db.version = 2
        }
        val upgraded = Room.databaseBuilder(context, AppDatabase::class.java, name)
            .addMigrations(AppDatabase.MIGRATION_2_3, AppDatabase.MIGRATION_3_4, AppDatabase.MIGRATION_4_5).build()
        try {
            assertEquals("kept note", upgraded.sampleDao().byId(sample)?.note)
            assertNull(upgraded.sampleDao().byId(sample)?.ownerKey)
            assertEquals(1, upgraded.sampleDao().observeLegacyCount().first())
            val restored = upgraded.imageDao().byId(image)!!
            assertEquals("kept.jpg", restored.filePath)
            assertEquals("context", restored.viewType)
            assertNull(restored.recognitionJson)
        } finally { upgraded.close(); context.deleteDatabase(name) }
    }

    @Test fun realSingleRecognitionAndAdoptionDoesNotRelabelSiblingPhoto(): Unit = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val args = InstrumentationRegistry.getArguments()
        val app = context.applicationContext as CitrusApplication
        app.container.authRepository.login(requireNotNull(args.getString("baseUrl")),
            requireNotNull(args.getString("collectorUsername")), requireNotNull(args.getString("collectorPassword")))
        app.container.authRepository.bootstrap(forceRefresh = true)
        val repository = app.container.repository
        val folder = File(context.cacheDir, "recognition-ui-${System.nanoTime()}").apply { mkdirs() }
        val source = File(requireNotNull(args.getString("imagePath")))
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(source.absolutePath, bounds)
        val ids = mutableSetOf<String>()
        val sample = repository.createSample("unknown", "leaf", "unknown", note = "recognition fixture notes").also { ids.add(it) }
        val device = UiDevice.getInstance(instrumentation)
        fun click(text: String) {
            var node = requireNotNull(device.wait(Until.findObject(By.text(text)), 20000)) { "Missing UI: $text" }
            while (!node.isClickable && node.parent != null) node = node.parent
            node.click()
        }
        try {
            repeat(2) { index ->
                val image = File(folder, "$index.png"); source.copyTo(image)
                repository.addImage(sample, if (index == 0) "context" else "close_up", image, "image/png", bounds.outWidth, bounds.outHeight)
            }
            repository.saveConfirm(sample, "unknown", "leaf", "unknown", "", "recognition fixture notes")
            val original = repository.imagesOf(sample).first()
            context.startActivity(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
            click("上传记录")
            assertNotNull(device.wait(Until.findObject(By.text("记录 ${sample.takeLast(8)} · 待上传")), 10000))
            click("识别此图")
            click("开始识别")
            assertNotNull(device.wait(Until.findObject(By.text("健康（模型标签）")), 45000))
            val stored = repository.imagesOf(sample).first().first()
            val result = CitrusJson.json.decodeFromString<RecognitionResult>(stored.recognitionJson!!)
            assertEquals(stored.sha256, result.sha256)
            assertEquals("healthy", result.candidates.first().label)
            assertFalse(result.accepted)
            assertEquals("unknown", repository.sampleById(sample).first()?.classId)
            click("采用结果")
            assertNotNull(device.wait(Until.findObject(By.text("编辑图片")), 10000))
            val adopted = repository.observePending().first().single { it.note.startsWith("recognition fixture notes\n模型建议：") }
            ids.add(adopted.sampleId)
            assertNotEquals(sample, adopted.sampleId)
            assertEquals("unknown", adopted.classId)
            val single = repository.imagesOf(adopted.sampleId).first().single()
            val accepted = CitrusJson.json.decodeFromString<RecognitionResult>(single.recognitionJson!!)
            assertTrue(accepted.accepted)
            assertEquals("context", single.viewType)
            assertEquals(original[0].filePath, single.filePath)
            assertEquals(1, repository.imagesOf(sample).first().size)
            assertEquals(original[1].imageId, repository.imagesOf(sample).first().single().imageId)
            assertEquals("unknown", repository.sampleById(sample).first()?.classId)
            assertEquals("recognition fixture notes", repository.sampleById(sample).first()?.note)
            val newFile = File(folder, "retaken.png"); source.copyTo(newFile)
            repository.replaceImage(adopted.sampleId, single.imageId, newFile, bounds.outWidth, bounds.outHeight)
            assertNull(repository.imagesOf(adopted.sampleId).first().single().recognitionJson)
        } finally {
            withContext(Dispatchers.IO) { ids.forEach { AppDatabase.get(context).sampleDao().deleteById(it) }; folder.deleteRecursively() }
        }
    }
}
