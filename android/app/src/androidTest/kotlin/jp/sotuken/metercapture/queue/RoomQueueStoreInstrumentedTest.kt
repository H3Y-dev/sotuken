package jp.sotuken.metercapture.queue

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RoomQueueStoreInstrumentedTest {
    private val context: Context
        get() = ApplicationProvider.getApplicationContext()

    @Test
    fun migrationFromVersionOnePreservesQueuedImagesAndAddsNullableSentVia() = runTest {
        val name = "queue-migration-${System.nanoTime()}.db"
        val path = context.getDatabasePath(name)
        path.parentFile?.mkdirs()
        try {
            SQLiteDatabase.openOrCreateDatabase(path, null).use { oldDb ->
                oldDb.execSQL("""
                    CREATE TABLE queue_items (
                        localId TEXT NOT NULL PRIMARY KEY, imagePath TEXT NOT NULL,
                        capturedAt TEXT NOT NULL, deviceName TEXT, operatorValue REAL,
                        operatorNote TEXT, sendState TEXT NOT NULL, retryCount INTEGER NOT NULL,
                        lastError TEXT, sentAt TEXT
                    )
                """.trimIndent())
                oldDb.execSQL("""
                    INSERT INTO queue_items (localId, imagePath, capturedAt, sendState, retryCount)
                    VALUES ('existing', '/private/capture.jpg', '2026-10-21T10:00:00Z', 'PENDING', 0)
                """.trimIndent())
                oldDb.version = 1
            }
            val database = Room.databaseBuilder(context, CaptureDatabase::class.java, name)
                .addMigrations(CaptureDatabase.MIGRATION_1_2)
                .build()
            try {
                val item = database.queueItemDao().findById("existing")
                assertNotNull(item)
                assertEquals("/private/capture.jpg", item?.imagePath)
                assertEquals(SendState.PENDING, item?.sendState)
                assertNull(item?.sentVia)
                val store = RoomQueueStore(database.queueItemDao())
                store.markSending("existing")
                store.markSent("existing", QueueItem.VIA_HTTP)
                assertEquals(QueueItem.VIA_HTTP, database.queueItemDao().findById("existing")?.sentVia)
            } finally {
                database.close()
            }
        } finally {
            context.deleteDatabase(name)
        }
    }

    @Test
    fun enqueueWithRoomCanBeReadBack() = runTest {
        val database = Room.inMemoryDatabaseBuilder(context, CaptureDatabase::class.java).build()
        val imageFile = File.createTempFile("room-queue-", ".jpg", context.cacheDir)

        try {
            val store = RoomQueueStore(database.queueItemDao())
            val localId = store.enqueue(imageFile, emptyMeta())
            val item = database.queueItemDao().findById(localId)

            assertNotNull(item)
            assertEquals(SendState.PENDING, item?.sendState)
            assertEquals(0, item?.retryCount)
            assertNull(item?.lastError)
            assertNull(item?.sentAt)
            assertNull(item?.sentVia)
        } finally {
            database.close()
            imageFile.delete()
        }
    }

    @Test
    fun sendStatesRoundTripThroughRoom() = runTest {
        val database = Room.inMemoryDatabaseBuilder(context, CaptureDatabase::class.java).build()
        val imageFile = File.createTempFile("room-queue-", ".jpg", context.cacheDir)

        try {
            val dao = database.queueItemDao()
            val localId = RoomQueueStore(dao).enqueue(imageFile, emptyMeta())
            val initialItem = requireNotNull(dao.findById(localId))

            for (state in listOf(SendState.PENDING, SendState.SENDING, SendState.SENT, SendState.FAILED)) {
                dao.update(initialItem.copy(sendState = state))

                assertEquals(state, dao.findById(localId)?.sendState)
            }
        } finally {
            database.close()
            imageFile.delete()
        }
    }

    @Test
    fun observeQueueReturnsItemsFromRoomFlow() = runTest {
        val database = Room.inMemoryDatabaseBuilder(context, CaptureDatabase::class.java).build()
        val imageFile = File.createTempFile("room-queue-", ".jpg", context.cacheDir)

        try {
            val store = RoomQueueStore(database.queueItemDao())
            val firstLocalId = store.enqueue(imageFile, emptyMeta())
            val secondLocalId = store.enqueue(imageFile, emptyMeta())

            val items = store.observeQueue().first()

            assertEquals(2, items.size)
            assertEquals(setOf(firstLocalId, secondLocalId), items.map { it.localId }.toSet())
        } finally {
            database.close()
            imageFile.delete()
        }
    }

    @Test
    fun enqueuedItemRemainsAfterDatabaseIsReopened() = runTest {
        context.deleteDatabase(persistentDatabaseName)
        val imageFile = File.createTempFile("room-queue-", ".jpg", context.cacheDir)
        var firstDatabase: CaptureDatabase? = null
        var reopenedDatabase: CaptureDatabase? = null

        try {
            firstDatabase = Room.databaseBuilder(
                context,
                CaptureDatabase::class.java,
                persistentDatabaseName,
            ).build()
            val localId = RoomQueueStore(firstDatabase.queueItemDao()).enqueue(
                imageFile,
                CaptureMeta(
                    deviceName = "test-device",
                    operatorValue = 12.5,
                    operatorNote = "persisted",
                ),
            )
            firstDatabase.close()
            firstDatabase = null

            reopenedDatabase = Room.databaseBuilder(
                context,
                CaptureDatabase::class.java,
                persistentDatabaseName,
            ).build()
            val restoredItem = reopenedDatabase.queueItemDao().findById(localId)

            assertNotNull(restoredItem)
            assertEquals(imageFile.absolutePath, restoredItem?.imagePath)
            assertEquals("test-device", restoredItem?.deviceName)
            assertEquals(12.5, restoredItem?.operatorValue)
            assertEquals("persisted", restoredItem?.operatorNote)
            assertEquals(SendState.PENDING, restoredItem?.sendState)
        } finally {
            firstDatabase?.close()
            reopenedDatabase?.close()
            context.deleteDatabase(persistentDatabaseName)
            imageFile.delete()
        }
    }

    @Test
    fun markSendingUpdatesStateInRoom() = runTest {
        val database = Room.inMemoryDatabaseBuilder(context, CaptureDatabase::class.java).build()
        val imageFile = File.createTempFile("room-queue-", ".jpg", context.cacheDir)

        try {
            val store = RoomQueueStore(database.queueItemDao())
            val localId = store.enqueue(imageFile, emptyMeta())

            store.markSending(localId)

            val item = database.queueItemDao().findById(localId)
            assertEquals(SendState.SENDING, item?.sendState)
        } finally {
            database.close()
            imageFile.delete()
        }
    }

    @Test
    fun fullHappyPathTransitionsPersistInRoom() = runTest {
        val database = Room.inMemoryDatabaseBuilder(context, CaptureDatabase::class.java).build()
        val imageFile = File.createTempFile("room-queue-", ".jpg", context.cacheDir)

        try {
            val dao = database.queueItemDao()
            val store = RoomQueueStore(dao)
            val localId = store.enqueue(imageFile, emptyMeta())
            assertEquals(SendState.PENDING, dao.findById(localId)?.sendState)

            store.markSending(localId)
            assertEquals(SendState.SENDING, dao.findById(localId)?.sendState)

            store.markSent(localId, QueueItem.VIA_HTTP)
            val sentItem = dao.findById(localId)
            assertEquals(SendState.SENT, sentItem?.sendState)
            assertEquals(QueueItem.VIA_HTTP, sentItem?.sentVia)
            assertNotNull(sentItem?.sentAt)
        } finally {
            database.close()
            imageFile.delete()
        }
    }

    @Test
    fun markFailedThenRetryRoundTripsThroughRoom() = runTest {
        val database = Room.inMemoryDatabaseBuilder(context, CaptureDatabase::class.java).build()
        val imageFile = File.createTempFile("room-queue-", ".jpg", context.cacheDir)

        try {
            val dao = database.queueItemDao()
            val store = RoomQueueStore(dao)
            val localId = store.enqueue(imageFile, emptyMeta())

            store.markSending(localId)
            store.markFailed(localId, "network error")

            val failedItem = dao.findById(localId)
            assertEquals(SendState.FAILED, failedItem?.sendState)
            assertEquals("network error", failedItem?.lastError)
            assertEquals(1, failedItem?.retryCount)

            store.retry(localId)

            val retriedItem = dao.findById(localId)
            assertEquals(SendState.PENDING, retriedItem?.sendState)
            assertNull(retriedItem?.lastError)
        } finally {
            database.close()
            imageFile.delete()
        }
    }

    @Test
    fun illegalTransitionThrowsAndRoomStateUnchanged() = runTest {
        val database = Room.inMemoryDatabaseBuilder(context, CaptureDatabase::class.java).build()
        val imageFile = File.createTempFile("room-queue-", ".jpg", context.cacheDir)

        try {
            val dao = database.queueItemDao()
            val store = RoomQueueStore(dao)
            val localId = store.enqueue(imageFile, emptyMeta())

            var threw = false
            try {
                store.markSent(localId, QueueItem.VIA_HTTP)
            } catch (e: IllegalStateException) {
                threw = true
            }

            assertTrue(threw)
            assertEquals(SendState.PENDING, dao.findById(localId)?.sendState)
        } finally {
            database.close()
            imageFile.delete()
        }
    }

    @Test
    fun recoverInterruptedSendsResetsSendingItemsInRoom() = runTest {
        val database = Room.inMemoryDatabaseBuilder(context, CaptureDatabase::class.java).build()
        val imageFile = File.createTempFile("room-queue-", ".jpg", context.cacheDir)

        try {
            val dao = database.queueItemDao()
            val store = RoomQueueStore(dao)
            val sendingId = store.enqueue(imageFile, emptyMeta())
            store.markSending(sendingId)

            val sentId = store.enqueue(imageFile, emptyMeta())
            store.markSending(sentId)
            store.markSent(sentId, QueueItem.VIA_HTTP)

            store.recoverInterruptedSends()

            assertEquals(SendState.PENDING, dao.findById(sendingId)?.sendState)
            assertEquals(SendState.SENT, dao.findById(sentId)?.sendState)
        } finally {
            database.close()
            imageFile.delete()
        }
    }

    private fun emptyMeta() = CaptureMeta(
        deviceName = null,
        operatorValue = null,
        operatorNote = null,
    )

    private companion object {
        const val persistentDatabaseName = "room-queue-store-instrumented-test.db"
    }
}
