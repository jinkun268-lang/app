package com.example.citruscollect

import android.graphics.Bitmap
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.example.citruscollect.data.AppDatabase
import com.example.citruscollect.data.repository.SampleRepository
import com.example.citruscollect.network.Backend
import com.example.citruscollect.util.sha256Streaming
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class PhotoManagementTest {
    private lateinit var db: AppDatabase
    private lateinit var repository: SampleRepository
    private lateinit var folder: File
    @Before fun setup() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        repository = SampleRepository(db.sampleDao(), db.imageDao(), Backend(),
            (context.applicationContext as CitrusApplication).container.authRepository)
        folder = File(context.cacheDir, "photo-test-${System.nanoTime()}").apply { mkdirs() }
    }
    @After fun cleanup() { db.close(); folder.deleteRecursively() }

    private fun photo(name: String, color: Int): File = File(folder, name).also { file ->
        val bitmap = Bitmap.createBitmap(24, 32, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(color)
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) }
        bitmap.recycle()
    }

    @Test fun retakeReplacesOnlyTargetAndDeletesOldFile(): Unit = runBlocking {
        val sample = repository.createSample("unknown", "leaf", "unknown")
        val old = photo("old.jpg", android.graphics.Color.RED)
        val untouched = photo("other.jpg", android.graphics.Color.BLUE)
        val id = repository.addImage(sample, "context", old, "image/jpeg", 24, 32)
        repository.addImage(sample, "close_up", untouched, "image/jpeg", 24, 32)
        val fresh = photo("fresh.jpg", android.graphics.Color.GREEN)
        repository.replaceImage(sample, id, fresh, 24, 32)
        val images = repository.imagesOf(sample).first()
        assertEquals(2, images.size)
        val replaced = images.single { it.imageId == id }
        assertEquals("context", replaced.viewType)
        assertEquals(fresh.absolutePath, replaced.filePath)
        assertEquals(sha256Streaming(fresh), replaced.sha256)
        assertEquals(fresh.length(), replaced.fileSize)
        assertFalse(old.exists())
        assertTrue(untouched.exists())
        repository.deleteImage(id)
        assertFalse(fresh.exists())
        assertEquals(1, repository.imagesOf(sample).first().size)
    }

    @Test fun failedRetakeKeepsOriginalAndDeclaredPhotosCannotChange(): Unit = runBlocking {
        val sample = repository.createSample("unknown", "leaf", "unknown")
        val old = photo("original.jpg", android.graphics.Color.RED)
        val id = repository.addImage(sample, "context", old, "image/jpeg", 24, 32)
        try { repository.replaceImage(sample, id, File(folder, "missing.jpg"), 24, 32); fail("Missing replacement accepted") }
        catch (_: IllegalArgumentException) { }
        assertEquals(old.absolutePath, db.imageDao().byId(id)?.filePath)
        assertTrue(old.exists())
        db.sampleDao().setUploadId(sample, "declared-session")
        try { repository.deleteImage(id); fail("Declared image deleted") }
        catch (_: com.example.citruscollect.network.UploadException) { }
        val fresh = photo("replacement.jpg", android.graphics.Color.GREEN)
        try { repository.replaceImage(sample, id, fresh, 24, 32); fail("Declared image replaced") }
        catch (_: com.example.citruscollect.network.UploadException) { }
        assertTrue(old.exists())
        assertEquals(old.absolutePath, db.imageDao().byId(id)?.filePath)
    }

    @Test fun limitAllowsRetakeAndDeletingLastPhotoLeavesNoRows(): Unit = runBlocking {
        val sample = repository.createSample("unknown", "leaf", "unknown")
        repeat(12) { index -> repository.addImage(sample, "close_up", photo("$index.jpg", index), "image/jpeg", 24, 32) }
        try { repository.addImage(sample, "close_up", photo("overflow.jpg", 1), "image/jpeg", 24, 32); fail("13th image accepted") }
        catch (_: com.example.citruscollect.network.UploadException) { }
        val target = repository.imagesOf(sample).first().first()
        repository.replaceImage(sample, target.imageId, photo("retake.jpg", 2), 24, 32)
        assertEquals(12, repository.imagesOf(sample).first().size)
        repository.imagesOf(sample).first().forEach { repository.deleteImage(it.imageId) }
        assertTrue(repository.imagesOf(sample).first().isEmpty())
    }

    @Test fun firstPhotoCreatesRecordAndLastPhotoCanDeleteRecord(): Unit = runBlocking {
        val sample = com.example.citruscollect.util.UuidV7.generate()
        assertNull(db.sampleDao().byId(sample))
        try {
            repository.addImage(sample, "close_up", File(folder, "missing.jpg"), "image/jpeg", 24, 32, createIfMissing = true)
            fail("Missing first photo accepted")
        } catch (_: com.example.citruscollect.network.UploadException) { }
        assertNull(db.sampleDao().byId(sample))
        val file = photo("first.jpg", android.graphics.Color.GREEN)
        val id = repository.addImage(sample, "close_up", file, "image/jpeg", 24, 32, createIfMissing = true)
        assertNotNull(db.sampleDao().byId(sample))
        assertTrue(repository.deleteImage(id, deleteRecordIfLast = true))
        assertNull(db.sampleDao().byId(sample))
        assertFalse(file.exists())
    }

    @Test fun cleanupOnlyRemovesAbandonedBlanksAndPreservesExplicitRetake(): Unit = runBlocking {
        val abandoned = repository.createSample("unknown", "leaf", "unknown")
        val meaningful = repository.createSample("unknown", "leaf", "unknown", note = "keep my notes")
        val declared = repository.createSample("unknown", "leaf", "unknown")
        db.sampleDao().setUploadId(declared, "declared")
        val kept = repository.createSample("unknown", "leaf", "unknown")
        val id = repository.addImage(kept, "close_up", photo("kept.jpg", 1), "image/jpeg", 24, 32)
        assertFalse(repository.deleteImage(id))
        assertEquals("needs_photos", db.sampleDao().byId(kept)?.uploadState)
        assertEquals(1, repository.cleanupAbandonedEmptyDrafts())
        assertNull(db.sampleDao().byId(abandoned))
        assertNotNull(db.sampleDao().byId(meaningful))
        assertNotNull(db.sampleDao().byId(declared))
        assertNotNull(db.sampleDao().byId(kept))
        repository.addImage(kept, "close_up", photo("new.jpg", 2), "image/jpeg", 24, 32)
        assertEquals("draft", db.sampleDao().byId(kept)?.uploadState)
    }

    @Test fun everyCapturedPhotoBecomesItsOwnRecord(): Unit = runBlocking {
        val first = repository.capturePhoto(photo("a.jpg", 1), "image/jpeg", 24, 32)
        val second = repository.capturePhoto(photo("b.jpg", 2), "image/jpeg", 24, 32)
        assertNotEquals(first, second)
        val firstImage = repository.imagesOf(first).first().single()
        assertEquals("close_up", firstImage.viewType)
        assertTrue(firstImage.sha256.isNotBlank())
        assertEquals(1, repository.imagesOf(second).first().size)
        assertEquals("draft", db.sampleDao().byId(first)?.uploadState)
        assertEquals("draft", db.sampleDao().byId(second)?.uploadState)
        assertEquals(2, repository.observePending().first().size)
    }

    @Test fun rejectedCaptureLeavesNoRecordBehind(): Unit = runBlocking {
        try {
            repository.capturePhoto(File(folder, "missing.jpg"), "image/jpeg", 24, 32)
            fail("Missing file accepted")
        } catch (_: com.example.citruscollect.network.UploadException) { }
        assertTrue(repository.observePending().first().isEmpty())
    }

    @Test fun discardRemovesRowAndLocalOriginalButDeclaredRecordsStay(): Unit = runBlocking {
        val discardable = repository.capturePhoto(photo("c.jpg", 3), "image/jpeg", 24, 32)
        val file = File(repository.imagesOf(discardable).first().single().filePath)
        assertTrue(repository.discardRecord(discardable))
        assertNull(db.sampleDao().byId(discardable))
        assertFalse(file.exists())

        val declared = repository.capturePhoto(photo("d.jpg", 4), "image/jpeg", 24, 32)
        db.sampleDao().setUploadId(declared, "declared-session")
        try { repository.discardRecord(declared); fail("Declared record discarded") }
        catch (_: com.example.citruscollect.network.UploadException) { }
        assertNotNull(db.sampleDao().byId(declared))
    }
}
