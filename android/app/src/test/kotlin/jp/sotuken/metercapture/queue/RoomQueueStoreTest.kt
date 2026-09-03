package jp.sotuken.metercapture.queue

import java.io.File
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RoomQueueStoreTest {
    @Test
    fun enqueueReturnsLocalIdThatCanBeFound() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())

            assertTrue(localId.isNotBlank())
            assertNotNull(dao.findById(localId))
        }
    }

    @Test
    fun enqueueCreatesPendingItemWithInitialValues() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())
            val item = dao.findById(localId)

            assertNotNull(item)
            assertEquals(SendState.PENDING, item?.sendState)
            assertEquals(0, item?.retryCount)
            assertEquals(null, item?.lastError)
            assertEquals(null, item?.sentAt)
        }
    }

    @Test
    fun enqueueStoresAbsoluteImagePath() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())

            assertEquals(imageFile.absolutePath, dao.findById(localId)?.imagePath)
        }
    }

    @Test
    fun enqueuePreservesCaptureMetaValues() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)
        val meta = CaptureMeta(
            deviceName = "Pressure meter A",
            operatorValue = 12.5,
            operatorNote = "verified",
        )

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, meta)
            val item = dao.findById(localId)

            assertEquals(meta.deviceName, item?.deviceName)
            assertEquals(meta.operatorValue, item?.operatorValue)
            assertEquals(meta.operatorNote, item?.operatorNote)
        }
    }

    @Test
    fun enqueuePreservesNullCaptureMetaValues() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())
            val item = dao.findById(localId)

            assertEquals(null, item?.deviceName)
            assertEquals(null, item?.operatorValue)
            assertEquals(null, item?.operatorNote)
        }
    }

    @Test
    fun enqueueGeneratesDifferentLocalIds() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val firstLocalId = store.enqueue(imageFile, emptyMeta())
            val secondLocalId = store.enqueue(imageFile, emptyMeta())

            assertTrue(firstLocalId != secondLocalId)
        }
    }

    @Test
    fun observeQueueContainsEveryEnqueuedItem() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val firstLocalId = store.enqueue(imageFile, emptyMeta())
            val secondLocalId = store.enqueue(imageFile, emptyMeta())
            val items = store.observeQueue().first()

            assertEquals(2, items.size)
            assertEquals(setOf(firstLocalId, secondLocalId), items.map { it.localId }.toSet())
        }
    }

    private suspend fun withTemporaryImage(block: suspend (File) -> Unit) {
        val imageFile = File.createTempFile("queue-store-test-", ".jpg")
        try {
            block(imageFile)
        } finally {
            imageFile.delete()
        }
    }

    private fun emptyMeta() = CaptureMeta(
        deviceName = null,
        operatorValue = null,
        operatorNote = null,
    )
}
