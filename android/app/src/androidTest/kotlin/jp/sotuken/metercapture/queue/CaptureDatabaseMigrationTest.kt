package jp.sotuken.metercapture.queue

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import jp.sotuken.metercapture.inspection.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CaptureDatabaseMigrationTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private suspend fun migrated(version: Int, verify: suspend (CaptureDatabase) -> Unit) {
        val name = "migration-p3-${System.nanoTime()}.db"
        val path = context.getDatabasePath(name)
        path.parentFile?.mkdirs()
        try {
            SQLiteDatabase.openOrCreateDatabase(path, null).use { db ->
                db.execSQL("CREATE TABLE queue_items (localId TEXT NOT NULL PRIMARY KEY, imagePath TEXT NOT NULL, capturedAt TEXT NOT NULL, deviceName TEXT, operatorValue REAL, operatorNote TEXT, sendState TEXT NOT NULL, retryCount INTEGER NOT NULL, lastError TEXT, sentAt TEXT)")
                if (version >= 2) db.execSQL("ALTER TABLE queue_items ADD COLUMN sentVia TEXT")
                if (version >= 3) db.execSQL("ALTER TABLE queue_items ADD COLUMN receiverId TEXT")
                if (version >= 4) { db.execSQL("ALTER TABLE queue_items ADD COLUMN deviceId TEXT"); db.execSQL("ALTER TABLE queue_items ADD COLUMN deviceIdSource TEXT") }
                db.execSQL("INSERT INTO queue_items (localId, imagePath, capturedAt, sendState, retryCount) VALUES ('old', '/capture.jpg', '2026-11-06T00:00:00Z', 'PENDING', 0)")
                db.version = version
            }
            val db = Room.databaseBuilder(context, CaptureDatabase::class.java, name).addMigrations(*CaptureDatabase.ALL_MIGRATIONS).build()
            try { verify(db) } finally { db.close() }
        } finally { context.deleteDatabase(name) }
    }
    @Test fun migration4To5KeepsPhotosWithNullInspection() = runTest { migrated(4) { db ->
        val photo = requireNotNull(db.queueItemDao().findById("old")); assertNull(photo.inspectionId); assertNull(photo.inspectionName); assertNull(photo.routeId); assertEquals("/capture.jpg", photo.imagePath); assertEquals(SendState.PENDING, photo.sendState)
    } }
    @Test fun migration4To5CreatesInspectionsTableAndIndex() = runTest { migrated(4) { db ->
        val item = Inspection("INS-test", "点検", null, null, null, null, null, InspectionState.IN_PROGRESS, "2026-11-06T00:00:00Z")
        db.inspectionDao().insert(item); assertEquals(item, db.inspectionDao().findById(item.inspectionId))
        db.openHelper.writableDatabase.query("SELECT name FROM sqlite_master WHERE type='index' AND name='index_queue_items_inspectionId'").use { cursor -> assertTrue(cursor.moveToFirst()) }
    } }
    @Test fun migrationFromVersionOneReachesFive() = runTest { migrated(1) { db ->
        val item = requireNotNull(db.queueItemDao().findById("old")); assertNull(item.inspectionId); assertNull(item.sentVia); assertNull(item.receiverId); assertNull(item.deviceId); assertEquals(5, db.openHelper.writableDatabase.version)
    } }
}
