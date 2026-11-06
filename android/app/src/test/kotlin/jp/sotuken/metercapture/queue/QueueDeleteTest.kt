package jp.sotuken.metercapture.queue

import java.io.File
import jp.sotuken.metercapture.queue.sender.FolderSender
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class QueueDeleteTest {
    @Test
    fun missingIdIsNotFound() = runTest {
        assertEquals(DeleteResult.NOT_FOUND, RoomQueueStore(FakeQueueDao()).delete("missing"))
    }

    @Test
    fun failedSentAndHeldItemsCanBeDeleted() = runTest {
        for (state in listOf(SendState.PENDING, SendState.FAILED, SendState.SENT)) {
            val image = File.createTempFile("queue-delete", ".jpg")
            try {
                val dao = FakeQueueDao()
                val store = RoomQueueStore(dao) { "old-pc" }
                val id = store.enqueue(image, CaptureMeta(null, null, null))
                dao.update(requireNotNull(dao.findById(id)).copy(sendState = state))
                assertEquals(DeleteResult.DELETED, store.delete(id))
                assertFalse(image.exists())
            } finally {
                image.delete()
            }
        }
    }

    @Test
    fun latestStateIsCheckedAgainBeforeDeleting() = runTest {
        val image = File.createTempFile("queue-delete", ".jpg")
        try {
            val backing = FakeQueueDao()
            var reads = 0
            val dao = object : QueueDao by backing {
                override suspend fun findById(localId: String): QueueItem? {
                    val item = backing.findById(localId)
                    if (++reads == 1 && item != null) {
                        backing.update(item.copy(sendState = SendState.SENDING))
                    }
                    return item
                }
            }
            val store = RoomQueueStore(dao)
            val id = store.enqueue(image, CaptureMeta(null, null, null))
            assertEquals(DeleteResult.SENDING, store.delete(id))
            assertTrue(image.exists())
            assertEquals(1, store.observeQueue().first().size)
        } finally {
            image.delete()
        }
    }

    @Test
    fun imageReferencedByAnotherRowIsRetained() = runTest {
        val image = File.createTempFile("queue-delete", ".jpg")
        try {
            val store = RoomQueueStore(FakeQueueDao())
            val id = store.enqueue(image, CaptureMeta(null, null, null))
            store.enqueue(image, CaptureMeta(null, null, null))
            assertEquals(DeleteResult.DELETED, store.delete(id))
            assertTrue(image.exists())
            assertEquals(1, store.observeQueue().first().size)
        } finally {
            image.delete()
        }
    }

    @Test
    fun fileDeletionFailureDoesNotRestoreRow() = runTest {
        val dir = kotlin.io.path.createTempDirectory().toFile()
        try {
            File(dir, "child").writeText("prevents deleting directory")
            val store = RoomQueueStore(FakeQueueDao())
            val id = store.enqueue(dir, CaptureMeta(null, null, null))
            assertEquals(DeleteResult.DELETED, store.delete(id))
            assertTrue(dir.exists())
            assertTrue(store.observeQueue().first().isEmpty())
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test
    fun deleteRemovesRowImageAndOutboxAndReducesObservedCount() = runTest {
        val dir = kotlin.io.path.createTempDirectory().toFile()
        try {
            val image = File(dir, "photo.jpg").apply { writeText("image") }
            val outbox = File(dir, "outbox")
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao, outboxDir = outbox)
            val id = store.enqueue(image, CaptureMeta(null, null, null))
            FolderSender(outbox).send(requireNotNull(dao.findById(id))).getOrThrow()
            assertEquals(1, store.observeQueue().first().size)
            assertEquals(DeleteResult.DELETED, store.delete(id))
            assertNull(dao.findById(id))
            assertFalse(image.exists())
            assertTrue(outbox.listFiles()!!.isEmpty())
            assertEquals(0, store.observeQueue().first().size)
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test
    fun sendingCannotBeDeletedAndUnknownIdIsNotFound() = runTest {
        val image = File.createTempFile("queue-delete", ".jpg")
        try {
            val store = RoomQueueStore(FakeQueueDao())
            val id = store.enqueue(image, CaptureMeta(null, null, null))
            store.markSending(id)
            assertEquals(DeleteResult.SENDING, store.delete(id))
            assertEquals(1, store.observeQueue().first().size)
            assertTrue(image.exists())
            assertEquals(DeleteResult.NOT_FOUND, store.delete("missing"))
        } finally {
            image.delete()
        }
    }
}
